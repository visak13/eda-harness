// The spawned e2e board's env is built from an ALLOWLIST, never the launching shell's env minus a
// denylist. A seat shell carries fleet pointers (EDP_HOME, EDP8_HOME, EDP8_RUN_DIR, EDP_AGENT_HOME,
// EDP_POOL_URL, EDP8_TOKEN, ...): inherited, the spec board read the fleet's tokens.json/code.json and
// every call 401'd (S14 m-44622648dc, t-ede9ce0717), and a pool URL made it spawn REAL seats for
// seeded test epics (2026-09-08: qa.epic-2b3bea99e0). No EDP* name from the shell ever passes; the
// board gets a private home and run dir, and the spec's own EDP8_* settings are layered on top by
// startBoard. Kept free of Playwright imports so vitest can unit-test it (src/test/hermeticEnv.test.ts).
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
