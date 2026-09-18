import { test, expect, BASE } from "./fixtures";
import { seedEpic } from "./g3a.seed";
test.use({ boardFile: "s2-live" });

test("coalesced delivered burst/replay keeps draft, caret, focus, scroll and avatar DOM", async ({ page }) => {
  const fixture = await seedEpic();
  let batch = ": ready\n\n";
  let deliveries = 0;
  await page.route("**/v1/feed?*", async (route) => {
    deliveries++;
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: batch });
  });
  let refetches = 0, avatarRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes(`/v1/tickets/${fixture.story}/page`)) refetches++;
    if (request.url().includes("/v1/avatars/")) avatarRequests++;
  });
  await page.goto(`/ui/ticket/${fixture.story}?as=owner`);
  const draft = page.getByRole("textbox", { name: "Message", exact: true });
  await draft.fill("A draft that must survive live refresh");
  await draft.evaluate((el: HTMLTextAreaElement) => {
    el.setSelectionRange(5, 10);
    (window as any).__s2Draft = el;
    (window as any).__s2Avatar = document.querySelector('[data-avatar-for="owner"]');
  });
  await page.waitForTimeout(300);
  const initialRequests = refetches, initialAvatars = avatarRequests;
  const scroll = await page.evaluate(() => scrollY);
  const events = (subject: string, first: number) => Array.from({ length: 20 }, (_, i) => `data: ${JSON.stringify({ seq: first + i, kind: "message_sent", subject_id: subject })}\n\n`).join("");
  batch = events("unrelated-ticket", 100);
  const delivered = deliveries;
  await expect.poll(() => deliveries).toBeGreaterThan(delivered);
  await page.waitForTimeout(350);
  expect(refetches).toBe(initialRequests);
  expect(avatarRequests).toBe(initialAvatars);
  batch = events(fixture.story, 200);
  await expect(page.getByTestId("live-new")).toContainText("40 new");
  expect(refetches).toBe(initialRequests);
  await page.waitForTimeout(1100); // replay the same sequence on reconnect
  await expect(page.getByTestId("live-new")).toContainText("40 new");
  await expect(draft).toHaveValue("A draft that must survive live refresh");
  expect(await draft.evaluate((el: HTMLTextAreaElement) => el === (window as any).__s2Draft && el.selectionStart === 5 && el.selectionEnd === 10 && document.activeElement === el)).toBe(true);
  expect(await page.evaluate(() => scrollY)).toBe(scroll);
  await page.getByTestId("live-new").click();
  await expect.poll(() => refetches).toBe(initialRequests + 1);
  await expect(draft).toHaveValue("A draft that must survive live refresh");
  expect(await draft.evaluate((el) => el === (window as any).__s2Draft)).toBe(true);
  expect(await page.evaluate(() => document.querySelector('[data-avatar-for="owner"]') === (window as any).__s2Avatar)).toBe(true);
  expect(avatarRequests).toBe(initialAvatars);
  // Clean-state relevant refresh becomes visible within 2s after a delivered response.
  await draft.fill("");
  const response = await fetch(`${BASE()}/v1/messages`, { method: "POST", headers: { "X-Participant": "owner", "content-type": "application/json" }, body: JSON.stringify({ ticket_id: fixture.story, kind: "note", text: "S2 fresh relevant message" }) });
  expect(response.ok).toBeTruthy();
  batch = events(fixture.story, 300);
  await expect(page.getByText("S2 fresh relevant message", { exact: true })).toBeVisible({ timeout: 2000 });
  expect(refetches).toBe(initialRequests + 2);
});
