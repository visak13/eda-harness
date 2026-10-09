// The site's tool reference examples (s-bd0cf6288c): seed the Tidewater demo on this run's private board, then call
// every board tool once through docs/site/tools/capture_tool_examples.py and write docs/site/tool-examples.json.
// The capture runs with the same allowlisted env as the board (no fleet pointer passes), a dead pool and no broker.
//   npx playwright test -c playwright.guide.config.ts tools
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { REPO_DIR } from "../e2e/board";
import { BASE, expect, test } from "../e2e/fixtures";
import { deadServiceEnv, hermeticEnv } from "../e2e/hermeticEnv";
import { makeArt } from "./art";
import { seedDemo } from "./demo.seed";

const SITE = path.join(REPO_DIR, "..", "docs", "site");
const OUT = process.env.TOOL_EXAMPLES_OUT ?? path.join(SITE, "tool-examples.json");

test.use({ boardFile: "guide-tools" });

test("one real reply per board tool", async () => {
  test.setTimeout(300_000);
  const demo = await seedDemo(await makeArt());
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "tool-examples-"));
  const demoFile = path.join(tmp, "demo.json");
  fs.writeFileSync(demoFile, JSON.stringify(demo));
  const home = process.env.EDP8_E2E_HOME!;
  const env = {
    ...hermeticEnv(process.env, home),
    ...deadServiceEnv(9),
    EDP_POOL_URL: "http://127.0.0.1:9",
    EDP8_BOARD_URL: BASE(),
    PYTHONUTF8: "1",
  };
  const py = path.join(REPO_DIR, ".venv", "Scripts", "python.exe");
  const run = spawnSync(py, [path.join(SITE, "tools", "capture_tool_examples.py"), "--board", BASE(), "--demo", demoFile,
    "--home", home, "--out", OUT], { env, encoding: "utf8", timeout: 240_000 });
  console.log(run.stdout);
  if (run.stderr) console.log(run.stderr);
  fs.rmSync(tmp, { recursive: true, force: true });
  expect(run.status, run.stderr).toBe(0);
});
