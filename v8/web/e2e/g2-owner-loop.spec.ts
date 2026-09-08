import { expect, test } from "./fixtures";
import { seedDecisions, type G2Fixture } from "./g2.seed";
import { get, openDecisions } from "./g2-owner-loop.helpers";

test.use({ boardFile: "g2-owner-loop" }); // one fresh board per spec file (fixtures.ts)

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
// This file: part 1. Part 2 and the gate answer live in g2-owner-loop-ruling.spec.ts / g2-owner-loop-gate.spec.ts, each on its own board.

test.describe("owner loop — part 1 (waiting-on-you + conversations)", () => {
  let fx: G2Fixture;
  test.beforeAll(async () => {
    fx = await seedDecisions();
  });

  test("counts, Seats-now, Epic pulse, and an inline reply that sets reply_to", async ({ page }) => {
    await openDecisions(page);

    // Tab counts equal the seeded decisions payload: 1 / 1 / 1.
    await expect(page.getByRole("tab", { name: /Sign-offs/ })).toContainText("1");
    await expect(page.getByRole("tab", { name: /Questions/ })).toContainText("1");
    await expect(page.getByRole("tab", { name: /Gates/ })).toContainText("1");

    // Seats-now: the alive engineer seat, its ticket, and the honest presence caveats.
    const seats = page.getByTestId("seats-now");
    await expect(seats).toContainText(fx.story);
    await expect(seats).toContainText("Last work update unavailable");
    await expect(seats).toContainText("Shell alive ≠ work progressing");

    // Epic pulse: the seeded epic's status word and its waiting_reason (open gate).
    const pulse = page.getByTestId("epic-pulse");
    await expect(pulse).toContainText(fx.words);

    // Inline reply to the question → it leaves the Questions tab, and the wire carries reply_to.
    await page.getByRole("tab", { name: /Questions/ }).click();
    await expect(page.getByTestId("question")).toBeVisible();
    await page.getByTestId("reply").click();
    await page.getByTestId("composer-text").fill("Use the Folio theme for the featured card.");
    await page.getByTestId("composer-send").click();
    await expect(page.getByTestId("question")).toHaveCount(0);

    await expect
      .poll(async () => {
        const msgs = await get(`/v1/messages?ticket_id=${fx.story}`);
        return (msgs ?? []).some((m: any) => m.reply_to === fx.question);
      })
      .toBe(true);
  });
});
