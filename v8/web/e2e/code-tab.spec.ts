import fs from "node:fs";
import path from "node:path";
import { expect, test } from "./fixtures";
import { REPO_DIR } from "./board";

// epic-91fcd3b370 S3 (c-8c3e157cc2, c-15095a23a0): the Code tab against the REAL code service.
//  - up: /ui/code embeds code-server full-bleed (rail collapsed, no page scrollbar) and the VS Code
//    workbench renders inside the frame; a deep link …&line=10-20 opens the file with the cursor on
//    line 10 and lines 10–20 on screen; the header's FAQ link opens guides/code-tab-faq.md.
// The down-state (a board whose EDP_CODE_PORT answers nothing) is code-tab-down.spec.ts: a worker
// option such as boardEnv is per FILE, so it needs its own board.
// Needs the code service up: `.\edp.ps1 start code` (it is by-name only).

const CODE_PORT = process.env.EDP_CODE_PORT ?? "9410";
const SHOTS = path.join(REPO_DIR, "web", "e2e", "evidence", "code-tab");
const as = "as=owner";

async function codeServiceUp(): Promise<boolean> {
  try {
    return (await fetch(`http://127.0.0.1:${CODE_PORT}/healthz`, { signal: AbortSignal.timeout(3000) })).ok;
  } catch {
    return false;
  }
}

test.use({ boardFile: "code-tab", boardEnv: { EDP_CODE_PORT: CODE_PORT } });

test.describe("code service up", () => {
  test.setTimeout(120_000);

  test.beforeAll(async () => {
    fs.mkdirSync(SHOTS, { recursive: true });
    // The spec board's EDP8_HOME is a temp dir: give it the real FAQ so the header link resolves.
    const home = process.env.EDP8_E2E_HOME!;
    fs.mkdirSync(path.join(home, "guides"), { recursive: true });
    fs.copyFileSync(path.join(REPO_DIR, "guides", "code-tab-faq.md"), path.join(home, "guides", "code-tab-faq.md"));
    expect(await codeServiceUp(), `code-server is not answering on :${CODE_PORT} — run .\\edp.ps1 start code`).toBe(true);
  });

  test("the workbench renders full-bleed with the rail collapsed and no page scrollbar", async ({ page }) => {
    await page.goto(`/ui/code?${as}&folder=${encodeURIComponent(REPO_DIR)}`, { waitUntil: "load" });
    const frameEl = page.getByTestId("code-frame");
    await expect(frameEl).toBeVisible();
    expect(await frameEl.getAttribute("src")).toMatch(new RegExp(`^http://127\\.0\\.0\\.1:${CODE_PORT}/\\?folder=/[a-z]:/`));
    await expect(page.locator("[data-rail]")).toHaveAttribute("data-rail", "collapsed");
    await expect(page.getByTestId("code-state")).toContainText("running");

    const wb = page.frameLocator('[data-testid="code-frame"]');
    await expect(wb.locator(".monaco-workbench")).toBeVisible({ timeout: 60_000 });
    await expect(wb.locator(".part.activitybar")).toBeVisible({ timeout: 30_000 });
    await expect(wb.locator(".part.statusbar")).toBeVisible();

    const geo = await page.evaluate(() => {
      const f = document.querySelector('[data-testid="code-frame"]')!.getBoundingClientRect();
      const rail = document.querySelector("#workspace-navigation")!.getBoundingClientRect();
      const se = document.scrollingElement!;
      return {
        vw: window.innerWidth, vh: window.innerHeight, frame: { left: f.left, right: f.right, top: f.top, bottom: f.bottom },
        railRight: rail.right, scrollH: se.scrollHeight, clientH: se.clientHeight, scrollW: se.scrollWidth, clientW: se.clientWidth,
      };
    });
    // no page scrollbar: the document is exactly one viewport, both ways
    expect(geo.scrollH).toBeLessThanOrEqual(geo.clientH);
    expect(geo.scrollW).toBeLessThanOrEqual(geo.clientW);
    // full-bleed: the frame runs from the collapsed rail to the right edge and down to the bottom
    expect(geo.railRight).toBeLessThanOrEqual(66);
    expect(Math.abs(geo.frame.left - geo.railRight)).toBeLessThanOrEqual(2);
    expect(Math.abs(geo.frame.right - geo.vw)).toBeLessThanOrEqual(1);
    expect(Math.abs(geo.frame.bottom - geo.vh)).toBeLessThanOrEqual(1);
    expect(geo.frame.top).toBeLessThanOrEqual(48); // only the thin header strip above it
    await page.screenshot({ path: path.join(SHOTS, "code-tab-up.png") });
  });

  test("a deep link …&line=10-20 opens the file with the cursor on line 10 and lines 10–20 in view", async ({ page }) => {
    const q = new URLSearchParams({ folder: REPO_DIR, file: "src/edp8/run_state.py", line: "10-20" });
    await page.goto(`/ui/code?${as}&${q.toString()}`, { waitUntil: "load" });
    await expect(page.getByTestId("code-where")).toHaveText("src/edp8/run_state.py L10–20");
    const wb = page.frameLocator('[data-testid="code-frame"]');
    await expect(wb.locator(".tab.active")).toContainText("run_state.py", { timeout: 60_000 });
    await expect(wb.locator(".part.statusbar")).toContainText("Ln 10, Col 1", { timeout: 30_000 });
    const numbers = (await wb.locator(".monaco-editor .line-numbers").allTextContents()).map((n) => Number(n.trim()));
    for (let n = 10; n <= 20; n++) expect(numbers, `line ${n} is on screen`).toContain(n);
    await page.screenshot({ path: path.join(SHOTS, "code-tab-deeplink.png") });
  });

  test("the header strip links the FAQ, which opens in its own tab", async ({ page, context }) => {
    await page.goto(`/ui/code?${as}`, { waitUntil: "load" });
    const faq = page.getByTestId("code-faq");
    await expect(faq).toHaveAttribute("href", "/ui/code/faq");
    await expect(faq).toHaveAttribute("target", "_blank");
    const [tab] = await Promise.all([context.waitForEvent("page"), faq.click()]);
    await tab.waitForLoadState("load");
    await expect(tab.getByRole("heading", { level: 1, name: "Code tab FAQ" })).toBeVisible();
    for (const topic of ["The shared tree and live seats", "Git worktree: your own copy", "Why there is no Pylance or C/C++ (cpptools)", "How tagging works", "The built-in git UI is not guarded"]) {
      await expect(tab.getByRole("heading", { name: topic })).toBeVisible();
    }
    await tab.screenshot({ path: path.join(SHOTS, "code-tab-faq.png"), fullPage: true });
  });
});
