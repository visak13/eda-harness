import { expect, test } from "./fixtures";
import { BASE } from "./fixtures";
import { seedDecisions } from "./g2.seed";
import { dotOn, get } from "./g2-owner-loop.helpers";

test.use({ boardFile: "g2-owner-loop-gate" }); // one fresh board per spec file (fixtures.ts)

// The G2 owner loop on the S20 attention trail (design-e963c656f5 §4.18): the seeded design_signoff gate
// waits behind the epic's Design opener (its dot); the design review's Approve answers it, GET /v1/gates
// empties, and the dot clears. (Other gates end at Actions → Answer a decision: s22-gate-draft.spec.ts.)

test.describe("owner loop — gate answer", () => {
  test("Design opener (dotted) → Approve design empties GET /v1/gates and clears the dot", async ({ page }) => {
    const fx = await seedDecisions();
    await page.goto(`${BASE()}/ui/epic/${fx.epic}?as=owner`);
    await expect(dotOn(page, "work-design")).toHaveAttribute("aria-label", "needs your attention: 1");
    await expect(page.getByTestId("work-design")).toHaveAttribute("data-attention", "true");

    await page.getByTestId("work-design").click();
    await page.getByRole("button", { name: "Approve design" }).click();

    await expect.poll(async () => (await get(`/v1/gates/${fx.epic}`))?.length ?? 0).toBe(0);
    await page.keyboard.press("Escape");
    await expect(dotOn(page, "work-design")).toHaveCount(0);
  });
});
