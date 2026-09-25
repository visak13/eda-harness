// C19 board-UI quotes (s-35ca5ca2ac; design-10b21760d9 §14.5/§14.7; C18 board half 9d1e531/466d65a).
// On a throwaway board from THIS tree (never :9400): select text in the doc drawer (a design, at an
// older version) and in a chat message, Quote it with a note (the popover's button and Ctrl+Alt+Q, C20 ruling m-db0d013529),
// build three quotes from two sources plus one to remove, reorder them, send with Ctrl+Enter, and
// assert on the BOARD that the message carries quotes[] in chip order with notes, verified by C18.
// The message then renders three quote cards; the doc card opens that version at the quoted lines,
// the message card scrolls to the quoted message. Existing doc comments and code cards still render,
// and a board whose message contract lacks quotes[] offers no Quote at all.
// Browser: Chromium by default; CHAT_BROWSER=stockff runs the installed Firefox. One at a time.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { ADMIN } from "./board";
import { BASE, EPIC, expect, test } from "./fixtures";

const STOCK_FF = process.env.CHAT_BROWSER === "stockff";
const FIREFOX = process.env.EDP8_FIREFOX ?? "C:/Program Files/Mozilla Firefox/firefox.exe";
const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "c19-quotes", STOCK_FF ? "stockff" : "chromium");

if (STOCK_FF) test.use({ browserName: "firefox", channel: "moz-firefox", launchOptions: { executablePath: FIREFOX } });
test.use({ boardFile: "c19-quotes", trace: "retain-on-failure", screenshot: "only-on-failure" });
test.describe.configure({ mode: "serial", timeout: 120_000 });

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const arch = { "X-Participant": "arch" };
const owner = { "X-Participant": "owner" };

const V1 = [
  "# C19 design",
  "",
  "## 14.5 Quotes",
  "The board **validates** each quote: the text must occur in that source at that version.",
  "",
  "- `source`: `doc` | `message` | `code`.",
  "- For `doc`: `id` and `version`.",
  "",
  "## 14.7 Inline comment boxes",
  "Every quote becomes quote + note, and the draft tray survives a reload.",
].join("\n");
const V2 = V1.replace("survives a reload", "survives a reload and a panel hide");
const MSG = "The plan is **ready**: ship C19 right after C18 lands.\nSecond line of the architect's note.";

let story = "", design = "", archMsg = "";

/** Select from the first occurrence of `text` inside `scope` to the end of `until` after it (default:
 *  `text` itself), spanning element boundaries, like a drag. */
async function selectText(page: Page, scope: string, text: string, until?: string): Promise<void> {
  const ok = await page.evaluate(({ scope, text, until }) => {
    const root = document.querySelector(scope);
    if (!root) return false;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes: Text[] = [];
    let all = "";
    for (let n = walker.nextNode(); n; n = walker.nextNode()) { nodes.push(n as Text); all += (n as Text).data; }
    const at = all.indexOf(text);
    if (at < 0) return false;
    const stop = until ? all.indexOf(until, at) : at;
    if (stop < 0) return false;
    const endAt = until ? stop + until.length : at + text.length;
    const range = document.createRange();
    let pos = 0;
    for (const n of nodes) {
      const end = pos + n.data.length;
      if (at >= pos && at < end) range.setStart(n, at - pos);
      if (endAt > pos && endAt <= end) { range.setEnd(n, endAt - pos); break; }
      pos = end;
    }
    const sel = window.getSelection()!;
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  }, { scope, text, until });
  expect(ok, `"${text}" is on screen in ${scope}`).toBe(true);
}

/** A drag ends with mouseup on the document: the popover opens for the selection. */
async function releaseMouse(page: Page): Promise<void> {
  await page.evaluate(() => document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true })));
}

async function shot(page: Page, name: string): Promise<void> {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE, `${name}.png`) });
}

test.beforeAll(async () => {
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Quote story", parent_id: EPIC() }, owner)).id;
  const d = await call("POST", "/v1/docs", { doc_type: "design", title: "C19 quote design", body_md: V1, scope: EPIC() }, arch);
  design = d.id;
  await call("PATCH", `/v1/docs/${design}`, { body_md: V2 }, arch); // v2 exists: the quotes come from v1
  await call("POST", "/v1/links", { from_id: story, to_id: design, relation: "designed_by" }, arch);
  archMsg = (await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: MSG }, arch)).id;
  // Compatibility seeds: a code-anchored message and a design-review doc comment (document_context).
  const snippet = "def quote():\n    return True";
  const { createHash } = await import("node:crypto");
  await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: "code anchor", code_context: {
    repo_root: "C:/repo", path: "src/q.py", line_start: 3, line_end: 4, commit: "a".repeat(40), dirty: false, snippet,
    snippet_sha: createHash("sha256").update(snippet).digest("hex") } }, arch);
  await call("POST", "/v1/docs/comments", { ticket_id: story, design_ref: design, reviewed_version: 1,
    text: "Review comment on v1 (document_context)", idempotency_key: "c19-doc-comment" }, owner);
});

test("quote two doc passages and a message, reorder and remove, send, and see three quote cards", async ({ page }) => {
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
  await expect(page.getByTestId("thread")).toBeVisible();
  await expect(page.getByTestId("code-card")).toBeVisible(); // compatibility: code cards still render
  await expect(page.getByTestId("thread-message").filter({ hasText: "Review comment on v1" })).toHaveCount(1);

  // 1. the design at v1 in the drawer: a bold passage via the popover's Quote button, with a note.
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner&doc=${design}&v=1`);
  const body = page.getByTestId("doc-body");
  await expect(body).toContainText("survives a reload.");
  await selectText(page, "[data-testid=doc-body]", "The board validates each quote");
  await releaseMouse(page);
  const pop = page.getByTestId("quote-popover");
  await expect(pop).toBeVisible();
  // typed, not fill(): under stock Firefox a Playwright fill() never reached React state (typed keys do)
  await pop.getByTestId("quote-note").click();
  await page.keyboard.type("This is the rule I mean.");
  await shot(page, "01-doc-popover");
  await pop.getByTestId("quote-add").click();
  await expect(page.getByTestId("quote-added")).toContainText(story);

  // 2. a passage across two list items via Ctrl+Alt+Q, note typed, Enter adds.
  await selectText(page, "[data-testid=doc-body]", "message | code.", "For doc: id");
  await page.keyboard.press("Control+Alt+KeyQ");
  await expect(pop).toBeVisible();
  await expect(pop.getByTestId("quote-note")).toBeFocused();
  await page.keyboard.type("List item quote");
  await page.keyboard.press("Enter");
  await expect(pop).toBeHidden();

  // 3. one more doc passage that will be removed before sending.
  await selectText(page, "[data-testid=doc-body]", "Every quote becomes quote + note");
  await releaseMouse(page);
  await pop.getByTestId("quote-add").click();
  await expect(pop).toBeHidden();

  // 4. close the drawer; quote the architect's message (bold inside), no note.
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
  await expect(page.getByTestId("thread")).toBeVisible();
  await selectText(page, `li[id="${archMsg}"]`, "ready: ship C19");
  await releaseMouse(page);
  await pop.getByTestId("quote-add").click();
  await expect(pop).toBeHidden();

  // 5. four chips in pick order; remove the third, move the message quote to the top.
  const chips = page.getByTestId("quote-chip");
  await expect(chips).toHaveCount(4);
  await expect(page.getByTestId("quote-chip-label")).toHaveText([`${design} v1 L4`, `${design} v1 L6-7`, `${design} v1 L10`, `${archMsg} (arch)`]);
  await chips.nth(2).getByTestId("quote-chip-remove").click();
  await expect(chips).toHaveCount(3);
  await chips.nth(2).getByTestId("quote-chip-up").click();
  await chips.nth(1).getByTestId("quote-chip-up").click();
  await expect(page.getByTestId("quote-chip-label")).toHaveText([`${archMsg} (arch)`, `${design} v1 L4`, `${design} v1 L6-7`]);
  // the chips survive a reload (tab-local tray)
  await page.reload();
  await expect(page.getByTestId("quote-chip")).toHaveCount(3);
  await page.getByTestId("composer-text").click();
  await page.keyboard.type("Three quotes, one message: please confirm the order.");
  await shot(page, "02-composer-chips");
  await page.getByTestId("composer-text").press("Control+Enter");
  await expect(page.getByTestId("sent-note")).toBeVisible();
  await expect(page.getByTestId("quote-chip")).toHaveCount(0);

  // 6. on the board: quotes[] in chip order, verified (heading derived), notes kept.
  const msgs = await call("GET", `/v1/messages?ticket_id=${story}`, undefined, owner);
  const sent = msgs.find((m: any) => (m.quotes ?? []).length > 0);
  expect(sent.text).toBe("Three quotes, one message: please confirm the order.");
  expect(sent.quotes.map((q: any) => [q.source, q.id, q.version ?? null])).toEqual([["message", archMsg, null], ["doc", design, 1], ["doc", design, 1]]);
  expect(sent.quotes[0].text).toBe("ready**: ship C19");
  expect(sent.quotes[1]).toMatchObject({ text: "The board **validates** each quote", note: "This is the rule I mean.", locator: { heading: "14.5 Quotes", line_start: 4, line_end: 4 } });
  expect(sent.quotes[2]).toMatchObject({ note: "List item quote", locator: { line_start: 6, line_end: 7 } });
  expect(sent.quoted).toContain(`— ${design} v1 §14.5 L4-4`);

  // 7. three quote cards above the text.
  const row = page.getByTestId("thread-message").filter({ hasText: "please confirm the order" });
  const cards = row.getByTestId("quote-card");
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(0).getByTestId("quote-source")).toContainText(`${archMsg} (arch)`);
  await expect(cards.nth(1).getByTestId("quote-source")).toContainText(`${design} v1 §14.5 L4`);
  await expect(cards.nth(1).getByTestId("quote-passage")).toHaveText("The board validates each quote"); // read as rendered
  await expect(cards.nth(1).getByTestId("quote-note-text")).toContainText("This is the rule I mean.");
  await row.scrollIntoViewIfNeeded();
  await shot(page, "03-quote-cards");

  // 8. the message card scrolls to the quoted message; the doc card opens v1 at line 4.
  await cards.nth(0).getByTestId("quote-source").click();
  await expect(page.locator(`li[id="${archMsg}"]`)).toHaveAttribute("data-flash", "1");
  await cards.nth(1).getByTestId("quote-source").click();
  await expect(page).toHaveURL(new RegExp(`doc=${design}&v=1&line=4-4`));
  const focus = page.locator("[data-testid=doc-body] [data-quote-focus]");
  await expect(focus).toHaveCount(1);
  await expect(focus).toContainText("The board validates each quote");
  await expect(page.getByTestId("doc-body")).not.toContainText("panel hide"); // v1, not v2
  await shot(page, "04-doc-at-quoted-line");
});

test("a board without quotes[] in its message contract offers no Quote", async ({ page }) => {
  await page.route("**/v1/describe/message", (r) => r.fulfill({ json: { ok: true, value: { type: "message", contract: "A message (pre-C18)." } } }));
  await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
  await expect(page.getByTestId("thread")).toBeVisible();
  await selectText(page, `li[id="${archMsg}"]`, "ready: ship C19");
  await releaseMouse(page);
  await page.keyboard.press("Control+Alt+KeyQ");
  await page.waitForTimeout(300); // nothing may appear; a short settle before asserting absence
  await expect(page.getByTestId("quote-popover")).toHaveCount(0);
  await expect(page.getByTestId("quote-chips")).toHaveCount(0);
});
