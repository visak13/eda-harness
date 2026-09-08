import { expect, type Page, BASE } from "./fixtures";

// Shared by the g2-owner-loop*.spec.ts files. Each of those files runs on ITS OWN board (fixtures.ts):
// the owner-loop assertions are absolute counts ("Sign-offs 1", "Gates 0") and "the featured
// sign-off", which only hold when the file's seed is the only scenario on the board — a second
// seedDecisions() on the same board makes the featured item another test's (acceptance finding,
// 2026-09-08: part 2 approved part 1's sign-off and the count stayed at 1).
const owner = { "X-Participant": "owner" };

export async function get(path: string): Promise<any> {
  const r = await fetch(`${BASE()}${path}`, { headers: owner });
  const j = (await r.json()) as { ok: boolean; value?: any };
  return j.value;
}

export async function openDecisions(page: Page) {
  await page.goto(`${BASE()}/ui/me?as=owner`);
  await expect(page.getByTestId("decisions")).toBeVisible();
}
