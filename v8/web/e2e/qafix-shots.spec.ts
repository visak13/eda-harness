// qa report-689ceb50f0 (architect m-b1eaae38c8): one pass that shoots each fixed screen at 1280 and 390 and asserts what the
// shot shows. Evidence goes to e2e/evidence/qafix/. Throwaway board from THIS tree (never :9400).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { ADMIN } from "./board";
import { BASE, EPIC, expect, test } from "./fixtures";

const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "qafix");
test.use({ boardFile: "qafix-shots" });
test.describe.configure({ mode: "serial", timeout: 180_000 });

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const arch = { "X-Participant": "arch" };
const owner = { "X-Participant": "owner" };
const MSG = "The plan is ready: ship the popover fix right after the layout review lands.";
let story = "", docId = "";

test.beforeAll(async () => {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Make the Epics list readable on a phone: the title column keeps its width" }, owner);
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Popover story", parent_id: EPIC() }, owner)).id;
  await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: MSG }, arch);
  docId = (await call("POST", "/v1/docs", { doc_type: "design", title: "Layout design", body_md: "# Layout\n\n## Rules\nText has room.", scope: EPIC() }, arch)).id;
  await call("POST", "/v1/links", { from_id: story, to_id: docId, relation: "designed_by" }, arch);
});

const shoot = (page: Page, name: string, label: string) => page.screenshot({ path: path.join(EVIDENCE, `${name}-${label}.png`) });
async function settle(page: Page, url: string): Promise<void> {
  await page.goto(`${BASE()}/ui${url}${url.includes("?") ? "&" : "?"}as=owner`);
  await page.waitForTimeout(900);
  await expect(page.getByText(/was updated/i)).toHaveCount(0); // item 1: no false reload banner on any page
}

for (const [label, size] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`fixed screens at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    // item 1 + 2: no banner; the Epics title shows; Library tabs; Admin teammates
    await settle(page, "/epics");
    await expect(page.locator("[data-testid=epic-row] div[title]").first()).toBeVisible();
    expect((await page.locator("[data-testid=epic-row] div[title]").first().boundingBox())!.width).toBeGreaterThan(60);
    await shoot(page, "1-2-epics", label);
    await settle(page, "/library/knowledge");
    await shoot(page, "2-library-tabs", label);
    await settle(page, "/admin?tab=teammates");
    await shoot(page, "2-admin-teammates", label);

    // item 3: the help panel on the epic page
    await settle(page, `/epic/${EPIC()}`);
    await shoot(page, "5-epic-header", label);
    await page.keyboard.press("Control+/");
    const panel = page.getByRole("dialog", { name: "What am I looking at?" });
    await expect(panel).toBeVisible();
    await expect(panel).not.toContainText(/demo|phase ladder|source-bound|lint \+ dry run|owner's words verbatim/i);
    await expect(panel.getByRole("heading", { name: "On this page", exact: true })).toBeVisible();
    await shoot(page, "3-help-epic", label);
    await page.keyboard.press("Escape");
    await settle(page, "/epics");
    await page.keyboard.press("Control+/");
    await expect(panel).toBeVisible();
    await expect(panel.getByRole("heading", { name: "On this page", exact: true })).toHaveCount(0); // nothing to list there: no empty heading
    await shoot(page, "3-help-epics", label);
    await page.keyboard.press("Escape");

    // item 4: Mark closes the popover and a toast says so
    await page.addInitScript(() => { try { localStorage.setItem("edp8.ui.owner.composer-collapsed", "0"); } catch { /* blocked */ } });
    await settle(page, `/ticket/${story}`);
    await page.evaluate((text) => {
      const root = document.querySelector("[data-testid=thread]")!;
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const at = (n as Text).data.indexOf(text);
        if (at < 0) continue;
        const r = document.createRange(); r.setStart(n, at); r.setEnd(n, at + text.length);
        const sel = window.getSelection()!; sel.removeAllRanges(); sel.addRange(r);
        document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
        return;
      }
    }, "ship the popover fix");
    await expect(page.getByTestId("quote-popover")).toBeVisible();
    await shoot(page, "4-popover-before-mark", label);
    await page.getByTestId("quote-popover-mark").click();
    await expect(page.getByTestId("quote-popover")).toHaveCount(0);
    await expect(page.getByTestId("composer-flash")).toHaveText("Requirement marked."); // in the composer's status slot, nothing moves
    await shoot(page, "4-popover-after-mark", label);

    // /doc: one panel toggle, and the way back is named by the epic's title
    await settle(page, `/doc/${docId}`);
    await expect(page.getByRole("button", { name: /Show panel|Reader mode/ })).toHaveCount(1);
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Spike epic");
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).not.toContainText("epic-");
    await shoot(page, "9-doc", label);

    // item 7: Seats spawn form (Model select, ticket placeholder), the composer's notify line, Browse all records
    await settle(page, "/seats");
    await shoot(page, "7-seats", label);
    await settle(page, `/ticket/${story}`);
    await page.getByTestId("composer-collapse").click().catch(() => {});
    await shoot(page, "7-composer-notify", label);
    await settle(page, "/epics");
    await page.keyboard.press("Control+k");
    await page.waitForTimeout(500);
    await shoot(page, "7-find-browse", label);
    const browse = page.getByRole("button", { name: "Browse all records" });
    if (await browse.count()) expect((await browse.boundingBox())!.height).toBeLessThan(48); // one line (a wrapped label is 60+)
  });
}

// qa fail 9 (live): an architect seat shows "Architect · running", then "Architect · closed" within 2 s of the close.
test("epic header: architect running, then closed within 2 s of the close", async ({ page }) => {
  const id = `architect.${EPIC()}`;
  await call("POST", "/v1/participants", { type: "agent", role: "architect", handle: id, id }, { "X-Admin": ADMIN });
  await call("PUT", "/v1/sessions/sess-arch", { participant_id: id, ticket_id: EPIC(), pool_id: "e2e", state: "alive", last_output_at: new Date().toISOString() }, { "X-Admin": ADMIN });
  await page.route("**/v1/pool/capabilities", (route) => route.fulfill({ status: 200, contentType: "application/json",
    body: JSON.stringify({ ok: true, value: { resume_parked: true, resume_closed: true, park: true, spawn: true }, hint: "" }) }));
  for (const [label, size] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
    await call("PUT", "/v1/sessions/sess-arch", { participant_id: id, ticket_id: EPIC(), pool_id: "e2e", state: "alive", last_output_at: new Date().toISOString() }, { "X-Admin": ADMIN });
    await page.setViewportSize(size);
    await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner`);
    const row = page.getByTestId("work-architect");
    await expect(row).toContainText("Architect · running");
    await shoot(page, "6-architect-running", label);
    const t0 = Date.now();
    await call("PUT", "/v1/sessions/sess-arch", { participant_id: id, ticket_id: EPIC(), pool_id: "e2e", state: "dead", reason: "closed by owner" }, { "X-Admin": ADMIN });
    await expect(row).toContainText("Architect · closed", { timeout: 2000 });
    console.log(`architect closed shown after ${Date.now() - t0} ms at ${label}`);
    await shoot(page, "6-architect-closed", label);
  }
});

// qa fail 7/4 at 390: the open composer does not hide a message (scrolled to the end), the Library tabs wrap, /doc fits, Find fits.
test("390 px: ticket with the composer open scrolled to its end, Library tabs, doc, Find", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => { try { localStorage.setItem("edp8.ui.owner.composer-collapsed", "0"); } catch { /* blocked */ } });
  const doc = (await call("POST", "/v1/docs", { doc_type: "design", title: "Layout design", body_md: "# Layout\n\n## Rules\nText has room.", scope: EPIC() }, arch)).id;
  await call("POST", "/v1/links", { from_id: story, to_id: doc, relation: "designed_by" }, arch);
  await settle(page, `/ticket/${story}`);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.waitForTimeout(200);
  await shoot(page, "7-ticket-composer-end", "390");
  await settle(page, "/library/knowledge");
  await shoot(page, "2-library-tabs-wrapped", "390");
  await settle(page, `/doc/${doc}`);
  await shoot(page, "8-doc", "390");
  await settle(page, "/epics");
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(500);
  await shoot(page, "3-find-placeholder", "390");
});

// architect m-2da889e64a: Admin -> Services for someone the board refuses (one plain line, no header names, said once) and for
// someone who is not an admin at all; the admin view is shot by text-fits (ok-admin-services-*).
for (const [label, size] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`admin services when the board refuses, and as a non-admin, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await settle(page, "/admin?tab=services");
    const alerts = page.getByRole("alert");
    await expect(alerts.first()).toContainText("Only an admin can manage services. Ask an admin to give you admin rights.");
    await expect(page.getByText(/X-Token|X-Participant/)).toHaveCount(0);
    await expect(page.getByText("Only an admin can manage services.")).toHaveCount(1); // said once, not once per panel
    await shoot(page, "10-services-refused", label);
    await page.route("**/v1/whoami", async (route) => {
      const res = await route.fetch(); const body = await res.json();
      body.value.admin = false; if (body.value.participant) body.value.participant.admin = false;
      await route.fulfill({ response: res, json: body });
    });
    await settle(page, "/admin?tab=services");
    await expect(page.getByTestId("admin-forbidden")).toBeVisible();
    await shoot(page, "10-services-non-admin", label);
  });
}
