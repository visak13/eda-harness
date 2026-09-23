// Design review fit: shots + overflow measures for scripts/reader_walk.py. Private board only.
//
//   node scripts/reader_walk.mjs before|after <board-base-url> <out-dir> <epic-id> <design-doc-id>
//
// t-feb26a46d9 added reader mode; t-cb431765fc (c-894f88bd1b) made the measure honest. For each viewport —
// CSS 1684x875 (the owner's 1852x962 window at 110% zoom), 1852x962 (the same window at 100%), 1280x800 and
// 1920x1080 — with the left rail expanded and collapsed: the design in its own tab (/ui/doc/<id>?source=<epic>)
// and in the pop-up (the epic page's Design link), each in reader mode and with the panel shown. Each shot logs
// whether the review is clipped or scrolls sideways anywhere: its right edge past the viewport, its header tools
// out of view, the page scrolling sideways, or ANY element inside [aria-label="Document review"] whose content is
// wider than its box (overflow-x auto|scroll|clip|hidden and scrollWidth > clientWidth+2). The last one is the
// check 54c0c4e's measure lacked: it only counted clip|hidden, so an inner horizontal scrollbar passed
// (qa m-6e36c0deaa, lesson les-3234de4bc7). Exits 1 when any `after` measure fails.
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
const VIEWPORTS = [[1684, 875], [1852, 962], [1280, 800], [1920, 1080]];
const failures = [];

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
    // Any box inside the review whose content is wider than it: a sideways scroller (auto|scroll) or a clip.
    const wide = [...review.querySelectorAll("*")].filter((el) => {
      const s = getComputedStyle(el);
      return /auto|scroll|clip|hidden/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0
        && s.textOverflow !== "ellipsis";
    }).map((el) => `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0] || "-"} ${el.clientWidth}<${el.scrollWidth} (${getComputedStyle(el).overflowX})`);
    return {
      review: true, viewport: vw, left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width),
      rail: document.querySelector("[data-rail]")?.getAttribute("data-rail") ?? null,
      pastViewport: r.right > vw + 1, toolsOutOfView: toolsOut, innerOverflow: wide, commentsAndIndexShown: asideShown,
      readingWidth: reading ? Math.round(reading.getBoundingClientRect().width) : null,
      pageHScroll: document.documentElement.scrollWidth > vw + 1,
    };
  });
  const ok = m.review && !m.pastViewport && !m.toolsOutOfView && !m.pageHScroll && m.innerOverflow.length === 0;
  console.log(`${ok ? "PASS" : "FAIL"} ${label}: ${JSON.stringify(m)}`);
  if (!ok) failures.push(label);
  return m;
}

async function setRail(page, want) {
  const now = await page.locator("[data-rail]").getAttribute("data-rail");
  if ((want === "collapsed") !== (now === "collapsed")) await page.getByTestId("rail-toggle").click();
  const after = await page.locator("[data-rail]").getAttribute("data-rail");
  if ((want === "collapsed") !== (after === "collapsed")) throw new Error(`rail stayed ${after}, wanted ${want}`);
}

const browser = await chromium.launch();
try {
  for (const [width, height] of VIEWPORTS) {
    for (const rail of ["full", "collapsed"]) {
      const tag = `${width}x${height}-rail-${rail}`;
      const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      const shot = async (name) => {
        await page.waitForTimeout(500);
        await page.screenshot({ path: path.join(out, `${mode}-${name}-${tag}.png`) });
        console.log(`shot ${mode}-${name}-${tag}.png`);
      };
      // the rail state is remembered per viewer, so set it once on the epic page
      await page.goto(`${base}/ui/epic/${epic}?${as}`);
      await page.locator("[data-rail]").waitFor();
      await setRail(page, rail);
      // the design in its own tab, reader mode then panel shown
      await page.goto(`${base}/ui/doc/${doc}?source=${epic}&${as}`);
      await page.locator('[aria-label="Document review"]').waitFor();
      await measure(page, `tab ${tag} reader`);
      await shot("tab");
      await page.getByTestId("review-reader-toggle").click();
      await measure(page, `tab ${tag} panel`);
      await shot("tab-panel");
      await page.getByTestId("review-reader-toggle").click();
      // the pop-up from the epic page's Design link
      await page.goto(`${base}/ui/epic/${epic}?${as}`);
      await page.getByRole("button", { name: "Design", exact: true }).click();
      await page.locator('[aria-label="Document review"]').waitFor();
      await measure(page, `pop-up ${tag} reader`);
      await shot("popup");
      await page.getByTestId("review-reader-toggle").click();
      await measure(page, `pop-up ${tag} panel`);
      await shot("popup-panel");
      await ctx.close();
    }
  }
} finally {
  await browser.close();
}
console.log(failures.length ? `${failures.length} FAIL: ${failures.join(" | ")}` : "ALL PASS");
if (mode === "after" && failures.length) process.exit(1);
