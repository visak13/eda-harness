import { expect, test } from "@playwright/test";

// The walking-skeleton acceptance (criterion c-e348a49a44): a real browser loads the SPA
// served by a spawned board at /app?as=owner, sees the identity rendered from an
// authenticated /v1/whoami, and receives — with no reload — a live feed event that the
// test posts via POST /v1/messages. This proves all three seams (serve-under-prefix,
// identity→headers, SSE fetch-stream) end-to-end on the production interfaces.
const BASE = process.env.EDP8_E2E_BASE!;
const EPIC = process.env.EDP8_E2E_EPIC!;

test("SPA renders whoami and receives a live feed event within 5s", async ({ page }) => {
  await page.goto(`${BASE}/app?as=owner`);

  // Seam 1+2: served under /app, identity round-tripped to an authenticated whoami.
  await expect(page.getByTestId("identity")).toHaveText("owner");
  await expect(page.getByTestId("whoami-handle")).toHaveText("owner");

  const before = Number(await page.getByTestId("event-count").textContent());

  // Seam 3: post a live event from outside the page (architect → owner) and watch it
  // arrive over the fetch-stream, no reload.
  const res = await fetch(`${BASE}/v1/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", "X-Participant": "arch" },
    body: JSON.stringify({ ticket_id: EPIC, to: "owner", kind: "note", text: "spike ping from arch" }),
  });
  expect(res.ok).toBeTruthy();

  await expect(page.getByTestId("event-count")).not.toHaveText(String(before), { timeout: 5_000 });
  await expect(page.getByTestId("event-item").last()).toBeVisible();
});
