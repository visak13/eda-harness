// A throwaway code-server for extension smokes (strategyll-5ec6802121 §2): the pinned build from
// vscode-ext/code-server.lock.json on a spare loopback port, temp user-data and extensions dirs (never
// :9410 or v8/.data/code), the freshly built edp-code vsix installed into its OWN extensions dir, no
// EDP_/EDP8_, PORT or CODE_SERVER_* variable in its env and its own --config in the temp dir, so it can never bind
// :9410 or read the live service's config.yaml (C21 m-9fc373ac00). stop() kills only the pid this module spawned (and its tree).
// Used by code-chat.spec.ts; code-tag.spec.ts keeps its own copy (S5, unchanged).
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { REPO_DIR } from "./board";

export const EXT_DIR = path.join(REPO_DIR, "vscode-ext", "edp-code");
export const VSIX = path.join(EXT_DIR, "edp-code.vsix");

const lock = JSON.parse(fs.readFileSync(path.join(REPO_DIR, "vscode-ext", "code-server.lock.json"), "utf8"));
const SERVER_DIR = path.join(REPO_DIR, ".tools", "code-server", lock.version, lock.server_dir);
const NODE = path.join(SERVER_DIR, lock.node);

export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const a = srv.address();
      const port = typeof a === "object" && a ? a.port : 0;
      srv.close(() => resolve(port));
    });
  });
}

function csEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [k, v] of Object.entries(process.env)) if (!/^(EDP8?_|PORT$|CODE_SERVER_|VSCODE_PROXY_URI$)/i.test(k)) env[k] = v;
  env.EXTENSIONS_GALLERY = "{}";
  return env;
}

export type CodeServer = { port: number; userDir: string; extDir: string; stop: () => void };

export async function startCodeServer(tmp: string, settings: Record<string, unknown>): Promise<CodeServer> {
  const userDir = path.join(tmp, "user-data");
  const extDir = path.join(tmp, "extensions");
  fs.mkdirSync(path.join(userDir, "User"), { recursive: true });
  fs.mkdirSync(path.join(userDir, "Machine"), { recursive: true });
  fs.mkdirSync(extDir, { recursive: true });
  const all = JSON.stringify({
    "security.workspace.trust.enabled": false, "workbench.startupEditor": "none", "workbench.tips.enabled": false,
    "telemetry.telemetryLevel": "off", "extensions.autoUpdate": false, "git.openRepositoryInParentFolders": "never",
    ...settings,
  }, null, 1);
  // edp.* settings are machine-scoped: a remote (code-server) window reads them from Machine/settings.json
  fs.writeFileSync(path.join(userDir, "User", "settings.json"), all);
  fs.writeFileSync(path.join(userDir, "Machine", "settings.json"), all);
  // its own config file: the live service's config.yaml never applies here
  const config = path.join(tmp, "config.yaml");
  fs.writeFileSync(config, "auth: none\ncert: false\n");
  const inst = spawnSync(NODE, [SERVER_DIR, "--config", config, "--user-data-dir", userDir, "--extensions-dir", extDir, "--install-extension", VSIX, "--force"],
    { env: csEnv(), encoding: "utf8", timeout: 120_000 });
  if (inst.status !== 0) throw new Error(`vsix install failed (${inst.status}): ${inst.stdout}\n${inst.stderr}`);
  const port = await freePort();
  let cs: ChildProcess | null = spawn(NODE, [SERVER_DIR, "--config", config, "--bind-addr", `127.0.0.1:${port}`, "--auth", "none", "--disable-telemetry",
    "--disable-update-check", "--disable-proxy", "--disable-workspace-trust", "--user-data-dir", userDir, "--extensions-dir", extDir],
    { env: csEnv(), stdio: "ignore", windowsHide: true });
  const stop = () => {
    if (cs?.pid && cs.exitCode === null) spawnSync("taskkill", ["/PID", String(cs.pid), "/T", "/F"], { stdio: "ignore" });
    cs = null;
  };
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (cs.exitCode !== null) throw new Error(`code-server exited early (${cs.exitCode})`);
    try { if ((await fetch(`http://127.0.0.1:${port}/healthz`)).ok) return { port, userDir, extDir, stop }; } catch { /* not up */ }
    await new Promise(r => setTimeout(r, 300));
  }
  stop();
  throw new Error("code-server did not answer /healthz within 60 s");
}

/** `/c:/…` folder URL form for a Windows path (les-ca6209874d). */
export const folderParam = (dir: string) => encodeURI("/" + dir.replace(/\\/g, "/").replace(/^([A-Z]):/, (_, d: string) => d.toLowerCase() + ":"));
