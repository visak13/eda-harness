// t-f5bf848f0f Open-topic dialog vs New-epic dialog: shots for scripts/topic_dialog_walk.py. Private board only.
//
//   node scripts/topic_dialog_walk.mjs before|after <board-base-url> <out-dir>
//
// At CSS 1684x875 (the owner's 1852x962 window at 110% zoom) and 1280x800: the New-epic pop-up (Epics → New
// epic) and the Open-topic pop-up (Library → Topics → Open topic), each empty, then filled the same way, each
// scrolled to its footer. `after` also opens a topic with two experts, shoots the one-time links (done state)
// and the topic page it lands on. Each dialog logs its width, its field labels and any horizontal overflow.
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "web", "package.json"));
const { chromium } = require("playwright");

const [mode, base, out] = process.argv.slice(2);
if (!["before", "after"].includes(mode) || !base || !out) {
  console.error("usage: node scripts/topic_dialog_walk.mjs before|after <base-url> <out-dir>");
  process.exit(2);
}
const as = `as=owner&token=${encodeURIComponent(process.env.WALK_OWNER_TOKEN ?? "")}`;
const VIEWPORTS = [[1684, 875], [1280, 800]];
let failures = 0;

async function measure(page, testid, label) {
  const m = await page.evaluate((id) => {
    const d = document.querySelector(`[data-testid="${id}"]`);
    if (!d) return null;
    const r = d.getBoundingClientRect();
    const labels = [...d.querySelectorAll("label, legend")].map((l) => l.textContent.trim().replace(/\s+/g, " ")).filter(Boolean);
    return { width: Math.round(r.width), left: Math.round(r.left), top: Math.round(r.top), labels,
      hOverflow: d.scrollWidth > d.clientWidth + 2, name: d.getAttribute("aria-label"),
      focused: document.activeElement?.getAttribute("data-testid") ?? null };
  }, testid);
  const ok = Boolean(m) && !m.hOverflow;
  if (!ok) failures += 1;
  console.log(`${ok ? "PASS" : "FAIL"} ${label}: ${JSON.stringify(m)}`);
}

const browser = await chromium.launch();
try {
  for (const [width, height] of VIEWPORTS) {
    const tag = `${width}x${height}`;
    const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const shot = async (name) => {
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(out, `${mode}-${name}-${tag}.png`) });
      console.log(`shot ${mode}-${name}-${tag}.png`);
    };
    const toFooter = async (testid) => {
      await page.evaluate((id) => { const d = document.querySelector(`[data-testid="${id}"]`); if (d) d.scrollTop = d.scrollHeight; }, testid);
    };
    // the New-epic pop-up
    await page.goto(`${base}/ui/epics?${as}`);
    await page.getByTestId("new-epic-open").click();
    await page.getByTestId("new-epic-dialog").waitFor();
    await page.getByTestId("new-epic-model-sme").waitFor();
    await measure(page, "new-epic-dialog", `epic ${tag}`);
    await shot("epic-empty");
    await page.getByTestId("new-epic-title").fill("Python testing craft");
    await page.getByTestId("new-epic-words").fill("Keep our pytest craft current: fixtures, markers, CI.");
    await page.getByTestId("new-epic-tags").fill("python, testing");
    await shot("epic-filled");
    await toFooter("new-epic-dialog");
    await shot("epic-footer");
    await page.keyboard.press("Escape");
    // the Open-topic pop-up
    await page.goto(`${base}/ui/library/topics?${as}`);
    await page.getByTestId("topic-open-button").click();
    await page.getByTestId("topic-open-dialog").waitFor();
    if (mode === "after") await page.getByTestId("topic-open-model-sme").waitFor();
    await measure(page, "topic-open-dialog", `topic ${tag}`);
    await shot("topic-empty");
    await page.getByTestId("topic-open-title").fill("Python testing craft");
    if (mode === "after") await page.getByTestId("topic-open-words").fill("Keep our pytest craft current: fixtures, markers, CI.");
    await page.getByTestId("topic-open-tags").fill("python, testing");
    if (mode === "after") await page.getByTestId("topic-open-experts").fill("priya, dana");
    await page.getByTestId("topic-open-seed").fill("https://docs.pytest.org/en/stable/");
    await shot("topic-filled");
    await toFooter("topic-open-dialog");
    await shot("topic-footer");
    if (mode === "after" && width === 1684) {
      // open it for real: two experts, their one-time links in the done state, then the topic page
      await page.getByTestId("topic-open-model-sme").selectOption("gpt-6-sol");
      await page.getByTestId("topic-open-effort-sme").selectOption("high");
      await page.getByTestId("topic-open-create").click();
      await page.getByTestId("topic-open-links").waitFor();
      const links = await page.getByTestId("topic-open-link").allInnerTexts();
      console.log(`${links.length === 2 ? "PASS" : "FAIL"} expert links shown once: ${links.map((l) => l.split("\n")[0]).join(", ")}`);
      if (links.length !== 2) failures += 1;
      await toFooter("topic-open-dialog");
      await shot("topic-done-links");
      await page.getByTestId("topic-open-go").click();
      await page.getByTestId("topic-page").waitFor();
      const words = await page.getByTestId("topic-words").innerText();
      const seat = await page.getByTestId("topic-seat").innerText();
      const ok = words.includes("Keep our pytest craft current") && seat.includes("gpt-6-sol at high");
      console.log(`${ok ? "PASS" : "FAIL"} topic page: words=${JSON.stringify(words)} seat=${JSON.stringify(seat)}`);
      if (!ok) failures += 1;
      await shot("topic-page");
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}
console.log(failures ? `${failures} FAIL` : "ALL PASS");
if (mode === "after" && failures) process.exit(1);
