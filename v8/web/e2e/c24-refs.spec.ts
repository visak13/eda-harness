// C24 $-references in the board UI (s-5d1b171d57; owner m-0f727b0c57). On a throwaway board from THIS tree (never
// :9400): in the composer type '$C2' and pick a story, a doc and a decision with the keyboard; '$5' and '$env:X' open
// no picker; in a quote note type '$C2' and pick the decision. Send. On the board the text and the note carry $<id>
// tokens; on the page each renders as a chip that opens its target (ticket page, doc drawer, History drawer on
// Decisions). Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox. One at a time.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Locator, Page } from "@playwright/test";
import { ADMIN } from "./board";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "c24-refs", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "c24-refs", trace: "retain-on-failure", screenshot: "only-on-failure" });
test.describe.configure({ mode: "serial", timeout: 150_000 });

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const arch = { "X-Participant": "arch" };
const owner = { "X-Participant": "owner" };

const DOC = ["# C24 smoke design", "", "## Refs", "Dollar references point at board objects.", ""].join("\n");
let story = "", other = "", design = "", decision = "";

async function shot(page: Page, name: string): Promise<void> {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE, `${name}.png`) });
}

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
}

/** Arrow down the open $ list until `id` is the active row, then Enter. */
async function pick(page: Page, menu: Locator, id: string): Promise<void> {
  await expect(menu.locator(`[data-ref="${id}"]`)).toBeVisible();
  for (let i = 0; i < 12; i++) {
    if ((await menu.locator('[aria-selected="true"]').getAttribute("data-ref")) === id) { await page.keyboard.press("Enter"); return; }
    await page.keyboard.press("ArrowDown");
  }
  throw new Error(`${id} never became the active row`);
}

test.beforeAll(async () => {
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "C24 smoke story", parent_id: EPIC() }, owner)).id;
  other = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "C2 smoke target", parent_id: EPIC() }, owner)).id;
  design = (await call("POST", "/v1/docs", { doc_type: "design", title: "C2 smoke design", body_md: DOC, scope: EPIC() }, arch)).id;
  await call("POST", "/v1/links", { from_id: story, to_id: design, relation: "designed_by" }, arch);
  decision = (await call("POST", "/v1/decisions", { scope: story, text: "C2 smoke ruling: $ references board objects" }, arch)).id;
});

test("$ picks a story, a doc and a decision in the composer and a note; the text carries $<id>; chips open their targets", async ({ page }) => {
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
  const ta = page.getByTestId("composer-text");
  await ta.click();

  // 1. '$5' and '$env:X' open no picker.
  await page.keyboard.type("costs $5 and $env:X ");
  await page.waitForTimeout(400);
  await expect(page.getByTestId("refs-menu")).toHaveCount(0);
  await shot(page, "01-no-picker-for-dollar5-env");
  await ta.fill("");

  // 2. the composer: '$C2' → rows of this epic first (kind, id, title) → pick the story, the doc, the decision.
  await page.keyboard.type("see $C2");
  const menu = page.getByTestId("refs-menu");
  await expect(menu).toBeVisible();
  for (const id of [other, design, decision]) await expect(menu.locator(`[data-ref="${id}"]`)).toHaveAttribute("data-group", "scope");
  await expect(menu.locator(`[data-ref="${other}"]`)).toContainText(`story $${other}`);
  await expect(menu.locator(`[data-ref="${other}"]`)).toContainText("C2 smoke target");
  await shot(page, "02-composer-picker");
  await pick(page, menu, other);
  await expect(menu).toHaveCount(0);
  await page.keyboard.type("and $C2");
  await pick(page, menu, design);
  await page.keyboard.type("per $C2");
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape"); // closes the list, keeps the text
  await expect(menu).toHaveCount(0);
  await expect(ta).toHaveValue(/per \$C2$/);
  await page.keyboard.press("Backspace"); await page.keyboard.press("Backspace");
  await page.keyboard.type("C2");
  await expect(menu).toBeVisible();
  await pick(page, menu, decision);
  await expect(ta).toHaveValue(`see $${other} (C2 smoke target) and $${design} (C2 smoke design) per $${decision} (C2 smoke ruling: $ references board objects) `);

  // 3. a quote note: select a doc passage, Ctrl+Alt+Q, '$C2' in the note → pick the decision, the story, the doc → add.
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner&doc=${design}&v=1`);
  await expect(page.getByTestId("doc-body")).toContainText("Dollar references point at board objects.");
  await selectText(page, "[data-testid=doc-body]", "Dollar references point at board objects.");
  await page.keyboard.press("Control+Alt+KeyQ");
  const pop = page.getByTestId("quote-popover");
  await expect(pop.getByTestId("quote-note")).toBeFocused();
  await page.keyboard.type("ruled in $C2");
  const noteMenu = pop.getByTestId("note-refs-menu");
  await expect(noteMenu).toBeVisible();
  await shot(page, "03-note-picker");
  await pick(page, noteMenu, decision);
  await expect(pop).toBeVisible(); // Enter picked; it did not add the quote
  await page.keyboard.type("for $C2");
  await pick(page, noteMenu, other);
  await page.keyboard.type("see $C2");
  await pick(page, noteMenu, design);
  await expect(pop.getByTestId("quote-note")).toHaveValue(`ruled in $${decision} (C2 smoke ruling: $ references board objects) for $${other} (C2 smoke target) see $${design} (C2 smoke design) `);
  await page.keyboard.press("Enter");
  await expect(pop).toBeHidden();

  // 4. send (the draft text survived the navigation).
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
  await expect(page.getByTestId("quote-chip")).toHaveCount(1);
  await expect(ta).toHaveValue(new RegExp(`^see \\$${other} `));
  await ta.press("Control+Enter");
  await expect(page.getByTestId("sent-note")).toBeVisible();

  // 5. on the board: the text and the note carry the ids.
  const msgs = await call("GET", `/v1/messages?ticket_id=${story}`, undefined, owner);
  const sent = msgs.find((m: any) => (m.text as string).startsWith("see $"));
  for (const id of [other, design, decision]) expect(sent.text).toContain(`$${id} (`);
  for (const id of [other, design, decision]) expect(sent.quotes[0].note).toContain(`$${id} (`);

  // 6. the chips: three in the text, three in the quote card's note; each opens its target.
  const row = page.getByTestId("thread-message").filter({ hasText: "see" }).last();
  await row.scrollIntoViewIfNeeded();
  const chips = row.getByTestId("ref-chip");
  await expect(chips).toHaveCount(6);
  await expect(row.locator(`[data-ref="${other}"]`).first()).toHaveText("story · C2 smoke target");
  await shot(page, "04-chips");
  await row.locator(`[data-testid=message-md] [data-ref="${design}"], [data-ref="${design}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`doc=${design}`));
  await expect(page.getByTestId("doc-body")).toContainText("Dollar references point at board objects.");
  await shot(page, "05-doc-chip-opens-drawer");
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
  await page.getByTestId("thread-message").filter({ hasText: "see" }).last().getByTestId("quote-card").locator(`[data-ref="${decision}"]`).click();
  await expect(page).toHaveURL(/view=history&category=decisions/);
  await expect(page.getByText("C2 smoke ruling").first()).toBeVisible();
  await shot(page, "06-decision-chip-opens-history");
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
  await page.getByTestId("thread-message").filter({ hasText: "see" }).last().locator(`[data-ref="${other}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`/ui/ticket/${other}`));
  await shot(page, "07-story-chip-opens-ticket");
});
