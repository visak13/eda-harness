import { test, expect, BASE, type Page } from "./fixtures";
import type { APIRequestContext } from "@playwright/test";

// S19 (s-d330d76467), criterion c-d0eadfea93 — owner m-845b58f25c: "the chat freezes occasionally
// and needs to be refreshed". Two measured causes, both reproduced red on 673803f by this file:
// (1) the page read the WAKE-filtered /v1/feed, so a note that did not page the viewer (any note
// between seats on the owner's epic) never reached the open page — even the no-draft control failed;
// (2) an unsent composer draft HELD the page's refresh (useDraftGuard), and drafts persist across
// reloads and hide in a collapsed composer. Each test provokes one condition, posts from another
// seat and requires the message on screen within 5 s WITHOUT a reload, with the draft untouched.
test.use({ boardFile: "s19-freeze" });
const SHOTS = "e2e/evidence/s19";
const PHASE = process.env.S19_PHASE ?? "after";

async function call(request: APIRequestContext, method: string, path: string, data: unknown, actor: string) {
  const res = await request.fetch(`${BASE()}${path}`, { method, headers: { "X-Participant": actor }, data });
  expect(res.ok(), `${method} ${path}: ${await res.text()}`).toBe(true);
  return (await res.json()).value;
}

let epicId: string | null = null;
async function epic(request: APIRequestContext): Promise<string> {
  if (!epicId) epicId = (await call(request, "POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Freeze epic" }, "owner")).id as string;
  return epicId!;
}

/** Wait until the live feed is attached (the page has rendered the thread once and is idle). */
async function openEpic(page: Page, id: string) {
  await page.goto(`/ui/epic/${id}?as=owner`);
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeVisible();
  await page.waitForTimeout(1500); // SSE connected (": ready" frame) before the provoking post
}

async function arrives(page: Page, request: APIRequestContext, id: string, text: string) {
  const t0 = Date.now();
  await call(request, "POST", "/v1/messages", { ticket_id: id, kind: "note", text }, "arch");
  await expect(page.getByText(text, { exact: true })).toBeVisible({ timeout: 5_000 });
  return Date.now() - t0;
}

test("control: with no draft a new message renders live", async ({ page, request }) => {
  const id = await epic(request);
  await openEpic(page, id);
  const ms = await arrives(page, request, id, "Arrives with an empty composer");
  console.log(`no-draft arrival ${ms} ms`);
});

test("a note between two seats (not addressed to the viewer) renders live", async ({ page, request }) => {
  // The measured root cause: the page subscribed to the WAKE-filtered feed, which never carries a
  // note that pages someone else, so the owner's open epic stayed frozen until reload.
  const id = await epic(request);
  await openEpic(page, id);
  const t0 = Date.now();
  await call(request, "POST", "/v1/messages", { ticket_id: id, kind: "note", to: "arch", text: "Seat-to-seat note" }, "arch");
  await expect(page.getByText("Seat-to-seat note", { exact: true })).toBeVisible({ timeout: 5_000 });
  console.log(`seat-to-seat arrival ${Date.now() - t0} ms`);
});

test("a typed, unsent draft does not freeze the thread", async ({ page, request }) => {
  const id = await epic(request);
  await openEpic(page, id);
  const box = page.getByRole("textbox", { name: "Message", exact: true });
  await box.fill("Half-written reply the owner has not sent");
  const ms = await arrives(page, request, id, "Arrives while a draft is typed");
  await expect(box).toHaveValue("Half-written reply the owner has not sent");
  await page.screenshot({ path: `${SHOTS}/${PHASE}-freeze-typed-draft.png` });
  console.log(`typed-draft arrival ${ms} ms`);
});

test("a draft restored after reload does not freeze the thread", async ({ page, request }) => {
  const id = await epic(request);
  await openEpic(page, id);
  const box = page.getByRole("textbox", { name: "Message", exact: true });
  await box.fill("Draft left over from yesterday");
  await page.reload();
  await expect(box).toHaveValue("Draft left over from yesterday");
  await page.waitForTimeout(1500);
  const ms = await arrives(page, request, id, "Arrives with a restored draft");
  console.log(`restored-draft arrival ${ms} ms`);
});

test("a draft inside a collapsed composer does not freeze the thread", async ({ page, request }) => {
  const id = await epic(request);
  await openEpic(page, id);
  const box = page.getByRole("textbox", { name: "Message", exact: true });
  await box.fill("Draft hidden by the collapsed message box");
  await page.getByRole("button", { name: "Collapse message box" }).click();
  await expect(page.getByTestId("composer-collapsed-bar")).toBeVisible();
  const ms = await arrives(page, request, id, "Arrives while the composer is collapsed");
  await page.screenshot({ path: `${SHOTS}/${PHASE}-freeze-collapsed-draft.png` });
  await page.getByTestId("composer-collapsed-bar").click();
  await expect(box).toHaveValue("Draft hidden by the collapsed message box");
  console.log(`collapsed-draft arrival ${ms} ms`);
});

test("a draft on a story does not freeze the story thread", async ({ page, request }) => {
  const id = await epic(request);
  const story = (await call(request, "POST", "/v1/tickets", { kind: "story", work_type: "bug", parent_id: id, title: "Freeze story" }, "arch")).id as string;
  await page.goto(`/ui/ticket/${story}?as=owner`);
  const box = page.getByRole("textbox", { name: "Message", exact: true });
  await expect(box).toBeVisible();
  await page.waitForTimeout(1500);
  await box.fill("Story draft");
  await arrives(page, request, story, "Arrives on the story with a draft");
  await expect(box).toHaveValue("Story draft");
});
