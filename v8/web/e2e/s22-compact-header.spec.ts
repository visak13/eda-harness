import fs from "node:fs";
import { test, expect, BASE, type Locator } from "./fixtures";

// t-899d295194 (owner m-9238e165cf, screenshots art-f97f8259fa / art-bbb22f6a23):
// (1) c-411c097bb8 — the design modal and its Open-in-tab page: ONE compact header row (single-line
//     title with ellipsis, version picker, Open in tab, Close) of at most 64 px; the modal spans the
//     viewport height minus a small margin, so at 1440×900 the doc column shows ≥ 600 px of content.
// (2) c-1bf26dd44e — the epic page: "Needs attention" is a compact chip IN the status row (next to
//     Architect); the separate NEEDS ATTENTION row is gone.
test.use({ boardFile: "s22-compact-header" });
const SHOTS = "e2e/evidence/s22";

async function call(method: string, p: string, data: unknown, actor: string) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", "X-Participant": actor }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${p} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

// The owner's real title: long enough to wrap to two lines in the old header.
const TITLE = "Conversation-first board: contextual review, retro character and Usage widget — proposed v7";
const BODY = ["# Conversation-first board redesign — proposed contract v7", "",
  ...Array.from({ length: 12 }, (_, i) => [`## ${i + 1}. Section ${i + 1}`, "", "Body text of the section. ".repeat(20), ""]).flat()].join("\n");

let seeded: { epic: string; doc: string } | null = null;
test.beforeAll(async () => {
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Board UI improvements" }, "owner")).id as string;
  const doc = (await call("POST", "/v1/docs", { doc_type: "design", title: TITLE, scope: epic, body_md: BODY }, "arch")).id as string;
  for (const n of [2, 3]) await call("PATCH", `/v1/docs/${doc}`, { body_md: BODY.replace("v7", `v7 (${n})`) }, "arch");
  await call("POST", "/v1/links", { from_id: epic, to_id: doc, relation: "designed_by" }, "arch");
  await call("PATCH", `/v1/tickets/${epic}`, { design_ref: doc, assignee: "arch" }, "arch");
  // Two open asks from a live-by-default seat → the attention chip has a count.
  for (const q of ["Which theme?", "Ship the outline?"]) await call("POST", "/v1/messages", { ticket_id: epic, kind: "question", to: "owner", text: q }, "arch");
  seeded = { epic, doc };
});

async function header(scope: Locator) {
  const review = scope.getByRole("region", { name: "Document review" }).or(scope.locator('section[aria-label="Document review"]')).first();
  const head = review.locator(":scope > div").first();
  return { review, head };
}

async function checkHeader(scope: Locator, max = 64) {
  const { head } = await header(scope);
  const hb = (await head.boundingBox())!;
  expect(hb.height, "header height").toBeLessThanOrEqual(max);
  const title = scope.getByTestId("review-title");
  await expect(title).toHaveAttribute("title", TITLE);
  const one = await title.evaluate((el) => ({ h: el.getBoundingClientRect().height, lh: parseFloat(getComputedStyle(el).lineHeight), clipped: el.scrollWidth > el.clientWidth, ws: getComputedStyle(el).whiteSpace, to: getComputedStyle(el).textOverflow }));
  expect(one.h, "title is one line").toBeLessThanOrEqual(one.lh + 2);
  expect(one.ws).toBe("nowrap");
  expect(one.to).toBe("ellipsis");
  // Version picker, Open in tab (viewer only) and Close sit inside the header band.
  for (const l of [scope.getByTestId("version-now"), scope.getByRole("button", { name: "Close" }), scope.getByRole("link", { name: /Open in tab/ })]) {
    if (!(await l.count())) continue;
    const b = (await l.first().boundingBox())!;
    expect(b.y).toBeGreaterThanOrEqual(hb.y - 1);
    expect(b.y + b.height).toBeLessThanOrEqual(hb.y + hb.height + 1);
  }
  return hb;
}

test("1440×900 design modal: one ≤64 px header row, full-height modal, ≥600 px of document", async ({ page }) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  const dialog = page.getByRole("dialog").filter({ hasText: "Section 1" });
  await expect(dialog.getByTestId("review-title")).toBeVisible();
  const hb = await checkHeader(dialog);
  expect(hb.height).toBeLessThanOrEqual(64);
  const db = (await dialog.boundingBox())!;
  expect(db.height, "modal = viewport minus a small margin").toBeGreaterThanOrEqual(900 - 32);
  const col = await dialog.getByTestId("doc-view").evaluate((el) => {
    const scroller = el.closest("div[class*='reading']") as HTMLElement;
    return scroller.getBoundingClientRect().height;
  });
  expect(col, "doc column visible height").toBeGreaterThanOrEqual(600);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/compact-header-1440-modal.png` });
});

test("844×390 design modal: header stays compact", async ({ page }) => {
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  const dialog = page.getByRole("dialog").filter({ hasText: "Section 1" });
  await expect(dialog.getByTestId("review-title")).toBeVisible();
  await checkHeader(dialog, 96); // narrow: the row wraps once (title row, then version/actions)
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/compact-header-844-modal.png` });
});

test("Open-in-tab page carries the same compact header", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  const dialog = page.getByRole("dialog").filter({ hasText: "Section 1" });
  const [tab] = await Promise.all([context.waitForEvent("page"), dialog.getByRole("link", { name: /Open in tab/ }).click()]);
  await tab.setViewportSize({ width: 1440, height: 900 });
  await expect(tab.getByTestId("review-title")).toBeVisible();
  await checkHeader(tab.locator("body"));
  await tab.screenshot({ path: `${SHOTS}/compact-header-1440-open-in-tab.png` });
  await tab.setViewportSize({ width: 844, height: 390 });
  await checkHeader(tab.locator("body"), 96);
  await tab.screenshot({ path: `${SHOTS}/compact-header-844-open-in-tab.png` });
});

for (const [w, h] of [[1440, 900], [844, 390]] as const) {
  test(`${w}: Needs attention is a chip in the status row, no row of its own`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
    const meta = page.getByTestId("work-metadata");
    await page.getByTestId("work-status").waitFor({ state: "attached" });
    await page.waitForTimeout(300);
    const toggle = page.getByTestId("work-context-toggle");
    if (!(await meta.isVisible()) && (await toggle.isVisible())) await toggle.click(); // phone: details collapsed
    await expect(meta).toBeVisible();
    const chip = page.getByTestId("work-attention");
    await expect(chip).toContainText("2 unanswered requests");
    const box = async (id: string) => (await page.getByTestId(id).boundingBox())!;
    const status = await box("work-status");
    const att = await box("work-attention");
    const arch = await box("work-assigned");
    if (w === 1440) {
      expect(Math.abs(att.y - status.y), "same row as Status").toBeLessThanOrEqual(4);
      expect(att.x).toBeGreaterThan(arch.x); // after Owner/Assigned(/Architect)
    }
    expect(att.height, "compact chip, not a 90 px card").toBeLessThanOrEqual(40);
    await page.screenshot({ path: `${SHOTS}/attention-chip-${w}.png` });
  });
}
