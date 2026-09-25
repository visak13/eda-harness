// C23 quote notes take @mentions (s-93ddb7fd1a; owner m-5a9111ce12; ruling m-ef7cdf6dec: # stays text in the board UI).
// On a throwaway board from THIS tree (never :9400): quote a doc passage, type '@vi' in the popover's note and
// pick vishal from the picker with the keyboard, type a '#tag', add a second quote whose chip note gets '@tok' +
// Tab. Send a message whose TEXT names nobody. On the board: the message_sent event's mentions list vishal and
// tokuser, vishal's own wake feed carries it as a mention, and the quote cards show the notes.
// Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox. One at a time.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { ADMIN } from "./board";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "c23-note-mentions", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "c23-note-mentions", trace: "retain-on-failure", screenshot: "only-on-failure" });
test.describe.configure({ mode: "serial", timeout: 120_000 });

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const arch = { "X-Participant": "arch" };
const owner = { "X-Participant": "owner" };
const vishal = { "X-Participant": "vishal" };

const DOC = ["# C23 design", "", "## Notes", "A quote note can notify people.", "", "## Tags", "Hash tags stay as text on the board."].join("\n");
let story = "", design = "";

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

async function shot(page: Page, name: string): Promise<void> {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE, `${name}.png`) });
}

test.beforeAll(async () => {
  await call("POST", "/v1/participants", { type: "human", role: "owner", handle: "vishal", id: "vishal" }).catch(() => undefined);
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "C23 note mentions", parent_id: EPIC() }, owner)).id;
  design = (await call("POST", "/v1/docs", { doc_type: "design", title: "C23 design", body_md: DOC, scope: EPIC() }, arch)).id;
  await call("POST", "/v1/links", { from_id: story, to_id: design, relation: "designed_by" }, arch);
});

test("a note's @ picker inserts a handle; a note-only mention wakes that person; # stays text", async ({ page }) => {
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner&doc=${design}&v=1`);
  await expect(page.getByTestId("doc-body")).toContainText("A quote note can notify people.");

  // 1. popover note: '@vi' → picker → Enter picks vishal (the popover stays open), then '#tag' as text.
  await selectText(page, "[data-testid=doc-body]", "A quote note can notify people.");
  await page.keyboard.press("Control+Alt+KeyQ");
  const pop = page.getByTestId("quote-popover");
  await expect(pop.getByTestId("quote-note")).toBeFocused();
  await page.keyboard.type("ask @vi");
  const menu = pop.getByTestId("note-mentions-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("option", { name: /@vishal/ })).toBeVisible();
  await shot(page, "01-popover-note-picker");
  await page.keyboard.press("Enter");
  await expect(menu).toBeHidden();
  await expect(pop).toBeVisible(); // Enter picked; it did not add the quote
  await page.keyboard.type("about #c23-tags");
  await expect(pop.getByTestId("quote-note")).toHaveValue("ask @vishal about #c23-tags");
  // Escape with the picker open closes the picker only
  await page.keyboard.type(" @vi");
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(pop).toBeVisible();
  for (let i = 0; i < 4; i++) await page.keyboard.press("Backspace"); // drop " @vi"
  await page.keyboard.press("Enter"); // closed list: Enter adds the quote
  await expect(pop).toBeHidden();

  // 2. a second quote without a note; its chip note gets '@tok' + ArrowDown/Tab in the composer.
  await selectText(page, "[data-testid=doc-body]", "Hash tags stay as text on the board.");
  await page.keyboard.press("Control+Alt+KeyQ");
  await expect(pop.getByTestId("quote-note")).toBeFocused();
  await page.keyboard.press("Enter");
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
  const chips = page.getByTestId("quote-chip");
  await expect(chips).toHaveCount(2);
  await expect(chips.nth(0).getByTestId("quote-chip-note")).toHaveValue("ask @vishal about #c23-tags");
  const chipNote = chips.nth(1).getByTestId("quote-chip-note");
  await chipNote.click();
  await page.keyboard.type("cc @tok");
  const chipMenu = chips.nth(1).getByTestId("note-mentions-menu");
  await expect(chipMenu).toBeVisible();
  await shot(page, "02-chip-note-picker");
  await page.keyboard.press("Tab");
  await expect(chipNote).toHaveValue("cc @tokuser ");
  // the wake preview counts the notes' mentions (the text is still empty)
  await expect(page.getByTestId("wake-preview")).toContainText("vishal");
  await expect(page.getByTestId("wake-preview")).toContainText("tokuser");

  // 3. send: the text itself names nobody.
  await page.getByTestId("composer-text").click();
  await page.keyboard.type("Two passages, see the notes.");
  await page.getByTestId("composer-text").press("Control+Enter");
  await expect(page.getByTestId("sent-note")).toBeVisible();

  // 4. on the board: mentions from the notes; vishal's wake feed has it as a mention.
  const msgs = await call("GET", `/v1/messages?ticket_id=${story}`, undefined, owner);
  const sent = msgs.find((m: any) => m.text === "Two passages, see the notes.");
  expect(sent.quotes.map((q: any) => q.note.trim())).toEqual(["ask @vishal about #c23-tags", "cc @tokuser"]);
  const evs = await call("GET", `/v1/events?subject_id=${story}`, undefined, owner);
  const ev = evs.find((e: any) => e.kind === "message_sent" && e.data.message === sent.id);
  expect(ev.data.mentions).toEqual(["vishal", "tokuser"]);
  const woke = await call("GET", "/v1/events?since=0&limit=500", undefined, vishal);
  expect(woke.some((e: any) => e.kind === "message_sent" && e.data.message === sent.id)).toBe(true);

  // 5. the quote cards show the notes (mention and tag as written).
  const row = page.getByTestId("thread-message").filter({ hasText: "Two passages, see the notes." });
  const cards = row.getByTestId("quote-card");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0).getByTestId("quote-note-text")).toContainText("ask @vishal about #c23-tags");
  await expect(cards.nth(1).getByTestId("quote-note-text")).toContainText("cc @tokuser");
  await row.scrollIntoViewIfNeeded();
  await shot(page, "03-quote-cards-notes");

  // 6. vishal's own view of the thread: the message is there for them.
  await page.goto(`${BASE()}/ui/ticket/${story}?as=vishal`);
  const theirs = page.getByTestId("thread-message").filter({ hasText: "Two passages, see the notes." });
  await expect(theirs.getByTestId("quote-note-text").first()).toContainText("@vishal");
  await theirs.scrollIntoViewIfNeeded();
  await shot(page, "04-vishal-view");
});
