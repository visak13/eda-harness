import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { REPO_DIR, startBoard, WEB_DIR } from "./board";

// Ensure the SPA bundle the board serves at /app exists, then spawn+seed the board.
export default async function globalSetup(): Promise<void> {
  const dist = path.join(REPO_DIR, "src", "edp8", "webapp", "dist", "index.html");
  if (!fs.existsSync(dist)) {
    execSync("npm run build", { cwd: WEB_DIR, stdio: "inherit" });
  }
  const { base, epic } = await startBoard();
  console.log(`[e2e] board up at ${base} (epic ${epic})`);
}
