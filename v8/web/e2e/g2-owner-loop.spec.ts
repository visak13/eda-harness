import { expect, test } from "@playwright/test";
import { seedDecisions, type G2Fixture } from "./g2.seed";

// The G2 owner loop, proven end-to-end through the real Folio shell served at /app/me:
//   part 1 (c-da073491bd): the seeded Sign-offs/Questions/Gates counts, Seats-now with the alive
//     engineer seat + "Last work update unavailable", Epic pulse status + waiting_reason, and an
//     inline question reply that leaves the tab and sets reply_to on the wire.
//   part 2 (c-6c014b0c72): "Review evidence" → drawer with the frozen report + verbatim criterion;
//     Approve-with-note closes it, the item leaves Sign-offs and lands under Resolved, verdict=pass;
//     a Needs-work run yields verdict=fail and a "[sign-off fail] …" message to the assignee.
//   gate (c-4941d309f1): answering the seeded design_signoff gate drops the Gates count to 0 and
//     GET /v1/gates/{epic} is empty.
// Each test seeds its own scenario via /v1 so they are order-independent.
const BASE = process.env.EDP8_E2E_BASE!;
const owner = { "X-Participant": "owner" };

async function get(path: string): Promise<any> {
  const r = await fetch(`${BASE}${path}`, { headers: owner });
  const j = (await r.json()) as { ok: boolean; value?: any };
  return j.value;
}

async function openDecisions(page: import("@playwright/test").Page) {
  await page.goto(`${BASE}/app/me?as=owner`);
  await expect(page.getByTestId("decisions")).toBeVisible();
}

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

test.describe("owner loop — part 2 (ruling drawer)", () => {
  test("Review evidence → Approve-with-note lands the item under Resolved, verdict=pass", async ({ page }) => {
    const fx = await seedDecisions();
    await openDecisions(page);

    await page.getByTestId("review-evidence").click();
    const drawer = page.getByTestId("drawer-panel");
    await expect(drawer).toBeVisible();
    // The frozen report body and the verbatim owner criterion.
    await expect(page.getByTestId("ruling-evidence")).toContainText("Decisions report");
    await expect(page.getByTestId("ruling-pane")).toContainText("The report proves the Decisions surface end-to-end.");

    await page.getByTestId("note").fill("Reads well; approved.");
    await page.getByTestId("approve").click();

    // Drawer closes; the sign-off leaves the queue.
    await expect(page.getByTestId("drawer-panel")).toHaveCount(0);
    await expect(page.getByRole("tab", { name: /Sign-offs/ })).toContainText("0");

    // It shows under Resolved, and the wire verdict is pass.
    await page.getByRole("tab", { name: /Resolved/ }).click();
    await expect(page.getByTestId("resolved")).toContainText(fx.story);
    await expect
      .poll(async () => {
        const crits = await get(`/v1/criteria?ticket_id=${fx.story}`);
        return (crits ?? []).find((c: any) => c.id === fx.signoffCriterion)?.verdict;
      })
      .toBe("pass");
  });

  test("Needs-work-with-note yields verdict=fail and a '[sign-off fail] …' message to the assignee", async ({ page }) => {
    const fx = await seedDecisions();
    await openDecisions(page);

    await page.getByTestId("review-evidence").click();
    await expect(page.getByTestId("drawer-panel")).toBeVisible();
    await page.getByTestId("note").fill("The cold-start proof is missing.");
    await page.getByTestId("needs-work").click();

    await expect(page.getByTestId("drawer-panel")).toHaveCount(0);
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

test.describe("owner loop — gate answer", () => {
  test("answering the design_signoff gate drops the count to 0 and empties GET /v1/gates", async ({ page }) => {
    const fx = await seedDecisions();
    await openDecisions(page);

    await page.getByRole("tab", { name: /Gates/ }).click();
    await expect(page.getByTestId("gate-kind")).toContainText(fx.gate);
    await page.getByTestId("gate-answer").fill("Approved — proceed.");
    await page.getByTestId("gate-submit").click();

    await expect(page.getByRole("tab", { name: /Gates/ })).toContainText("0");
    await expect.poll(async () => (await get(`/v1/gates/${fx.epic}`))?.length ?? 0).toBe(0);
  });
});
