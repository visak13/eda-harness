import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { test, expect } from "./fixtures";
import { seedEpic } from "./g3a.seed";

// R1 repair captures (design-a2e5369133): every screen at 1440x900 beside the revision3 renders,
// plus the owner's 2026-09-20 defects (composer not pinned, Reply hangs, Load older unstyled).
test.use({ boardFile: "r1-captures" });
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "r1");
const BASE = () => process.env.EDP8_E2E_BASE!;
async function call(method: string, p: string, body: unknown, headers: Record<string, string>) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
  const j = (await r.json()) as any; if (!r.ok || !j.ok) throw new Error(`${method} ${p} ${r.status} ${JSON.stringify(j.error ?? j)}`); return j.value;
}
async function shot(page: any, name: string, full = false) { fs.mkdirSync(OUT, { recursive: true }); await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: full }); }

test("captures", async ({ page }) => {
  test.setTimeout(180_000);
  const f = await seedEpic();
  // 130 messages so the thread pages (100/page) and "Load older" shows.
  for (let i = 1; i <= 130; i++) {
    const by = i % 2 ? "owner" : `architect.g3a-1`;
    await call("POST", "/v1/messages", { ticket_id: f.epic, kind: i % 7 === 0 ? "question" : "note", to: i % 2 ? "architect.g3a-1" : "owner", text: `Message ${i}: keep the conversation central and the composer reachable at every scroll position.` }, { "X-Participant": by });
  }
  // One image attachment staged by the architect and finalised on a message (§18.1).
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
  const form = new FormData();
  form.append("file", new Blob([png], { type: "image/png" }), "board-layout-sketch.png");
  form.append("ticket_id", f.epic); form.append("note", "Illustrative layout");
  const up = await fetch(`${BASE()}/v1/artifacts/upload`, { method: "POST", headers: { "X-Participant": "architect.g3a-1" }, body: form });
  const staged = (await up.json()) as any; if (!staged.ok) throw new Error(JSON.stringify(staged));
  await call("POST", "/v1/messages", { ticket_id: f.epic, kind: "note", to: "owner", text: "Here is a compact sketch. Your design review stays one click away, and feedback comes back to this thread.", artifacts: [staged.value.id] }, { "X-Participant": "architect.g3a-1" });
  // The doc is the epic's design (design_ref) so the viewer opens in review mode, as on a real epic.
  await call("PATCH", `/v1/tickets/${f.epic}`, { design_ref: f.doc }, { "X-Participant": "architect.g3a-1" });
  const errors: string[] = [];
  page.on("pageerror", (e: Error) => errors.push(e.message));
  // c-d83b97253a: prove opening fetches only the NEWEST page — the epic page
  // endpoint embeds the newest 100, and the /thread cursor endpoint is hit
  // ONLY when "Load older" is clicked (never a full-thread fetch on open).
  const threadReqs: string[] = [];
  page.on("request", (r: any) => { const u = r.url().replace(BASE(), ""); if (/\/thread(\?|$)/.test(u)) threadReqs.push(`${r.method()} ${u}`); });
  await page.goto(`/ui/epic/${f.epic}?as=owner`);
  await expect(page.getByTestId("conversation")).toBeVisible();
  await page.waitForTimeout(400);
  const threadReqsOnOpen = [...threadReqs];
  // The indicator is present while older pages remain; a short timeout keeps a legitimately
  // absent indicator (all pages loaded) from auto-waiting the whole test budget.
  const indicatorOnOpen = await page.getByTestId("thread-page-indicator").textContent({ timeout: 2_000 }).catch(() => null);
  await shot(page, "01-epic-top");
  await shot(page, "01-epic-full", true);
  // Is the composer visible without scrolling? Record its box.
  const composer = page.getByTestId("conversation-composer");
  const box = await composer.boundingBox();
  const vh = page.viewportSize()!.height;
  fs.writeFileSync(path.join(OUT, "composer-box.json"), JSON.stringify({ box, vh, visibleInViewport: !!box && box.y < vh }, null, 2));
  // Load older
  const older = page.getByRole("button", { name: /Load older/ });
  if (await older.count()) { await older.scrollIntoViewIfNeeded(); await shot(page, "02-load-older-before"); await older.click(); await page.waitForTimeout(800); await shot(page, "02-load-older-after"); }
  const indicatorAfterOlder = await page.getByTestId("thread-page-indicator").textContent({ timeout: 2_000 }).catch(() => null);
  // Evidence for c-d83b97253a: no /thread fetch on open, one after Load older; page indicator "older N-M of T".
  fs.writeFileSync(path.join(OUT, "thread-pagination.json"), JSON.stringify({
    threadReqsOnOpen, threadReqsAfterOlder: threadReqs, fullThreadFetchOnOpen: threadReqsOnOpen.length > 0,
    indicatorOnOpen, indicatorAfterOlder,
  }, null, 2));
  expect(threadReqsOnOpen, "opening the epic must not fetch the thread — the newest page is embedded in the epic page").toEqual([]);
  // Reply
  const reply = page.getByTestId("thread-reply").first();
  await reply.scrollIntoViewIfNeeded(); await reply.click(); await page.waitForTimeout(600);
  await shot(page, "03-after-reply");
  await shot(page, "03-after-reply-full", true);
  const chip = page.getByTestId("reply-chip");
  const attachment = page.getByTestId("attachment-card").first();
  await attachment.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(500);
  await shot(page, "03b-attachment-card");
  // Open in tab keeps the session: open Files & evidence, follow "Open in tab", the new tab must not 401.
  await page.getByTestId("work-files").click(); await page.waitForTimeout(600); await shot(page, "03c-files-drawer");
  const [tab] = await Promise.all([page.context().waitForEvent("page"), page.getByRole("link", { name: /Open in tab/ }).click()]);
  await tab.waitForLoadState(); await tab.waitForTimeout(800);
  await tab.screenshot({ path: path.join(OUT, "03d-open-in-tab.png") });
  const tabText = await tab.locator("body").innerText();
  fs.writeFileSync(path.join(OUT, "open-in-tab.json"), JSON.stringify({ url: tab.url(), relogin: /token|sign in|log in|401|identity/i.test(tabText), excerpt: tabText.slice(0, 300) }, null, 2));
  await tab.close();
  await page.keyboard.press("Escape");
  fs.writeFileSync(path.join(OUT, "reply.json"), JSON.stringify({ chipVisible: await chip.isVisible().catch(() => false), chipBox: await chip.boundingBox().catch(() => null), focused: await page.evaluate(() => (document.activeElement as HTMLElement)?.dataset?.testid ?? document.activeElement?.tagName), errors }, null, 2));
  // Design viewer
  await page.goto(`/ui/epic/${f.epic}?as=owner`); await page.getByTestId("work-design").click(); await page.waitForTimeout(900); await shot(page, "04-design-viewer");
  // Review mode: open the design_signoff gate as the architect, reload, capture Approve/Request changes + the feedback panel.
  await call("POST", `/v1/gates/${f.epic}/design_signoff/open`, { note: "please review v2" }, { "X-Participant": "architect.g3a-1" }).catch((e) => console.log("gate open", String(e)));
  await page.goto(`/ui/epic/${f.epic}?as=owner`); await page.getByTestId("work-design").click(); await page.waitForTimeout(900); await shot(page, "04a-design-review");
  const req = page.getByRole("button", { name: "Request changes", exact: true });
  if (await req.count()) { await req.click(); await page.waitForTimeout(500); await shot(page, "04a-design-request-changes"); }
  await page.keyboard.press("Escape"); await page.waitForTimeout(300);
  await page.getByTestId("work-design").click(); await page.waitForTimeout(600);
  const [docTab] = await Promise.all([page.context().waitForEvent("page"), page.getByRole("link", { name: "Open in tab" }).click()]);
  await docTab.waitForLoadState(); await docTab.waitForTimeout(800); await docTab.screenshot({ path: path.join(OUT, "04b-design-open-in-tab.png") });
  fs.writeFileSync(path.join(OUT, "design-open-in-tab.json"), JSON.stringify({ url: docTab.url(), excerpt: (await docTab.locator("body").innerText()).slice(0, 200) }));
  await docTab.close();
  // Usage widget — wait for the rail widget to mount (it renders once whoami resolves) so the
  // capture is deterministic rather than racing the navigation.
  await page.goto(`/ui/epic/${f.epic}?as=owner`);
  const usage = page.getByTestId("usage-open");
  await usage.waitFor({ state: "visible", timeout: 15_000 });
  await usage.click();
  await page.getByTestId("usage-freshness").waitFor({ timeout: 10_000 }).catch(() => {});
  await page.waitForTimeout(600); await shot(page, "05-usage");
  // Ticket page
  await page.goto(`/ui/ticket/${f.story}?as=owner`); await page.waitForTimeout(800); await shot(page, "06-ticket"); await shot(page, "06-ticket-full", true);
  // Settings
  await page.goto(`/ui/settings?as=owner`); await page.waitForTimeout(800); await shot(page, "07-settings-profile");
  await page.goto(`/ui/settings?as=owner&tab=slack`); await page.waitForTimeout(600); await shot(page, "07-settings-slack");
  // Epics + Seats + Decisions
  await page.goto(`/ui/epics?as=owner`); await page.waitForTimeout(600); await shot(page, "08-epics");
  await page.goto(`/ui/seats?as=owner`); await page.waitForTimeout(600); await shot(page, "09-seats");
  await page.goto(`/ui/me?as=owner`); await page.waitForTimeout(600); await shot(page, "10-needs-you");
  fs.writeFileSync(path.join(OUT, "errors.json"), JSON.stringify(errors, null, 2));
});
