import { expect, type Page, BASE } from "./fixtures";
import type { G2Fixture } from "./g2.seed";

// Shared by the g2-owner-loop*.spec.ts files. Each of those files runs on ITS OWN board (fixtures.ts):
// the owner-loop assertions are absolute ("the Files opener's one dot", "no gates left"), which only
// hold when the file's seed is the only scenario on the board.
// S20 (design-e963c656f5 §4.18): the Decisions page is gone; the owner loop walks the attention trail —
// a sign-off ends at the story's Files & evidence row → the ruling drawer; a design_signoff gate at the
// epic's Design opener → the design review; any other gate at Actions → Answer a decision.
const owner = { "X-Participant": "owner" };

export async function get(path: string): Promise<any> {
  const r = await fetch(`${BASE()}${path}`, { headers: owner });
  const j = (await r.json()) as { ok: boolean; value?: any };
  return j.value;
}

/** The dot on a control, by its aria-label ("needs your attention: N"); null when the control has none. */
export const dotOn = (page: Page, testid: string) => page.getByTestId(testid).locator("[data-attention-dot]");

/** The owner's landing: the Epics list with the rail. */
export async function openEpics(page: Page) {
  await page.goto(`${BASE()}/ui/epics?as=owner`);
  await expect(page.getByTestId("epic-list")).toBeVisible();
}

/** Story page → Files & evidence (dotted) → the evidence row (dotted) → the ruling drawer. */
export async function openSignoff(page: Page, fx: G2Fixture) {
  await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=owner`);
  await expect(dotOn(page, "work-files")).toHaveAttribute("aria-label", "needs your attention: 1");
  await page.getByTestId("work-files").click();
  const row = page.locator(`li[id="${fx.doc}"]`);
  await expect(row).toHaveAttribute("data-attention", "true");
  await row.getByRole("button").first().click();
  await expect(page.getByTestId("ruling-grid")).toBeVisible();
}
