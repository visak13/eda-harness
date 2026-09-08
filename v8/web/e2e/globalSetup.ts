import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { REPO_DIR, WEB_DIR } from "./board";

// Ensure the SPA bundle the board serves at /ui exists AND is built for the /ui base, then
// leave the board to the per-file worker fixture (fixtures.ts). Post-cutover (EDP8_UI=folio) the board serves the SPA at /ui, so its
// index.html must reference /ui/assets. A dist left over from the /app build phase (or any
// mismatched base) is rebuilt — otherwise every asset 404s under /ui and the specs fail opaquely.
const WEB_BASE = "/ui/";
export default async function globalSetup(): Promise<void> {
  const dist = path.join(REPO_DIR, "src", "edp8", "webapp", "dist", "index.html");
  const builtForUi = fs.existsSync(dist) && fs.readFileSync(dist, "utf8").includes(`${WEB_BASE}assets/`);
  if (!builtForUi) {
    // Pin the base so a stray EDP8_WEB_BASE in the launching shell can't build a mismatched bundle.
    execSync("npm run build", { cwd: WEB_DIR, stdio: "inherit", env: { ...process.env, EDP8_WEB_BASE: WEB_BASE } });
  }
  // The board itself is per spec FILE now — see fixtures.ts (`board` worker fixture).
}
