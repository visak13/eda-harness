import { expect, test } from "./fixtures";
import { seedDecisions } from "./g2.seed";
import { dotOn, get, openSignoff } from "./g2-owner-loop.helpers";

test.use({ boardFile: "g2-owner-loop-ruling" }); // one fresh board per spec file (fixtures.ts)

// The G2 owner loop on the S20 attention trail (the Decisions page is gone, design-e963c656f5 §4.18):
//   part 2 (c-6c014b0c72): story → Files & evidence → the evidence row → the ruling drawer with the frozen
//     report + verbatim criterion; Approve-with-note closes it, verdict=pass, and the trail's dot clears.
//   Needs work: g2-owner-loop-needswork.spec.ts. Gate answers: g2-owner-loop-gate.spec.ts.
// Each file seeds its own scenario via /v1 on its own board.

test.describe("owner loop — part 2 (ruling drawer)", () => {
  test("Files & evidence → evidence row → Approve-with-note: verdict=pass and the dot clears", async ({ page }) => {
    const fx = await seedDecisions();
    await openSignoff(page, fx);

    // The frozen report body and the verbatim owner criterion.
    await expect(page.getByTestId("ruling-evidence")).toContainText("Decisions report");
    await expect(page.getByTestId("ruling-pane")).toContainText("The report proves the Decisions surface end-to-end.");

    await page.getByTestId("note").fill("Reads well; approved.");
    await page.getByTestId("approve").click();

    // The ruling drawer closes and the wire verdict is pass.
    await expect(page.getByTestId("ruling-grid")).toHaveCount(0);
    await expect
      .poll(async () => {
        const crits = await get(`/v1/criteria?ticket_id=${fx.story}`);
        return (crits ?? []).find((c: any) => c.id === fx.signoffCriterion)?.verdict;
      })
      .toBe("pass");
    // Clearing: the sign-off left the attention list, so the Files opener's dot is gone.
    await expect(dotOn(page, "work-files")).toHaveCount(0);
  });
});
