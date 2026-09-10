import { expect, test, BASE } from "./fixtures";
import { seedQaLoopStory, type G3bQaLoopFixture } from "./g3b.seed";

test.use({ boardFile: "g3b-loop-qa" }); // one fresh board per spec file (fixtures.ts)

// Companion to g3b-loop (adversary finding #16, 2026-09-10): the same loop with the board's DERIVED
// checker. The owner-override fixture proved the owner path only; here the criterion is qa-checked
// (§24.1), the engineer hands the story to review over /v1, the qa seat rules it FROM THE UI and
// the board advances the story to done on its own.
const owner = { "X-Participant": "owner" };

async function get(path: string, who: Record<string, string> = owner): Promise<any> {
  const r = await fetch(`${BASE()}${path}`, { headers: who });
  return ((await r.json()) as { value?: any }).value;
}
async function patch(path: string, body: unknown, who: string): Promise<void> {
  await fetch(`${BASE()}${path}`, {
    method: "PATCH",
    headers: { "content-type": "application/json", "X-Participant": who },
    body: JSON.stringify(body),
  });
}
const statusOf = (s: string) => get(`/v1/tickets/${s}`).then((t) => t?.status);

test.describe("S16 companion — the derived qa checker closes the loop from the pages", () => {
  let fx: G3bQaLoopFixture;
  test.beforeAll(async () => {
    fx = await seedQaLoopStory();
  });

  test("ready → in_progress → in_review (engineer) → qa rules from the UI → done (board)", async ({ page }) => {
    expect(await statusOf(fx.story)).toBe("ready");
    await patch(`/v1/tickets/${fx.story}`, { status: "in_progress" }, "owner"); // the owner may move any ticket
    await expect.poll(() => statusOf(fx.story)).toBe("in_progress");
    await patch(`/v1/tickets/${fx.story}`, { status: "in_review" }, fx.engineer); // only the assignee hands off
    await expect.poll(() => statusOf(fx.story)).toBe("in_review");

    // The qa seat opens the ticket: the pending criterion offers a ruling to ITS checker.
    await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=${encodeURIComponent(fx.qa)}`);
    await expect(page.getByTestId("process-strip")).toHaveAttribute("data-status", "in_review");
    await page.getByTestId("approve").click();
    await expect
      .poll(async () => ((await get(`/v1/criteria?ticket_id=${fx.story}`)) ?? []).find((c: any) => c.id === fx.criterion)?.verdict)
      .toBe("pass");
    const events = (await get(`/v1/events?subject_id=${fx.story}`)) ?? [];
    const ruled = events.find((e: any) => e.kind === "criterion_checked" && e.data?.criterion === fx.criterion);
    expect(ruled?.data?.by).toBe(fx.qa); // the verdict is the qa seat's, not the owner's

    // §24.1 auto-advance: every criterion passed → the board moves the story to done; the page mirrors it.
    await expect.poll(() => statusOf(fx.story)).toBe("done");
    await expect(page.getByTestId("process-strip")).toHaveAttribute("data-status", "done");
    await expect(page.getByTestId("stage-current")).toContainText("Done");

    // The owner-side UI hand-off is visible too: the criterion reads passed on the owner's view.
    await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=owner`);
    await expect(page.getByTestId("process-strip")).toHaveAttribute("data-status", "done");
  });
});
