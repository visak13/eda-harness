import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { REPO_DIR, WEB_DIR } from "./board";

// Ensure the SPA bundle the board serves at /ui exists, is built for the /ui base AND is not older
// than the sources — then leave the board to the per-file worker fixture (fixtures.ts).
// Post-cutover (EDP8_UI=folio) the board serves the SPA at /ui, so its index.html must reference
// /ui/assets. A dist left over from the /app build phase, a mismatched base, or a dist older than
// any file under web/src (adversary finding #12, 2026-09-10: the suite silently tested a stale
// bundle) is rebuilt.
const WEB_BASE = "/ui/";

function newestMtime(dir: string): number {
  let newest = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) newest = Math.max(newest, newestMtime(p));
    else newest = Math.max(newest, fs.statSync(p).mtimeMs);
  }
  return newest;
}

/** The newest source mtime the bundle depends on (web/src + the build inputs beside it). */
export function newestSourceMtime(): number {
  let newest = newestMtime(path.join(WEB_DIR, "src"));
  const publicDir = path.join(WEB_DIR, "public");
  if (fs.existsSync(publicDir)) newest = Math.max(newest, newestMtime(publicDir));
  for (const f of ["index.html", "vite.config.ts", "package.json", "tsconfig.json"]) {
    const p = path.join(WEB_DIR, f);
    if (fs.existsSync(p)) newest = Math.max(newest, fs.statSync(p).mtimeMs);
  }
  return newest;
}

export default async function globalSetup(): Promise<void> {
  const dist = path.join(REPO_DIR, "src", "edp8", "webapp", "dist", "index.html");
  const builtForUi = fs.existsSync(dist) && fs.readFileSync(dist, "utf8").includes(`${WEB_BASE}assets/`);
  const fresh = builtForUi && fs.statSync(dist).mtimeMs >= newestSourceMtime();
  if (!fresh) {
    console.log(`[e2e] dist ${builtForUi ? "is older than web/src" : "is missing or not built for /ui"} — rebuilding`);
    // Pin the base so a stray EDP8_WEB_BASE in the launching shell can't build a mismatched bundle.
    execSync("npm run build", { cwd: WEB_DIR, stdio: "inherit", env: { ...process.env, EDP8_WEB_BASE: WEB_BASE } });
  }
  // The board itself is per spec FILE now — see fixtures.ts (`board` worker fixture).
}
