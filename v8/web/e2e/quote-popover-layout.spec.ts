// s-aa76c83998 (owner m-9834482f32, architect m-e4d66cbb38): the selection popover is two rows — the note input, then an
// actions row (Mark as requirement secondary, Quote primary) — at a desktop width and at a phone width, on a message
// and on a doc. Throwaway board from THIS tree (never :9400). Screenshots go to e2e/evidence/quote-popover/.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { ADMIN } from "./board";
import { BASE, EPIC, expect, test } from "./fixtures";

const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "quote-popover");
test.use({ boardFile: "quote-popover", trace: "retain-on-failure" });
test.describe.configure({ mode: "serial", timeout: 120_000 });

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const arch = { "X-Participant": "arch" };
const owner = { "X-Participant": "owner" };
const MSG = "The plan is ready: ship the popover fix right after the layout review lands.";
let story = "", design = "", msg = "";

test.beforeAll(async () => {
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Popover story", parent_id: EPIC() }, owner)).id;
  design = (await call("POST", "/v1/docs", { doc_type: "design", title: "Popover design", body_md: "# Popover\n\n## Rules\nThe popover has a note row and an actions row.", scope: EPIC() }, arch)).id;
  await call("POST", "/v1/links", { from_id: story, to_id: design, relation: "designed_by" }, arch);
  msg = (await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: MSG }, arch)).id;
});

async function selectText(page: Page, scope: string, text: string): Promise<void> {
  const ok = await page.evaluate(({ scope, text }) => {
    const root = document.querySelector(scope);
    if (!root) return false;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const at = (n as Text).data.indexOf(text);
      if (at < 0) continue;
      const range = document.createRange();
      range.setStart(n, at); range.setEnd(n, at + text.length);
      const sel = window.getSelection()!;
      sel.removeAllRanges(); sel.addRange(range);
      return true;
    }
    return false;
  }, { scope, text });
  expect(ok, `"${text}" is on screen in ${scope}`).toBe(true);
  await page.evaluate(() => document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true })));
}

async function checkAndShoot(page: Page, name: string, withMark: boolean): Promise<void> {
  const pop = page.getByTestId("quote-popover");
  await expect(pop).toBeVisible();
  const box = (await pop.boundingBox())!;
  const vp = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
  expect(box.width).toBeLessThanOrEqual(340.5);
  const note = (await pop.getByTestId("quote-note").boundingBox())!;
  const quote = (await pop.getByTestId("quote-add").boundingBox())!;
  expect(note.width).toBeGreaterThan(box.width - 24); // row 1 is the note, full width
  expect(quote.y).toBeGreaterThan(note.y + note.height - 1); // row 2 is below it
  expect(Math.abs(quote.x + quote.width - (box.x + box.width - 9))).toBeLessThan(4); // right-aligned
  if (withMark) {
    const mark = (await pop.getByTestId("quote-popover-mark").boundingBox())!;
    expect(Math.abs(mark.y - quote.y)).toBeLessThan(1); // one row
    expect(mark.height).toBeCloseTo(quote.height, 0);
    expect(mark.x + mark.width).toBeLessThanOrEqual(quote.x); // Mark first, Quote last
  }
  // nothing paints over the popover: the four corners (inset past the 8px radius), the centre, and a point every 8px along its top
  // and bottom edges (the sticky composer's collapse chevron once sat on the top edge)
  const hits = await page.evaluate(({ x, y, w, h }) => {
    const pop = document.querySelector("[data-testid=quote-popover]")!;
    const pts: number[][] = [[x + 10, y + 10], [x + w - 10, y + 10], [x + 10, y + h - 10], [x + w - 10, y + h - 10], [x + w / 2, y + h / 2]];
    for (let px = x + 10; px <= x + w - 10; px += 8) pts.push([px, y + 0.5], [px, y + h - 0.5]);
    return pts.filter(([px, py]) => { const el = document.elementFromPoint(px, py); return !el || !pop.contains(el); });
  }, { x: box.x, y: box.y, w: box.width, h: box.height });
  expect(hits, "points of the popover covered by something else").toEqual([]);
  // the sticky composer's collapse toggle sits on the edge the popover often lands on (qa saw it at y 518 on a phone, with the
  // popover top at 526): while the popover is open it is hidden (visibility, so nothing reflows), wherever it falls
  const toggleVisibility = await page.getByTestId("composer-collapse").evaluate((el) => getComputedStyle(el).visibility);
  expect(toggleVisibility, "the composer's collapse toggle is hidden while the popover is open").toBe("hidden");
  // never over the selected text
  const sel = await page.evaluate(() => { const r = window.getSelection()!.getRangeAt(0).getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; });
  expect(box.y >= sel.bottom - 1 || box.y + box.height <= sel.top + 1, "popover does not cover the selection").toBe(true);
  await expect(pop.getByTestId("quote-note")).toHaveAttribute("placeholder", "Add a note (optional) — @ to notify");
  fs.mkdirSync(EVIDENCE, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE, `${name}.png`) });
}

for (const [label, size] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`popover on a message and on a doc at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    // a phone starts with the composer on its one-line bar; open it, as the owner had, so the toggle that once met the popover is there
    await page.addInitScript(() => { try { localStorage.setItem("edp8.ui.owner.composer-collapsed", "0"); } catch { /* storage blocked */ } });
    await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
    await expect(page.getByTestId("thread")).toBeVisible();
    await selectText(page, `li[id="${msg}"]`, "ship the popover fix");
    await checkAndShoot(page, `message-${label}`, true);
    await page.keyboard.press("Escape");
    await page.goto(`${BASE()}/ui/ticket/${story}?as=owner&doc=${design}&v=1`);
    await expect(page.getByTestId("doc-body")).toContainText("actions row");
    await selectText(page, "[data-testid=doc-body]", "note row and an actions row");
    await checkAndShoot(page, `doc-${label}`, false);
  });
}
