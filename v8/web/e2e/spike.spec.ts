import { expect, test } from "@playwright/test";

// Walking-skeleton seams, now proven through the real Folio shell (was the S1 skeleton
// page; G1b replaced main.tsx). Seam 1+2: the SPA is served under /app and identity
// round-trips to an authenticated /v1/whoami rendered in the sidebar. Seam 3: a live feed
// event posted from outside the page arrives over the fetch-stream, no reload, and raises
// the shell's "N new" pill.
const BASE = process.env.EDP8_E2E_BASE!;
const EPIC = process.env.EDP8_E2E_EPIC!;

test("shell renders identity + whoami and receives a live feed event within 5s", async ({ page }) => {
  await page.goto(`${BASE}/app/me?as=owner`);

  await expect(page.getByTestId("identity")).toHaveText("owner");
  await expect(page.getByTestId("whoami-handle")).toHaveText("owner");

  // Seam 3: post a note (architect → owner) and watch the live pill appear over SSE.
  const res = await fetch(`${BASE}/v1/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", "X-Participant": "arch" },
    body: JSON.stringify({ ticket_id: EPIC, to: "owner", kind: "note", text: "spike ping from arch" }),
  });
  expect(res.ok).toBeTruthy();

  await expect(page.getByTestId("live-new")).toBeVisible({ timeout: 5_000 });
  await expect(page.getByTestId("live-new")).toContainText("new");
});
