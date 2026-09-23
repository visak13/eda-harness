import fs from "node:fs";
import { test, expect, BASE, type Page } from "./fixtures";

// S19 (s-d330d76467), criterion c-4bc0090b1d — owner m-845b58f25c: "the v3 renders from astra arent
// followed through and through for design page". Binding target: docs/ui-redesign-concepts/
// revision3-clean-review.png (dec-23c1a38a6e). The seed reproduces the render's content (epic "Board
// improvements", design "Conversation-first workflow" at version 3 with an open review request) so
// every screen of the design page can be put side by side with the render: the viewer, the Request
// changes state, the scrolled document, and the dedicated Open-in-tab page, at 1440×900 and 844×390.
test.use({ boardFile: "s19-design" });
const SHOTS = "e2e/evidence/s19";
const PHASE = process.env.S19_PHASE ?? "after";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${PHASE}-design-${name}.png` });

const BODY = [
  "# Keep the work and conversation together",
  "",
  "The epic is your everyday working surface. Documents open when you need them; they do not replace the conversation.",
  "",
  "## 1. Context stays visible",
  "",
  "- Status, owner and assignee stay near the epic title.",
  "- The current design is linked prominently beside History and Files & evidence.",
  "- Opening this viewer preserves your epic message draft.",
  "",
  "## 2. Review the version you can see",
  "",
  "Approve design targets this displayed version. If a newer draft arrives, review that version before approving. Earlier feedback remains in the conversation.",
  "",
  "## 3. Feedback stays here while you write",
  "",
  "Request changes opens the feedback box alongside the design. Send posts your note to the original epic conversation, addressed to the architect. You remain in this viewer.",
  "",
  "## 4. Open in tab is optional",
  "",
  "The dedicated view keeps the same source epic, document version and review actions. No detour is needed to comment.",
].join("\n");

async function call(method: string, path: string, data: unknown, actor: string, admin = false) {
  const r = await fetch(`${BASE()}${path}`, { method, headers: { "content-type": "application/json", ...(admin ? { "X-Admin": "t" } : { "X-Participant": actor }) }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${path} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

let seeded: { epic: string; doc: string } | null = null;
async function seed() {
  if (seeded) return seeded;
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Board improvements" }, "owner")).id as string;
  const doc = (await call("POST", "/v1/docs", { doc_type: "design", title: "Conversation-first workflow", scope: epic, body_md: BODY.replace("together", "together (draft)") }, "arch")).id as string;
  await call("PATCH", `/v1/docs/${doc}`, { body_md: BODY.replace("together", "together (draft 2)") }, "arch");
  await call("PATCH", `/v1/docs/${doc}`, { body_md: BODY }, "arch"); // version 3, as in the render
  await call("POST", "/v1/links", { from_id: epic, to_id: doc, relation: "designed_by" }, "arch");
  await call("PATCH", `/v1/tickets/${epic}`, { design_ref: doc }, "arch");
  await call("POST", "/v1/messages", { ticket_id: epic, kind: "note", to: "owner", text: "The design is ready for your review." }, "arch");
  await call("POST", `/v1/gates/${epic}/design_signoff/open`, { note: "please review v3" }, "arch");
  seeded = { epic, doc };
  return seeded;
}

const SIZES = [[1440, 900], [844, 390]] as const;

for (const [w, h] of SIZES) {
  test(`design page screens ${w}x${h}`, async ({ page, context }) => {
    fs.mkdirSync(SHOTS, { recursive: true });
    const { epic } = await seed();
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`/ui/epic/${epic}?as=owner`);
    await page.getByTestId("work-design").click();
    const dialog = page.getByRole("dialog").filter({ hasText: "Conversation-first workflow" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Approve design" })).toBeVisible();
    await page.waitForTimeout(500);
    await shot(page, `${w}-viewer`);
    await dialog.getByRole("button", { name: "Request changes", exact: true }).click();
    const feedback = dialog.getByRole("textbox").last();
    await feedback.fill("Please clarify what happens if a new design version arrives while I'm writing feedback.\n\nKeep my note and let me compare the newer version before approving.");
    await page.waitForTimeout(300);
    await shot(page, `${w}-request-changes`);
    // Scroll the document column (and the dialog) to the end: the rest of the page, not only the first screen.
    await dialog.evaluate((el) => { for (const n of el.querySelectorAll<HTMLElement>("*")) if (n.scrollHeight > n.clientHeight + 4) n.scrollTop = n.scrollHeight; });
    await page.waitForTimeout(300);
    await shot(page, `${w}-scrolled`);
    const [tab] = await Promise.all([context.waitForEvent("page"), dialog.getByRole("link", { name: /Open in tab/ }).click()]);
    await tab.setViewportSize({ width: w, height: h });
    await tab.waitForLoadState();
    await expect(tab.getByText("Conversation-first workflow").first()).toBeVisible();
    await tab.waitForTimeout(800);
    await tab.screenshot({ path: `${SHOTS}/${PHASE}-design-${w}-open-in-tab.png` });
    await tab.close();
  });
}
