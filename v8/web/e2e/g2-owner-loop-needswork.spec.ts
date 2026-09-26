import { expect, test } from "./fixtures";
import { seedDecisions } from "./g2.seed";
import { get, openSignoff } from "./g2-owner-loop.helpers";

test.use({ boardFile: "g2-owner-loop-needswork" }); // one fresh board per spec file (fixtures.ts)

// The G2 owner loop on the S20 attention trail (design-e963c656f5 §4.18): a Needs-work ruling from the
// ruling drawer (story → Files & evidence → evidence row) yields verdict=fail and a "[sign-off fail] …"
// message to the assignee. Approve lives in g2-owner-loop-ruling.spec.ts.

test.describe("owner loop — part 2 (ruling drawer)", () => {
  test("Needs-work-with-note yields verdict=fail and a '[sign-off fail] …' message to the assignee", async ({ page }) => {
    const fx = await seedDecisions();
    await openSignoff(page, fx);

    await page.getByTestId("note").fill("The cold-start proof is missing.");
    await page.getByTestId("needs-work").click();

    await expect(page.getByTestId("ruling-grid")).toHaveCount(0);
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
