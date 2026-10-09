// S9 guard G1 (memory e2e-board-cmd-relative-to-v8-not-web): the board is spawned with cwd = v8/, so a relative
// EDP8_BOARD_CMD executable must mean v8/, not wherever the runner started (web/). Free of Playwright imports for vitest.
import fs from "node:fs";
import path from "node:path";

/** `EDP8_BOARD_CMD` split into [exe, ...args]; a relative exe with a path separator (/ or \) is made absolute against repoDir. */
export function resolveBoardCmd(raw: string | undefined, repoDir: string, exists: (p: string) => boolean = fs.existsSync): string[] {
  const parts = (raw ?? "uv run edp8-board").split(" ");
  const exe = parts[0];
  if (/[\\/]/.test(exe) && !path.isAbsolute(exe)) {
    const abs = path.resolve(repoDir, exe);
    const found = [abs, `${abs}.exe`, `${abs}.cmd`].some(exists);
    if (!found) throw new Error(`EDP8_BOARD_CMD "${exe}" not found (resolved to ${abs}); pass an absolute venv path`);
    parts[0] = /\s/.test(abs) ? `"${abs}"` : abs; // the launcher runs under shell:true: quote a path with spaces
  }
  return parts;
}
