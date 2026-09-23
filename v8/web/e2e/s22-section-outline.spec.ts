import fs from "node:fs";
import path from "node:path";
import { PNG } from "pngjs";
import { test, expect, BASE, type Page } from "./fixtures";
import { REPO_DIR } from "./board";

// S22 (s-8ebd40da22) c-95d5c22dda — owner m-94117833e0: "we lost the easy to navigate menu from old".
// The section outline (heading jump list) is back inside the v3 design viewer and on its Open-in-tab
// page: wide — a block in the right panel under the review guidance (revision3-clean-review.png);
// narrow (844) — a sticky, collapsed bar at the top of the document column. Collapsible (<details>),
// keyboard-reachable (summary + one button per heading), a jump scrolls to the heading and focuses it.
test.use({ boardFile: "s22-outline" });
const SHOTS = "e2e/evidence/s22";
const REFERENCE = path.join(REPO_DIR, "docs", "ui-redesign-concepts", "revision3-clean-review.png");

async function call(method: string, p: string, data: unknown, actor: string) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", "X-Participant": actor }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${p} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

const para = "The epic is your everyday working surface. Documents open when you need them; they do not replace the conversation. ".repeat(3);
const BODY = [
  "# Keep the work and conversation together", "", para, "",
  "## 1. Owner words and scope", "", para, "",
  "## 2. Review the version you can see", "", para, "",
  "## 3. Feedback stays here while you write", "", para, "",
  "## 4. Surfaces", "", para, "",
  ...Array.from({ length: 11 }, (_, i) => [`### 4.${i + 1} Surface ${i + 1}`, "", para, ""]).flat(),
  "## 5. Open in tab is optional", "", para,
].join("\n");
const HEADINGS = 1 + 4 + 11 + 1; // h1 + 1.–4. + 4.1–4.11 + 5.

let seeded: { epic: string; doc: string } | null = null;
test.beforeAll(async () => {
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Board improvements" }, "owner")).id as string;
  const doc = (await call("POST", "/v1/docs", { doc_type: "design", title: "Conversation-first workflow", scope: epic, body_md: BODY }, "arch")).id as string;
  await call("POST", "/v1/links", { from_id: epic, to_id: doc, relation: "designed_by" }, "arch");
  await call("PATCH", `/v1/tickets/${epic}`, { design_ref: doc }, "arch");
  await call("POST", `/v1/gates/${epic}/design_signoff/open`, { note: "please review" }, "arch");
  seeded = { epic, doc };
});

/** Reference render (left) | this build (right), top-aligned, for the qa composite read. */
function composite(actualPath: string, out: string) {
  const ref = PNG.sync.read(fs.readFileSync(REFERENCE));
  const act = PNG.sync.read(fs.readFileSync(actualPath));
  const gap = 16;
  const img = new PNG({ width: ref.width + gap + act.width, height: Math.max(ref.height, act.height) });
  img.data.fill(255);
  PNG.bitblt(ref, img, 0, 0, ref.width, ref.height, 0, 0);
  PNG.bitblt(act, img, 0, 0, act.width, act.height, ref.width + gap, 0);
  fs.writeFileSync(out, PNG.sync.write(img));
}

const viewer = (page: Page) => page.getByRole("dialog").filter({ hasText: "Conversation-first workflow" });
const inViewport = (page: Page, name: string) => page.getByRole("heading", { name }).evaluate((el) => {
  const r = el.getBoundingClientRect();
  return r.top >= 0 && r.top < window.innerHeight;
});

test("1440: outline under the review guidance — jump, keyboard, collapse; composite vs render", async ({ page }) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  const dialog = viewer(page);
  const outline = dialog.getByTestId("review-outline-side");
  await expect(outline).toBeVisible();
  await expect(dialog.getByTestId("review-outline-inline")).toBeHidden();
  // Placed in the right panel, below "Your review" guidance.
  const panel = dialog.getByRole("complementary", { name: "Your review" });
  await expect(panel.getByTestId("review-outline-side")).toBeVisible();
  const guidance = await panel.getByRole("heading", { name: "Your review" }).boundingBox();
  const box = await outline.boundingBox();
  expect(box!.y).toBeGreaterThan(guidance!.y);
  const entries = outline.getByRole("button");
  await expect(entries).toHaveCount(HEADINGS);
  await expect(entries.nth(0)).toHaveText("Keep the work and conversation together");
  await expect(outline.getByRole("button", { name: "4.7 Surface 7" })).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/outline-1440-viewer.png` });
  composite(`${SHOTS}/outline-1440-viewer.png`, `${SHOTS}/composite-1440-outline-vs-revision3.png`);

  // Mouse jump: the heading scrolls into view and takes focus.
  expect(await inViewport(page, "4.9 Surface 9")).toBe(false);
  await outline.getByRole("button", { name: "4.9 Surface 9" }).click();
  await expect.poll(() => inViewport(page, "4.9 Surface 9")).toBe(true);
  await expect(page.getByRole("heading", { name: "4.9 Surface 9" })).toBeFocused();

  // Keyboard: focus the first entry, Tab to the next, Enter jumps.
  await outline.getByRole("button", { name: "1. Owner words and scope" }).focus();
  await page.keyboard.press("Tab");
  await expect(outline.getByRole("button", { name: "2. Review the version you can see" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "2. Review the version you can see" })).toBeFocused();
  await expect.poll(() => inViewport(page, "2. Review the version you can see")).toBe(true);

  // Collapsible from the keyboard: the summary toggles the list.
  const summary = outline.locator("summary");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(entries.first()).toBeHidden();
  await page.keyboard.press("Enter");
  await expect(entries.first()).toBeVisible();

  // Still there with the feedback box open (Request changes).
  await dialog.getByRole("button", { name: "Request changes", exact: true }).click();
  await expect(dialog.getByTestId("review-outline-side")).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/outline-1440-request-changes.png` });
});

test("844x390: sticky collapsed outline bar in the document column", async ({ page }) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  const dialog = viewer(page);
  const bar = dialog.getByTestId("review-outline-inline");
  await expect(bar).toBeVisible();
  await expect(dialog.getByTestId("review-outline-side")).toBeHidden();
  await expect(bar.getByRole("button").first()).toBeHidden(); // collapsed by default
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/outline-844-collapsed.png` });
  await bar.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(bar.getByRole("button", { name: "4.11 Surface 11" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/outline-844-open.png` });
  composite(`${SHOTS}/outline-844-open.png`, `${SHOTS}/composite-844-outline-vs-revision3.png`);
  await bar.getByRole("button", { name: "4.11 Surface 11" }).click();
  await expect(page.getByRole("heading", { name: "4.11 Surface 11" })).toBeFocused();
  await expect.poll(() => inViewport(page, "4.11 Surface 11")).toBe(true);
  await expect(bar.getByRole("button").first()).toBeHidden(); // closes after the jump
  // Sticky: the bar is still on screen after scrolling deep into the document.
  const barBox = await bar.boundingBox();
  expect(barBox!.y).toBeGreaterThanOrEqual(0);
  expect(barBox!.y).toBeLessThan(390);
  await page.screenshot({ path: `${SHOTS}/outline-844-after-jump.png` });
});

test("the Open-in-tab page carries the same outline", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  const [tab] = await Promise.all([context.waitForEvent("page"), viewer(page).getByRole("link", { name: /Open in tab/ }).click()]);
  await tab.setViewportSize({ width: 1440, height: 900 });
  const outline = tab.getByTestId("review-outline-side");
  await expect(outline).toBeVisible();
  await expect(outline.getByRole("button")).toHaveCount(HEADINGS);
  await outline.getByRole("button", { name: "5. Open in tab is optional" }).click();
  await expect(tab.getByRole("heading", { name: "5. Open in tab is optional" })).toBeFocused();
  await expect.poll(() => inViewport(tab, "5. Open in tab is optional")).toBe(true);
  await tab.screenshot({ path: `${SHOTS}/outline-1440-open-in-tab.png` });
});
