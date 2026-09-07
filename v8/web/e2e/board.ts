// SEAM (Playwright against a real spawned board). One board process on a free port with
// temp EDP8_DB/EDP8_HOME, EDP8_EMBEDDER=none, EDP8_ADMIN_TOKEN=t, seeded via /v1 — the
// production endpoints, not mocks. Shared by globalSetup/globalTeardown (same runner
// process) and read by specs through process.env.EDP8_E2E_BASE. (LL §9.3 / design §4.4c.)
import { type ChildProcess, spawn } from "node:child_process";
import { createServer } from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const WEB_DIR = path.resolve(HERE, "..");
export const REPO_DIR = path.resolve(WEB_DIR, ".."); // v8/

export const ADMIN = "t";
let board: ChildProcess | null = null;
let tmpHome: string | null = null;

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      srv.close(() => resolve(port));
    });
  });
}

async function waitHealthy(base: string, timeoutMs = 40_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (board && board.exitCode !== null) throw new Error(`board exited early (code ${board.exitCode})`);
    try {
      const r = await fetch(`${base}/healthz`);
      if (r.ok && (await r.json()).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`board did not become healthy at ${base} within ${timeoutMs}ms`);
}

async function post(base: string, path_: string, body: unknown, headers: Record<string, string>): Promise<unknown> {
  const r = await fetch(`${base}${path_}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  const j = (await r.json()) as { ok: boolean; value?: unknown; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`POST ${path_} failed: ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

export interface Seeded {
  base: string;
  epic: string;
}

/** Spawn a board, wait healthy, seed owner + one epic. Returns base URL + seeded ids. */
export async function startBoard(): Promise<Seeded> {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "edp8-e2e-"));

  // Default to the documented `uv run edp8-board`; EDP8_BOARD_CMD overrides it (e.g. the
  // venv console script `edp8-board`) to skip a cold `uv` sync on CI / pool shells.
  const cmd = (process.env.EDP8_BOARD_CMD ?? "uv run edp8-board").split(" ");
  board = spawn(cmd[0], cmd.slice(1), {
    cwd: REPO_DIR,
    shell: true, // resolve the launcher on PATH (Windows)
    stdio: "inherit",
    env: {
      ...process.env,
      EDP8_HOST: "127.0.0.1",
      EDP8_PORT: String(port),
      EDP8_DB: path.join(tmpHome, "edp8.db"),
      EDP8_HOME: tmpHome,
      EDP8_EMBEDDER: "none",
      EDP8_ADMIN_TOKEN: ADMIN,
      EDP8_LOG: "warning",
    },
  });

  await waitHealthy(base);

  // Seed via /v1, mirroring tests/test_ui_live.py: X-Admin for participants, X-Participant
  // for authored tickets.
  await post(base, "/v1/participants", { type: "human", role: "owner", handle: "owner", id: "owner" }, { "X-Admin": ADMIN });
  await post(base, "/v1/participants", { type: "agent", role: "architect", handle: "arch", id: "arch" }, { "X-Admin": ADMIN });
  const epic = (await post(base, "/v1/tickets", { kind: "epic", work_type: "feature", title: "Spike epic" }, { "X-Participant": "owner" })) as {
    id: string;
  };

  // Expose for the spec + config baseURL (workers spawn after globalSetup, inheriting env).
  process.env.EDP8_E2E_BASE = base;
  process.env.EDP8_E2E_EPIC = epic.id;
  process.env.EDP8_ADMIN_TOKEN = ADMIN;
  return { base, epic: epic.id };
}

export function stopBoard(): void {
  if (board && board.exitCode === null) {
    try {
      board.kill();
    } catch {
      /* already gone */
    }
  }
  board = null;
  if (tmpHome) {
    try {
      fs.rmSync(tmpHome, { recursive: true, force: true });
    } catch {
      /* best effort */
    }
    tmpHome = null;
  }
}
