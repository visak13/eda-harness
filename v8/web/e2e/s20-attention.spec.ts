import fs from "node:fs";
import path from "node:path";
import { expect, test, BASE, type Page } from "./fixtures";
import { seedDecisions, type G2Fixture } from "./g2.seed";

// S20 attention trail (design-e963c656f5 §4.18, owner ruling m-8d061abf32; criterion c-bb46b01331): on a
// private board seeded through /v1, follow the dot from the rail to each item and screenshot every hop —
// rail → Epics row (sorted first, marked, reason) → the epic's openers (Actions, Design, Work) → the section
// (Answer a decision) → the Work pop-up's ticket row → the story's Files & evidence → the ruling drawer;
// the question highlighted on its thread; Library → Topics → the topic row → the question; the Waiting on
// you popover (the Needs you page is gone); and clearing (an answered item's dots leave). Shots land in
// e2e/evidence/s20-attention/ (git-ignored): the walk's evidence for qa and the owner.
test.use({ boardFile: "s20-attention" });

const OUT = path.join("e2e", "evidence", "s20-attention");
let n = 0;
async function shot(page: Page, name: string) {
  fs.mkdirSync(OUT, { recursive: true });
  await page.waitForTimeout(250); // settle transitions before the capture
  await page.screenshot({ path: path.join(OUT, `${String(++n).padStart(2, "0")}-${name}.png`) });
}
const dot = (scope: ReturnType<Page["getByTestId"]>) => scope.locator("[data-attention-dot]").first();
const label = (count: number) => `needs your attention: ${count}`;

async function call(method: string, p: string, body: unknown, headers: Record<string, string>): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
  const j = (await r.json()) as { ok: boolean; value?: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${p} → ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

test.describe("S20 attention trail walk", () => {
  let fx: G2Fixture;
  let topic: string;
  let topicQ: string;
  test.beforeAll(async () => {
    fx = await seedDecisions();
    // a scope gate on the epic: answered from Actions → Answer a decision
    await call("POST", `/v1/gates/${fx.epic}/scope/open`, { note: "cut the export from v1?" }, { "X-Participant": "arch" });
    // a Library topic whose sme asks the owner a question
    topic = (await call("POST", "/v1/topics", { title: "Rendering choices", tags: ["rendering"] }, { "X-Participant": "owner" })).topic.id;
    await call("POST", "/v1/participants", { type: "agent", role: "sme", handle: `sme-${topic}`, id: `sme.${topic}` }, { "X-Admin": process.env.EDP8_ADMIN_TOKEN ?? "t" }).catch(() => {});
    topicQ = (await call("POST", "/v1/messages", { ticket_id: topic, to: "owner", kind: "question", text: "Canvas or SVG for the chart?" }, { "X-Participant": `sme.${topic}` })).id;
  });

  test("rail → Epics → epic openers → section → Work row → ticket → item, topics, popover, clearing", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });

    // 1. rail + Epics list: counts on Epics and Library, the epic sorted first, marked, with its reason
    await page.goto(`${BASE()}/ui/epics?as=owner`);
    const epicsLink = page.getByRole("link", { name: /^Epics/ });
    await expect(dot(epicsLink)).toHaveAttribute("aria-label", label(4));
    await expect(dot(page.getByRole("link", { name: /^Library/ }))).toHaveAttribute("aria-label", label(1));
    const row = page.getByTestId("epic-row").first();
    await expect(row).toContainText(fx.words);
    await expect(row).toHaveAttribute("data-attention", "true");
    await expect(row.getByTestId("attention-reason")).toHaveText("Waiting on you: 1 sign-off, 1 question, 1 design sign-off, 1 scope decision");
    await shot(page, "rail-and-epics-list");

    // 2. Waiting on you popover (the Needs you page is gone; /me redirects here)
    await page.getByTestId("waiting-open").click();
    const pop = page.getByRole("dialog", { name: "Waiting on you" });
    await expect(pop.getByTestId("waiting-row")).toHaveCount(2);
    await shot(page, "waiting-on-you-popover");
    await page.keyboard.press("Escape");
    await page.goto(`${BASE()}/ui/me?as=owner`);
    await expect(page).toHaveURL(/\/ui\/epics/);

    // 3. inside the epic: Actions, Design and Work carry the dot; Files does not
    await page.goto(`${BASE()}/ui/epic/${fx.epic}?as=owner`);
    await expect(dot(page.getByTestId("actions-open"))).toHaveAttribute("aria-label", label(1));
    await expect(dot(page.getByTestId("work-design"))).toHaveAttribute("aria-label", label(1));
    await expect(dot(page.getByTestId("work-work"))).toHaveAttribute("aria-label", label(2));
    await expect(page.getByTestId("work-files").locator("[data-attention-dot]")).toHaveCount(0);
    await shot(page, "epic-openers");

    // 4. Actions → its section (Answer a decision) → the gate, marked
    await page.getByTestId("actions-open").click();
    await expect(page.getByTestId("action-answer-decision")).toHaveAttribute("data-attention", "true");
    await shot(page, "actions-menu-section");
    await page.getByTestId("action-answer-decision").click();
    await expect(page.locator('[data-attention="true"]').filter({ has: page.getByTestId("gate-form") })).toHaveCount(1);
    await shot(page, "decision-drawer-gate");
    await page.keyboard.press("Escape");

    // 5. Work pop-up: the story row carries the dot
    await page.getByTestId("work-work").click();
    const storyRow = page.locator(`[id="row-${fx.story}"]`);
    await expect(storyRow).toHaveAttribute("data-attention", "true");
    await expect(dot(storyRow)).toHaveAttribute("aria-label", label(2));
    await shot(page, "work-popup-ticket-row");
    await page.keyboard.press("Escape");

    // 6. the story: Files & evidence (dot) → the evidence row (dot) → the ruling drawer
    await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=owner`);
    await expect(dot(page.getByTestId("work-files"))).toHaveAttribute("aria-label", label(1));
    await shot(page, "ticket-files-opener");
    await page.getByTestId("work-files").click();
    const evidence = page.locator(`li[id="${fx.doc}"]`);
    await expect(evidence).toHaveAttribute("data-attention", "true");
    await shot(page, "files-evidence-row");
    await evidence.getByRole("button").first().click();
    await expect(page.getByTestId("ruling-grid")).toBeVisible();
    await shot(page, "ruling-drawer-item");
    await page.keyboard.press("Escape");

    // 7. the question on its thread: highlighted from its link, marked, dotted
    await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=owner#${fx.question}`);
    const q = page.locator(`li[id="${fx.question}"]`);
    await expect(q).toHaveAttribute("data-highlight", "true");
    await expect(dot(q)).toHaveAttribute("aria-label", label(1));
    await shot(page, "question-highlighted-on-thread");

    // 8. Library → Topics (dot) → the topic row (reason) → the question in its thread
    await page.goto(`${BASE()}/ui/library/topics?as=owner`);
    await expect(dot(page.getByRole("link", { name: /^Topics/ }))).toHaveAttribute("aria-label", label(1));
    const topicRow = page.getByTestId("topic-row").filter({ hasText: "Rendering choices" });
    await expect(topicRow).toHaveAttribute("data-attention", "true");
    await expect(topicRow.getByTestId("attention-reason")).toHaveText("Waiting on you: 1 question");
    await shot(page, "library-topics-row");
    await page.goto(`${BASE()}/ui/library/topics/${topic}?as=owner#${topicQ}`);
    const tq = page.locator(`li[id="${topicQ}"]`);
    await expect(tq).toHaveAttribute("data-attention", "true");
    await expect(tq).toHaveAttribute("data-highlight", "true");
    await shot(page, "topic-question-highlighted");

    // 9. clearing: rule the sign-off and answer the scope gate — their dots leave; the rest stay
    await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=owner`);
    await page.getByTestId("work-files").click();
    await page.locator(`li[id="${fx.doc}"]`).getByRole("button").first().click();
    await page.getByTestId("note").fill("Reads well; approved.");
    await page.getByTestId("approve").click();
    await expect(page.getByTestId("ruling-grid")).toHaveCount(0);
    await expect(page.getByTestId("work-files").locator("[data-attention-dot]")).toHaveCount(0);
    await page.goto(`${BASE()}/ui/epic/${fx.epic}?as=owner`);
    await page.getByTestId("actions-open").click();
    await page.getByTestId("action-answer-decision").click();
    const form = page.getByTestId("gate-form").filter({ hasText: /scope/i });
    await form.getByTestId("gate-answer").fill("Cut it from v1.");
    await form.getByTestId("gate-submit").click();
    await expect.poll(async () => ((await call("GET", `/v1/gates/${fx.epic}`, undefined, { "X-Participant": "owner" }).catch(() => [])) ?? [])
      .filter((g: any) => (g.gate ?? g.data?.gate) === "scope").length).toBe(0);
    await page.goto(`${BASE()}/ui/epics?as=owner`);
    await expect(dot(page.getByRole("link", { name: /^Epics/ }))).toHaveAttribute("aria-label", label(2));
    await expect(page.getByTestId("epic-row").first().getByTestId("attention-reason")).toHaveText("Waiting on you: 1 question, 1 design sign-off");
    await shot(page, "cleared-after-answers");
  });
});
