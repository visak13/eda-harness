// t-feb26a46d9 design reader mode: shots + clipping measures for scripts/reader_walk.py. Private board only.
//
//   node scripts/reader_walk.mjs before|after <board-base-url> <out-dir> <epic-id> <design-doc-id>
//
// For each width (1280, 1920), with the left rail expanded: the design in its own tab
// (/ui/doc/<id>?source=<epic>) and in the pop-up (the epic page's Design link). Each shot logs whether the
// review is clipped (its right edge past the viewport, its header tools out of view, content wider than
// its box) and whether the comment/index panel is shown. `after` also toggles reader mode off and on.
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "web", "package.json"));
const { chromium } = require("playwright");

const [mode, base, out, epic, doc] = process.argv.slice(2);
if (!["before", "after"].includes(mode) || !base || !out || !epic || !doc) {
  console.error("usage: node scripts/reader_walk.mjs before|after <base-url> <out-dir> <epic-id> <doc-id>");
  process.exit(2);
}
const as = `as=owner&token=${encodeURIComponent(process.env.WALK_OWNER_TOKEN ?? "")}`;

async function measure(page, label) {
  const m = await page.evaluate(() => {
    const review = document.querySelector('[aria-label="Document review"]');
    if (!review) return { review: false };
    const r = review.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;
    const tools = [...review.querySelectorAll("a, button")].filter((b) => /Close|Open in tab/.test(b.textContent ?? ""));
    const toolsOut = tools.filter((b) => { const t = b.getBoundingClientRect(); return t.right > Math.min(r.right, vw) + 1 || t.left < r.left - 1; }).length;
    const aside = review.querySelector("aside");
    const asideShown = Boolean(aside && aside.getBoundingClientRect().width > 0 && getComputedStyle(aside).display !== "none");
    const reading = review.querySelector('[data-testid="doc-view"]')?.closest("div[class]")?.parentElement;
    const clippedInside = [...review.querySelectorAll("*")].some((el) => {
      const s = getComputedStyle(el);
      return /clip|hidden/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 200;
    });
    return {
      review: true, viewport: vw, left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width),
      pastViewport: r.right > vw + 1, toolsOutOfView: toolsOut, clippedInside, commentsAndIndexShown: asideShown,
      readerToggle: Boolean(review.querySelector('[data-testid="review-reader-toggle"]')),
      readingWidth: reading ? Math.round(reading.getBoundingClientRect().width) : null,
      pageHScroll: document.documentElement.scrollWidth > vw + 1,
    };
  });
  console.log(`${label}: ${JSON.stringify(m)}`);
  return m;
}

const browser = await chromium.launch();
try {
  for (const width of [1280, 1920]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const shot = async (name) => {
      await page.waitForTimeout(600);
      await page.screenshot({ path: path.join(out, `${mode}-${name}-${width}.png`) });
      console.log(`shot ${mode}-${name}-${width}.png`);
    };
    // the design in its own tab
    await page.goto(`${base}/ui/doc/${doc}?source=${epic}&${as}`);
    await page.locator('[aria-label="Document review"]').waitFor();
    const rail = await page.locator("[data-rail]").getAttribute("data-rail");
    console.log(`rail ${rail} at ${width}`);
    await measure(page, `tab ${width}`);
    await shot("tab");
    if (mode === "after") {
      await page.getByTestId("review-reader-toggle").click();
      await measure(page, `tab ${width} comments+index shown`);
      await shot("tab-panel");
      await page.getByTestId("review-reader-toggle").click();
      await measure(page, `tab ${width} reader again`);
    }
    // the pop-up from the epic page's Design link
    await page.goto(`${base}/ui/epic/${epic}?${as}`);
    await page.getByRole("button", { name: "Design", exact: true }).click();
    await page.locator('[aria-label="Document review"]').waitFor();
    await measure(page, `pop-up ${width}`);
    await shot("popup");
    if (mode === "after") {
      await page.getByTestId("review-reader-toggle").click();
      await measure(page, `pop-up ${width} comments+index shown`);
      await shot("popup-panel");
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}
