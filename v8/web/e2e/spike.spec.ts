import { expect, test, BASE, EPIC } from "./fixtures";

test.use({ boardFile: "spike" }); // one fresh board per spec file (fixtures.ts)

// Walking-skeleton seams, now proven through the real Folio shell (was the S1 skeleton
// page; G1b replaced main.tsx). Seam 1+2: the SPA is served under /ui and identity
// round-trips to an authenticated /v1/whoami rendered in the sidebar. Seam 3: a live feed
// event posted from outside the page arrives over the fetch-stream, no reload, and renders
// (S19: the "N new" pill that held refresh under a draft is retired — drafts never hold it).

test("shell renders identity + whoami and receives a live feed event within 5s", async ({ page }) => {
  await page.goto(`${BASE()}/ui/me?as=owner`);

  await expect(page.getByTestId("identity")).toHaveText("owner");
  await expect(page.getByTestId("whoami-handle")).toHaveText("owner");

  // Seam 3: post a note (architect → owner) while a conversation draft is open and watch it arrive
  // over the feed within 5 s — the draft does not hold the refresh, and it survives it.
  await page.getByRole("button", { name: "New conversation" }).click();
  await page.getByTestId("composer-text").fill("draft in progress — do not refresh under me");
  const res = await fetch(`${BASE()}/v1/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", "X-Participant": "arch" },
    body: JSON.stringify({ ticket_id: EPIC(), to: "owner", kind: "note", text: "spike ping from arch" }),
  });
  expect(res.ok).toBeTruthy();

  await expect(page.getByText("spike ping from arch").first()).toBeVisible({ timeout: 5_000 });
  await expect(page.getByTestId("composer-text")).toHaveValue("draft in progress — do not refresh under me");
});
