import { expect, test } from "@playwright/test";
import { seedEpic, type G3aFixture } from "./g3a.seed";

// Criterion c-5985a92696: the deep-link shapes the slack bridge + legacy UI produce land on the
// right Folio surface with identity attached, and the legacy query-string filters survive the
// redirect. The slack bridge (src/edp8/slack_bridge.py:83) builds exactly two shapes —
// `{base}/ui/ticket/{ticket}?as={handle}` (a message on a ticket) and `{base}/ui/me?as={handle}`
// (no ticket) — and identity (src/auth/identity.ts) reads ?as → sessionStorage → an X-Participant
// header on every /v1 request (the feed is fetch, not EventSource, so it too carries the header).
const BASE = process.env.EDP8_E2E_BASE!;
const ADMIN = () => process.env.EDP8_ADMIN_TOKEN ?? "t";

let fx: G3aFixture;

test.beforeAll(async () => {
  fx = await seedEpic();
  // Seed the deep-link recipient so the destination page can actually read its data as `alice`
  // (the X-Participant header assertion below fires regardless of whether alice exists — the
  // identity adapter attaches it unconditionally — but a known participant keeps the heading real).
  await fetch(`${BASE}/v1/participants`, {
    method: "POST",
    headers: { "content-type": "application/json", "X-Admin": ADMIN() },
    body: JSON.stringify({ type: "human", role: "owner", handle: "alice", id: "alice" }),
  }).catch(() => {});
});

/** Attach a request listener that records the X-Participant of the FIRST /v1 call, before nav. */
function captureFirstV1Participant(page: import("@playwright/test").Page): { value(): string | undefined } {
  let seen: string | undefined;
  let captured = false;
  page.on("request", (req) => {
    if (!captured && req.url().includes("/v1/")) {
      captured = true;
      // Playwright lowercases header names.
      seen = req.headers()["x-participant"];
    }
  });
  return { value: () => seen };
}

test.describe("slack-bridge deep links carry identity", () => {
  test("/ui/ticket/{id}?as=alice opens the ticket and the first /v1 call is X-Participant: alice", async ({ page }) => {
    const first = captureFirstV1Participant(page);
    await page.goto(`${BASE}/ui/ticket/${fx.story}?as=alice`);

    // Destination: the ticket page (its status chip renders).
    await expect(page.getByTestId("status-chip")).toBeVisible();
    expect(new URL(page.url()).pathname).toContain(`/ticket/${fx.story}`);

    // The first board request went out as alice.
    await expect.poll(() => first.value()).toBe("alice");
  });

  test("/ui/me?as=alice opens Decisions and the first /v1 call is X-Participant: alice", async ({ page }) => {
    const first = captureFirstV1Participant(page);
    await page.goto(`${BASE}/ui/me?as=alice`);

    await expect(page.getByTestId("decisions")).toBeVisible();
    expect(new URL(page.url()).pathname).toContain("/me");

    await expect.poll(() => first.value()).toBe("alice");
  });
});

test.describe("legacy paths redirect into Folio with the filter intact", () => {
  test("/ui/tickets?status=in_review → /ui/library/tickets with the status filter applied", async ({ page }) => {
    await page.goto(`${BASE}/ui/tickets?status=in_review&as=owner`);

    // The router shim (main.tsx RedirectTo) redirects to Library, preserving the whole query string.
    await expect.poll(() => new URL(page.url()).pathname).toContain("/library/tickets");
    expect(new URL(page.url()).searchParams.get("status")).toBe("in_review");
    expect(new URL(page.url()).searchParams.get("as")).toBe("owner");

    // The Library tickets filter binds to the query string, so the status select shows in_review.
    await expect(page.getByTestId("ticket-filters").getByLabel("status")).toHaveValue("in_review");
  });

  test("/ui/epic/{id}?as=owner opens the epic destination directly (no redirect)", async ({ page }) => {
    // /ui/epic/{id} is already a Folio destination — the deep link opens the epic page in place.
    await page.goto(`${BASE}/ui/epic/${fx.epic}?as=owner`);
    await expect.poll(() => new URL(page.url()).pathname).toContain(`/epic/${fx.epic}`);
    await expect(page.getByRole("tablist")).toBeVisible();
    await expect(page.locator("main h1")).toBeVisible();
  });
});

// A wrong token with a tokens.json present → the legacy server-side "identity panel". The Folio SPA
// does NOT implement this: identity (src/auth/identity.ts) strips ?token into sessionStorage and
// sends it as X-Token; there is no in-SPA token-validation panel (grep for tokens.json / identity
// panel across web/src returns nothing). The behaviour lives in the legacy server UI, unreachable
// from the SPA — so this leg is left for qa to exercise against the server, not the SPA. FLAGGED.
test.fixme("wrong token + tokens.json → identity panel (legacy server UI, not reachable in-SPA)", () => {
  // Unbuilt in the Folio SPA — the identity panel is a legacy server-rendered surface. qa: exercise
  // against the board's server UI with a tokens.json fixture, or drop this leg if the SPA is canon.
});
