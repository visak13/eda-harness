import { expect, test, BASE } from "./fixtures";
import { seedDecisions, type G2Fixture } from "./g2.seed";
import { get, openDecisions } from "./g2-owner-loop.helpers";

test.use({ boardFile: "g2-replies" }); // one fresh board per spec file (fixtures.ts)

// Human defect #3 (widened, ruling m-d20bbb7305, 2026-09-10): every conversation the human starts
// from the UI and every reply to it must be findable — the reply attached to their message on the
// ticket thread, and on the owner's Decisions page under "Replies to you". The verification the
// human asked for, verbatim: send as owner from the UI, reply as an agent via the API, then find
// the reply from the owner's Decisions page.
test.describe("owner conversations: a reply comes back to the owner", () => {
  let fx: G2Fixture;
  test.beforeAll(async () => {
    fx = await seedDecisions();
  });

  test("owner sends from the ticket page, the seat replies over /v1, the owner finds it on Decisions and in the thread", async ({ page }) => {
    // 1. Owner sends from the UI, addressed to the live engineer seat.
    await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=owner`);
    await expect(page.getByTestId("thread")).toBeVisible();
    const people: any[] = (await get("/v1/me/people")) ?? [];
    const handle: string = people.find((p) => p.id === fx.liveSeat)?.handle ?? fx.liveSeat;
    await page.getByTestId("to-picker").selectOption(handle);
    const ask = `Owner asks from the UI: is the featured card ready? ${Date.now()}`;
    await page.getByTestId("composer-text").fill(ask);
    await page.getByTestId("composer-send").click();
    await expect(page.getByTestId("sent-note")).toBeVisible();

    let mine: any;
    await expect
      .poll(async () => {
        const msgs = (await get(`/v1/messages?ticket_id=${fx.story}`)) ?? [];
        mine = msgs.find((m: any) => m.text === ask && m.created_by === "owner");
        return Boolean(mine);
      })
      .toBe(true);
    expect([fx.liveSeat, handle]).toContain(mine.to); // the board keeps the handle the picker sent

    // 2. The seat answers over the API, attached to the owner's message.
    const answer = `Yes — the featured card is live on ${Date.now()}`;
    const r = await fetch(`${BASE()}/v1/messages`, {
      method: "POST",
      headers: { "content-type": "application/json", "X-Participant": fx.liveSeat },
      body: JSON.stringify({ ticket_id: fx.story, to: "owner", kind: "answer", text: answer, reply_to: mine.id }),
    });
    expect(r.ok).toBe(true);

    // 3. The owner finds the reply on Decisions, quoting their own words.
    await openDecisions(page);
    const replies = page.getByTestId("replies");
    await expect(replies).toContainText(answer);
    await expect(replies).toContainText("you wrote:");
    await expect(replies).toContainText(ask.slice(0, 60));

    // 4. …and on the ticket thread, attached to the message it answers.
    await replies.getByRole("link", { name: "Decisions home story" }).first().click();
    await expect(page.getByTestId("thread")).toBeVisible();
    const replyRow = page.getByTestId("thread-message").filter({ hasText: answer });
    await expect(replyRow).toHaveCount(1);
    await expect(replyRow.getByTestId("reply-quote")).toContainText("replying to you");
    await expect(replyRow.getByTestId("reply-quote")).toContainText(ask.slice(0, 60));
  });
});
