import { expect, test } from "./fixtures";
import { seedDecisions } from "./g2.seed";
import { get, openDecisions } from "./g2-owner-loop.helpers";

test.use({ boardFile: "g2-owner-loop-needswork" }); // one fresh board per spec file (fixtures.ts)

// The G2 owner loop, proven end-to-end through the real Folio shell served at /ui/me:
//   part 1 (c-da073491bd): the seeded Sign-offs/Questions/Gates counts, Seats-now with the alive
//     engineer seat + "Last work update unavailable", Epic pulse status + waiting_reason, and an
//     inline question reply that leaves the tab and sets reply_to on the wire.
//   part 2 (c-6c014b0c72): "Review evidence" → drawer with the frozen report + verbatim criterion;
//     Approve-with-note closes it, the item leaves Sign-offs and lands under Resolved, verdict=pass;
//     a Needs-work run yields verdict=fail and a "[sign-off fail] …" message to the assignee.
//   gate (c-4941d309f1): answering the seeded design_signoff gate drops the Gates count to 0 and
//     GET /v1/gates/{epic} is empty.
// Each test seeds its own scenario via /v1 so they are order-independent.
// This file: part 2, Needs-work-with-note (one seed → one featured sign-off).

test.describe("owner loop — part 2 (ruling drawer)", () => {
  test("Needs-work-with-note yields verdict=fail and a '[sign-off fail] …' message to the assignee", async ({ page }) => {
    const fx = await seedDecisions();
    await openDecisions(page);

    await page.getByTestId("review-evidence").click();
    await expect(page.getByTestId("drawer-panel")).toBeVisible();
    await page.getByTestId("note").fill("The cold-start proof is missing.");
    await page.getByTestId("needs-work").click();

    await expect(page.getByTestId("drawer-panel")).toHaveCount(0);
    await expect
      .poll(async () => {
        const crits = await get(`/v1/criteria?ticket_id=${fx.story}`);
        return (crits ?? []).find((c: any) => c.id === fx.signoffCriterion)?.verdict;
      })
      .toBe("fail");
    // The assignee gets a durable '[sign-off fail] …' note on the ticket thread.
    await expect
      .poll(async () => {
        const msgs = await get(`/v1/messages?ticket_id=${fx.story}`);
        return (msgs ?? []).some((m: any) => typeof m.text === "string" && m.text.startsWith("[sign-off fail]"));
      })
      .toBe(true);
  });
});
