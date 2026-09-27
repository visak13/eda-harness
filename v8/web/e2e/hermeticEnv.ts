// The spawned e2e board's env is built from an ALLOWLIST, never the launching shell's env minus a
// denylist. A seat shell carries fleet pointers (EDP_HOME, EDP8_HOME, EDP8_RUN_DIR, EDP_AGENT_HOME,
// EDP_POOL_URL, EDP8_TOKEN, ...): inherited, the spec board read the fleet's tokens.json/code.json and
// every call 401'd (S14 m-44622648dc, t-ede9ce0717), and a pool URL made it spawn REAL seats for
// seeded test epics (2026-09-08: qa.epic-2b3bea99e0). No EDP* name from the shell ever passes; the
// board gets a private home and run dir, and the spec's own EDP8_* settings are layered on top by
// startBoard. Kept free of Playwright imports so vitest can unit-test it (src/test/hermeticEnv.test.ts).
import fs from "node:fs";
import path from "node:path";

/** OS/process basics a Python board (and `uv run`, and cmd.exe for shell:true) needs. Upper-case;
 *  matched case-insensitively because Windows spells them `Path`, `SystemRoot`, `windir`, ... */
const ALLOW = new Set([
  "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
  "TEMP", "TMP", "TMPDIR",
  "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH", "USERNAME", "USER", "LOGNAME",
  "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
  "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
  "NUMBER_OF_PROCESSORS", "OS", "LANG", "TZ", "PYTHONUTF8", "PYTHONIOENCODING",
]);
/** Prefixes: uv's own settings (cache dir, python pin), CPU identity, locale. */
const ALLOW_PREFIX = ["UV_", "PROCESSOR_", "LC_"];

export function hermeticEnv(env: NodeJS.ProcessEnv, home: string): NodeJS.ProcessEnv {
  const out: NodeJS.ProcessEnv = {};
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined) continue;
    const K = k.toUpperCase();
    if (K.startsWith("EDP")) continue; // belt and braces: no allowlisted name starts with EDP
    if (ALLOW.has(K) || ALLOW_PREFIX.some((p) => K.startsWith(p))) out[k] = v;
  }
  out.EDP_HOME = home;
  out.EDP8_HOME = home;
  out.EDP8_RUN_DIR = path.join(home, ".run");
  return out;
}

/** qa m-c4f23e49f0: with no EDP_POOL_URL a board derives its pool from EDP_POOL_PORT, whose default is the
 *  fleet's 9301 (a spec board read and could write the fleet's seat caps). Pin the pool port to one nothing
 *  listens on; the broker stays unset (off), and the MCP URL handed to seats is dead too. */
export function deadServiceEnv(deadPort: number): NodeJS.ProcessEnv {
  return {
    EDP_POOL_PORT: String(deadPort),
    EDP8_MCP_URL: `http://127.0.0.1:${deadPort}`,
  };
}

/** t-67d19c5807 (qa m-e633397a42): the spec board's agent home. With a private EDP_HOME the board is not in dev
 *  mode, so its agent home is `<home>/agent-home` and it has no source checkout to fall back on: every card is
 *  missing and a Standard copy fails validation with card_missing, and there is no shipped models.json, so the
 *  role-model picker is empty. Seed a PRIVATE copy of the repo's role cards and models.json there — a pinned fixture, never the repo home itself (the board writes pinned cards into its agent home) and
 *  never the fleet's. Returns the agent home. */
export function seedAgentHome(repoDir: string, home: string): string {
  const agentHome = path.join(home, "agent-home");
  const src = path.join(repoDir, ".claude", "commands");
  const dst = path.join(agentHome, ".claude", "commands");
  fs.mkdirSync(dst, { recursive: true });
  for (const f of fs.readdirSync(src)) if (f.endsWith(".md")) fs.copyFileSync(path.join(src, f), path.join(dst, f));
  const models = path.join(repoDir, "models.json");
  if (fs.existsSync(models)) fs.copyFileSync(models, path.join(agentHome, "models.json"));
  return agentHome;
}
