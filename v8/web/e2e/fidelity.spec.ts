import { expect, test, type Locator, type Page, BASE } from "./fixtures";
import { readFileSync } from "node:fs";
import { GEOMETRY } from "./geometry";
import { bandDiffRatio, expectPx, readPng } from "./fidelity-helpers";
import { seedEpic, type G3aFixture } from "./g3a.seed";
import { seedDecisions } from "./g2.seed";

test.use({ boardFile: "fidelity" }); // one fresh board per spec file (fixtures.ts)

// Criterion c-fee415dda3: at 1440×900 the shell geometry, tokens, type and focus ring
// match the Folio plate (design §4.2, board-concepts-r2/source/design.css `.folio`).

// Folio (default theme) token colours as the browser reports them.
const RAIL = "rgb(238, 229, 216)"; // #EEE5D8
const PANEL = "rgb(255, 253, 248)"; // #FFFDF8
const ACCENTINK = "rgb(135, 63, 56)"; // #873F38

const style = (loc: Locator, prop: string) =>
  loc.evaluate((el, p) => getComputedStyle(el).getPropertyValue(p), prop);

// Reference plates (full-page 1440×900 win32 renders), decoded once.
const plate = (name: string) =>
  readPng(readFileSync(new URL(`./design-reference/${name}`, import.meta.url)));

test.describe("shell fidelity @ 1440×900", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("sidebar / header / main geometry, rail token, active nav, h1, focus ring", async ({ page }) => {
    await page.goto(`${BASE()}/ui/me?as=owner`);

    // Sidebar: x=0, width 216, background = the rail token.
    const sidebar = page.getByRole("complementary", { name: "Primary" }); // the Status rail is a second <aside>
    const sb = (await sidebar.boundingBox())!;
    expectPx(sb.x, GEOMETRY.sidebar.x, "sidebar x");
    expectPx(sb.width, GEOMETRY.sidebar.w, "sidebar width");
    expect(await style(sidebar, "background-color")).toBe(RAIL);

    // Header: height 72, starting at x=216.
    const header = page.getByTestId("app-header");
    const hb = (await header.boundingBox())!;
    expectPx(hb.x, GEOMETRY.header.x, "header x");
    expectPx(hb.height, GEOMETRY.header.h, "header height");

    // Main: x=256, width 1144.
    const main = page.locator("main");
    const mb = (await main.boundingBox())!;
    expectPx(mb.x, GEOMETRY.main.x, "main x");
    expectPx(mb.width, GEOMETRY.main.w, "main width");

    // Active nav row (Decisions on /me): 43px tall, on the panel colour, icon in accentink.
    const active = page.locator("a[aria-current='page']");
    const ab = (await active.boundingBox())!;
    expectPx(ab.height, 43, "active nav row height");
    expect(await style(active, "background-color")).toBe(PANEL);
    expect(await style(active.locator("[data-nav-icon] svg"), "color")).toBe(ACCENTINK);

    // Page h1: Georgia 38px.
    const h1 = page.locator("main h1");
    expect(await style(h1, "font-family")).toContain(GEOMETRY.type.h1.family);
    expect(await style(h1, "font-size")).toBe(`${GEOMETRY.type.h1.px}px`);

    // Focus ring on a nav link: 2px accentink, offset 3px. Keyboard focus so :focus-visible
    // engages (the first Tab lands on the Decisions link, first focusable in the DOM).
    await page.keyboard.press("Tab");
    const ring = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const s = getComputedStyle(el);
      return {
        text: el.textContent ?? "",
        width: s.outlineWidth,
        color: s.outlineColor,
        offset: s.outlineOffset,
      };
    });
    expect(ring.text).toContain("Decisions");
    expect(ring.width).toBe(`${GEOMETRY.focus.width}px`);
    expect(ring.offset).toBe(`${GEOMETRY.focus.offset}px`);
    expect(ring.color).toBe(ACCENTINK);
  });
});

// --- Band pixelmatch (image diff) — criterion c-80b50710a6 ------------------------------------
// The rail + header chrome bands are the fixed target; the content area (seeded rows/copy) will
// never pixel-match a live board, so it is logged, never asserted (see tests/fidelity/README.md:
// per-pixel threshold 0.1, band ratio ≤ 5%, content logged-only). Plates are win32 renders, so the
// whole block is skipped off win32 to match the visual-baseline policy.
test.describe("shell fidelity — band pixelmatch @ 1440×900", () => {
  test.use({ viewport: { width: 1440, height: 900 } });
  test.skip(process.platform !== "win32", "reference plates are win32 renders (visual-baseline policy)");

  let fx: G3aFixture;
  test.beforeAll(async () => {
    fx = await seedEpic();
  });

  const RAIL_BAND = GEOMETRY.bands.rail;
  const HEADER_BAND = GEOMETRY.bands.header;
  // Content area: right of the rail, below the header (logged, never asserted).
  const CONTENT_BAND = {
    x: GEOMETRY.header.x,
    y: GEOMETRY.header.h,
    w: 1440 - GEOMETRY.header.x,
    h: 900 - GEOMETRY.header.h,
  };

  // The header carries the theme picker the owner ruled into it (human defect #2, 2026-09-10 —
  // the plates predate that ruling and show none). Its rectangle is painted over with the plate's
  // own pixels before the header band is compared, so the ruled control is neither a false diff
  // nor a hiding place for anything else: only the picker's box is excluded, nothing around it.
  async function maskRuledControls(page: Page, shot: ReturnType<typeof readPng>, ref: ReturnType<typeof readPng>) {
    const picker = page.getByTestId("theme-picker-compact");
    if ((await picker.count()) === 0) return;
    const b = await picker.boundingBox();
    if (!b) return;
    const x0 = Math.max(0, Math.floor(b.x) - 4);
    const y0 = Math.max(0, Math.floor(b.y) - 4);
    const x1 = Math.min(shot.width, Math.ceil(b.x + b.width) + 4);
    const y1 = Math.min(shot.height, Math.ceil(b.y + b.height) + 4);
    for (let y = y0; y < y1; y++) {
      const s = (y * shot.width + x0) * 4;
      const r = (y * ref.width + x0) * 4;
      ref.data.copy(shot.data, s, r, r + (x1 - x0) * 4);
    }
    console.log(`[fidelity] header band excludes the ruled theme picker at ${x0},${y0}-${x1},${y1}`);
  }

  async function bandCheck(page: Page, url: string, plateName: string, label: string) {
    await page.goto(url);
    await expect(page.locator("main h1")).toBeVisible();
    const shot = readPng(await page.screenshot());
    const ref = plate(plateName);
    await maskRuledControls(page, shot, ref);

    const rail = bandDiffRatio(shot, ref, RAIL_BAND);
    const header = bandDiffRatio(shot, ref, HEADER_BAND);
    const content = bandDiffRatio(shot, ref, CONTENT_BAND);
    console.log(
      `[fidelity ${label}] rail band diff=${(rail * 100).toFixed(2)}% header band diff=${(header * 100).toFixed(2)}% content diff=${(content * 100).toFixed(2)}% (content logged-only)`,
    );
    expect(rail, `${label} rail band`).toBeLessThanOrEqual(0.05);
    expect(header, `${label} header band`).toBeLessThanOrEqual(0.05);
  }

  test("home rail + header bands match folio-home.png", async ({ page }) => {
    await bandCheck(page, `${BASE()}/ui/me?as=owner`, "folio-home.png", "home");
  });

  // The rail + header are the outer shell chrome — identical bands on the epic page — so the epic
  // plate's chrome is a real, asserting check too.
  test("epic rail + header bands match folio-epic.png", async ({ page }) => {
    await bandCheck(page, `${BASE()}/ui/epic/${fx.epic}?as=owner`, "folio-epic.png", "epic");
  });

  // Ruling-drawer band vs folio-ruling.png (finding 2, second-opinion 2026-09-08 — implemented, not
  // deferred). The drawer opens from a pending owner sign-off's "Review evidence" (design §17). With
  // the drawer open the shell chrome behind it is dimmed by the scrim — a deterministic, content-free
  // target (g2-fidelity asserts the sidebar/queue stay visible behind the dim), so the rail + header
  // bands are asserted against the ruling plate exactly as home/epic are; the drawer body is seed-
  // dependent, so its band is logged-only.
  const DRAWER_BAND = {
    x: GEOMETRY.drawer.rightEdge - GEOMETRY.drawer.w, // 1420 - 1112 = 308
    y: GEOMETRY.drawer.top, // 20
    w: GEOMETRY.drawer.w, // 1112
    h: 900 - GEOMETRY.drawer.top * 2, // 860
  };

  test("ruling drawer rail + header bands match folio-ruling.png (drawer body logged-only)", async ({ page }) => {
    await seedDecisions(); // a pending owner sign-off → "Review evidence" opens the ruling drawer
    await page.goto(`${BASE()}/ui/me?as=owner`);
    await page.getByTestId("review-evidence").click();
    await expect(page.getByTestId("drawer-panel")).toBeVisible();

    const shot = readPng(await page.screenshot());
    const ref = plate("folio-ruling.png");
    await maskRuledControls(page, shot, ref);
    const rail = bandDiffRatio(shot, ref, RAIL_BAND);
    const header = bandDiffRatio(shot, ref, HEADER_BAND);
    const drawer = bandDiffRatio(shot, ref, DRAWER_BAND);
    console.log(
      `[fidelity ruling] rail band diff=${(rail * 100).toFixed(2)}% header band diff=${(header * 100).toFixed(2)}% drawer diff=${(drawer * 100).toFixed(2)}% (drawer logged-only)`,
    );
    expect(rail, "ruling rail band").toBeLessThanOrEqual(0.05);
    expect(header, "ruling header band").toBeLessThanOrEqual(0.05);
  });
});
