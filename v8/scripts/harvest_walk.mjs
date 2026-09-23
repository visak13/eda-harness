// S-HARVEST (s-043eb90ccc) Library clicks for scripts/harvest_walk.py: as the owner, open a proposed doc
// in the Library tab, screenshot its diff, then Approve or Reject it (one ruling per call, so the driver
// reads the brief between them). Private board only.
//
//   node scripts/harvest_walk.mjs <board-base-url> <approve|reject> <doc-id> <out-dir>
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "web", "package.json"));
const { chromium } = require("playwright");

const [base, mode, id, out] = process.argv.slice(2);
if (!base || !["approve", "reject"].includes(mode) || !id || !out) {
  console.error("usage: node scripts/harvest_walk.mjs <base-url> <approve|reject> <doc-id> <out-dir>");
  process.exit(2);
}
const browser = await chromium.launch();
try {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })).newPage();
  const shot = async (name) => { await page.waitForTimeout(600); await page.screenshot({ path: path.join(out, `${name}.png`) }); console.log(`shot ${name}.png`); };

  const n = mode === "approve" ? 1 : 3;
  await page.goto(`${base}/ui/library/knowledge?as=owner&k=${id}`);
  await page.getByTestId("knowledge-detail").waitFor();
  await page.getByTestId("knowledge-diff").waitFor();
  console.log(`source: ${(await page.getByTestId("knowledge-source").innerText()).replace(/\s+/g, " ")}`);
  console.log(`diff: ${(await page.getByTestId("knowledge-diff").innerText()).split("\n").filter((l) => /^[+-]- /.test(l)).join(" | ")}`);
  await shot(`${n}-${mode}-proposal-diff`);
  await page.getByTestId(`knowledge-${mode}`).click();
  await page.getByTestId(`knowledge-${mode}`).waitFor({ state: "detached" });
  const done = mode === "approve" ? "approved" : "rejected";
  console.log(`${done} in the Library`);
  await shot(`${n + 1}-${done}`);
} finally {
  await browser.close();
}
