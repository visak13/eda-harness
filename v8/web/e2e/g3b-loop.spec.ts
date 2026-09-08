import { expect, test, type Page } from "@playwright/test";
import { seedLoopStory, type G3bLoopFixture } from "./g3b.seed";

// G3b S16 — close one full loop from the pages, no shell (c-f449ac02be). As the owner, on a seeded
// story's page: open a gate, SPAWN an engineer seat from the page, walk ready → in_progress →
// in_review with the status control, record a verdict on the criterion, and mark it done. After each
// step the board (GET /v1) shows the change and the process strip marks the new stage.
//
// POOL-LESS SPAWN DOUBLE (named per the criterion): the real pool is not attached in e2e, so the
// browser-side routes below stand in for it — GET /v1/pool/capabilities is forced to report
// spawn:true (so the page offers "Spawn a seat"), and POST /v1/sessions/spawn returns ok without a
// live shell. Every OTHER call (status changes, the verdict, gate open) hits the real board
// unchanged, so the loop's state transitions are genuinely the board's.
const BASE = process.env.EDP8_E2E_BASE!;
const owner = { "X-Participant": "owner" };

async function get(path: string): Promise<any> {
  const r = await fetch(`${BASE}${path}`, { headers: owner });
  return ((await r.json()) as { value?: any }).value;
}
const statusOf = (s: string) => get(`/v1/tickets/${s}`).then((t) => t?.status);

async function installSpawnDouble(page: Page): Promise<{ spawned: () => boolean }> {
  let didSpawn = false;
  await page.route("**/v1/pool/capabilities", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, value: { resume_parked: true, resume_closed: false, park: true, spawn: true }, hint: "" }),
    });
  });
  await page.route("**/v1/sessions/spawn", async (route) => {
    didSpawn = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, value: { ok: true, session: "e2e-double" }, hint: "pool-less e2e double" }),
    });
  });
  return { spawned: () => didSpawn };
}

test.describe("S16 — one full loop from the pages, no shell", () => {
  let fx: G3bLoopFixture;
  test.beforeAll(async () => {
    fx = await seedLoopStory();
  });

  test("open gate → spawn → in_progress → in_review → verdict → done, each mirrored by the board", async ({ page }) => {
    const dbl = await installSpawnDouble(page);
    await page.goto(`${BASE}/app/ticket/${fx.story}?as=owner`);

    // the process strip opens on the seeded stage
    await expect(page.getByTestId("process-strip")).toHaveAttribute("data-status", "ready");
    expect(await statusOf(fx.story)).toBe("ready");

    // 1) open a gate from the page → the board records an open gate on the story
    await page.getByTestId("gate-open-kind").selectOption("demo");
    await page.getByTestId("gate-open").getByRole("button", { name: /Open the .* gate/ }).click();
    await expect.poll(async () => ((await get(`/v1/gates/${fx.story}`)) ?? []).length).toBeGreaterThan(0);

    // 2) spawn an engineer seat from the page (pool-less double) → the spawn call fires
    await page.getByTestId("spawn-seat").click();
    await expect.poll(() => dbl.spawned()).toBe(true);

    // 3) ready → in_progress via the status control → board + strip agree
    await page.getByTestId("status-move-in_progress").click();
    await expect.poll(() => statusOf(fx.story)).toBe("in_progress");
    await expect(page.getByTestId("process-strip")).toHaveAttribute("data-status", "in_progress");

    // 4) in_progress → in_review (owner is the assignee; the criterion carries evidence)
    await page.getByTestId("status-move-in_review").click();
    await expect.poll(() => statusOf(fx.story)).toBe("in_review");

    // 5) record a verdict on the criterion from the ticket page (ruling pane) → board shows pass
    await page.getByTestId("approve").click();
    await expect
      .poll(async () => ((await get(`/v1/criteria?ticket_id=${fx.story}`)) ?? []).find((c: any) => c.id === fx.criterion)?.verdict)
      .toBe("pass");

    // 6) in_review → done now that every criterion passed; the strip marks the final stage
    await page.getByTestId("status-move-done").click();
    await expect.poll(() => statusOf(fx.story)).toBe("done");
    await expect(page.getByTestId("process-strip")).toHaveAttribute("data-status", "done");
    await expect(page.getByTestId("stage-current")).toContainText("Done");
  });
});
