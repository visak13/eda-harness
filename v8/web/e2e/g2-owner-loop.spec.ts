import { expect, test } from "./fixtures";
import { BASE } from "./fixtures";
import { seedDecisions, type G2Fixture } from "./g2.seed";
import { dotOn, get, openEpics } from "./g2-owner-loop.helpers";

test.use({ boardFile: "g2-owner-loop" }); // one fresh board per spec file (fixtures.ts)

// The G2 owner loop on the S20 attention trail (the Decisions page is gone, design-e963c656f5 §4.18; each
// former panel's new home per architect m-e972777a3d):
//   part 1 (c-da073491bd): what waits on the owner is on the Epics row (sorted first, marked, one-line
//     reason — the former Epic pulse), the rail counts it, the Waiting-on-you popover links to it; Seats
//     now lives on the Seats page; a question is answered inline on its own thread (highlighted from its
//     #m- link) with reply_to on the wire, and its mark clears.
//   part 2 (ruling drawer): g2-owner-loop-ruling / -needswork. Gates: g2-owner-loop-gate, s22-gate-draft.

test.describe("owner loop — part 1 (the trail + conversations)", () => {
  let fx: G2Fixture;
  test.beforeAll(async () => {
    fx = await seedDecisions();
  });

  test("Epics row + rail + popover, Seats page, and an inline reply that sets reply_to", async ({ page }) => {
    await openEpics(page);

    // The epic waiting on the owner sorts first, marked, with its one-line reason.
    const row = page.getByTestId("epic-row").first();
    await expect(row).toContainText(fx.words);
    await expect(row).toHaveAttribute("data-attention", "true");
    const reason = row.getByTestId("attention-reason");
    await expect(reason).toHaveText("Waiting on you: 1 sign-off, 1 question, 1 design sign-off"); // a dead seat's question is collapsed (§18.2 inbox rule)
    await expect(row.locator("[data-attention-dot]")).toHaveAttribute("aria-label", "needs your attention: 3");
    // The rail counts it (v34: no "Waiting on you" popover any more; the Epics count and row are the way in).
    await expect(page.getByRole("link", { name: /^Epics/ }).locator("[data-attention-dot]")).toHaveAttribute("aria-label", "needs your attention: 3");
    await expect(page.getByTestId("waiting-open")).toHaveCount(0);

    // Seats now → the Seats page: the alive engineer seat, its ticket, and the honest presence caveats.
    await page.goto(`${BASE()}/ui/seats?as=owner`);
    await expect(page.getByText(fx.story).first()).toBeVisible();
    await expect(page.getByText("Last work update unavailable").first()).toBeVisible();
    await expect(page.getByText(/Shell alive ≠ work progressing/).first()).toBeVisible();

    // The question on its thread: highlighted from its #m- link, marked; the inline reply carries reply_to.
    await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=owner#${fx.question}`);
    const q = page.locator(`li[id="${fx.question}"]`);
    await expect(q).toHaveAttribute("data-highlight", "true");
    await expect(q).toHaveAttribute("data-attention", "true");
    await q.getByTestId("thread-reply").click();
    await page.getByTestId("composer-text").fill("Use the Folio theme for the featured card.");
    await page.getByTestId("composer-send").click();
    await expect
      .poll(async () => {
        const msgs = await get(`/v1/messages?ticket_id=${fx.story}`);
        return (msgs ?? []).some((m: any) => m.reply_to === fx.question);
      })
      .toBe(true);
    // Clearing: answered, so the question leaves the attention list and its mark goes.
    await expect(q).not.toHaveAttribute("data-attention", "true");
    await expect(dotOn(page, "work-files")).toHaveAttribute("aria-label", "needs your attention: 1"); // the sign-off still waits
  });
});
