import { expect, test } from "./fixtures";
import { seedDecisions } from "./g2.seed";
import { get, openDecisions } from "./g2-owner-loop.helpers";

test.use({ boardFile: "g2-owner-loop-gate" }); // one fresh board per spec file (fixtures.ts)

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
// This file: the gate answer (one seed → one open gate).

test.describe("owner loop — gate answer", () => {
  test("answering the design_signoff gate drops the count to 0 and empties GET /v1/gates", async ({ page }) => {
    const fx = await seedDecisions();
    await openDecisions(page);

    await page.getByRole("tab", { name: /Gates/ }).click();
    await expect(page.getByTestId("gate-kind")).toContainText("Design sign-off"); // the human label for fx.gate ("design_signoff"), not the raw enum
    await page.getByTestId("gate-answer").fill("Approved — proceed.");
    await page.getByTestId("gate-submit").click();

    await expect(page.getByRole("tab", { name: /Gates/ })).toContainText("0");
    await expect.poll(async () => (await get(`/v1/gates/${fx.epic}`))?.length ?? 0).toBe(0);
  });
});
