// e0cec S16 c-d37f54463d (the `$` artifact picker) and c-320d037cb8 (the topic page as a ticket page). One-off evidence
// spec on a private board and a privately built SPA: run it alone, never the full suite. Shots go to
// e2e/evidence/s16-refs-topic/ (git-ignored run output; the evidence doc cites the uploaded copies).
import fs from "node:fs";
import path from "node:path";
import { BASE, EPIC, expect, test } from "./fixtures";

test.use({ boardFile: "s16-refs-topic", viewport: { width: 1440, height: 900 } });
test.describe.configure({ mode: "serial", timeout: 120_000 });
const out = path.resolve("e2e/evidence/s16-refs-topic");
const ADMIN = process.env.EDP8_ADMIN_TOKEN ?? "t";
const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(32)]);

async function call(method: string, route: string, who: string, body?: unknown, admin = false): Promise<any> {
  const h: Record<string, string> = { "content-type": "application/json", "X-Participant": who };
  if (admin) h["X-Admin"] = ADMIN;
  const r = await fetch(BASE() + route, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${route} ${JSON.stringify(j)}`);
  return j.value;
}
async function upload(name: string, ticket: string): Promise<string> {
  const form = new FormData();
  form.append("file", new Blob([PNG], { type: "image/png" }), name);
  const r = await fetch(`${BASE()}/v1/artifacts/upload`, { method: "POST", headers: { "X-Participant": "arch" }, body: form });
  const id = (await r.json()).value.id as string;
  await call("POST", "/v1/artifacts/finalize", "arch", { artifact_ids: [id], ticket_id: ticket });
  return id;
}

let story1 = "", picked = "", topic = "";

test.beforeAll(async () => {
  fs.mkdirSync(out, { recursive: true });
  const story = async (epic: string, title: string) => (await call("POST", "/v1/tickets", "arch", { kind: "story", work_type: "feature", title, parent_id: epic })).id as string;
  story1 = await story(EPIC(), "Spike board screens");
  const story2 = await story(EPIC(), "Spike benchmarks");
  const other = (await call("POST", "/v1/tickets", "owner", { kind: "epic", work_type: "feature", title: "Harbour dashboard" })).id as string;
  const otherStory = await story(other, "Harbour wireframes");
  picked = await upload("spike-board-shot.png", story1);
  await call("POST", "/v1/artifacts", "arch", { form: "url", uri: "https://example.test/spike/report", note: "Spike report page", ticket_id: story1 });
  await call("POST", "/v1/artifacts", "arch", { form: "url", uri: "https://example.test/spike/bench", note: "Spike benchmark notes", ticket_id: story2 });
  await upload("harbour-wireframe.png", otherStory);
  await call("POST", "/v1/artifacts", "arch", { form: "url", uri: "https://example.test/harbour/report", note: "Harbour report page", ticket_id: otherStory });

  // a Library topic with a criterion that has evidence waiting on the owner, an open gate
  const t = await call("POST", "/v1/topics", "owner", { title: "Python testing", seed_url: "https://docs.pytest.org/en/stable/", tags: ["python", "testing"] });
  topic = t.topic.id as string;
  const sme = `sme.${topic}`;
  const crit = await call("POST", "/v1/criteria", "owner", { ticket_id: topic, text: "The sme's notes cover pytest fixtures and parametrisation", check: "look", checked_by: "owner", override_reason: "a topic has no architect" });
  const doc = await call("POST", "/v1/docs", sme, { doc_type: "report", title: "Fixture notes", body_md: "# Fixture notes\n\nScoped fixtures, factories, parametrize.\n", scope: topic, status: "proposed" });
  await call("PATCH", `/v1/criteria/${crit.id}`, sme, { evidence_ref: doc.id });
  await call("POST", `/v1/gates/${topic}/demo/open`, sme, { note: "Is the sme on track with the fixtures notes?" });
});

test("C1: `$` lists the epic's artifacts first, then every other epic's, each row naming its epic; the pick renders as an artifact link", async ({ page }) => {
  await page.goto(`${BASE()}/ui/ticket/${story1}?as=owner`);
  const ta = page.getByTestId("composer-text");
  await ta.click();
  await page.keyboard.type("evidence in $art"); // the trigger is `$` + a letter; the art- prefix lists every artifact
  const menu = page.getByTestId("refs-menu");
  await expect(menu).toBeVisible();
  const rows = menu.locator("[data-ref^=art-]");
  await expect(rows).toHaveCount(5);
  const groups = await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-group")));
  expect(groups).toEqual(["scope", "scope", "scope", "board", "board"]);
  await expect(menu.locator(`[data-ref="${picked}"] [data-testid=ref-epic]`)).toContainText("Spike epic");
  await expect(menu.locator('[data-group="board"] [data-testid=ref-epic]').first()).toContainText("Harbour dashboard");
  await page.screenshot({ path: path.join(out, "1-picker-open.png") });

  const bench = await menu.locator("[data-ref^=art-]", { hasText: "Spike benchmark notes" }).getAttribute("data-ref");
  for (let i = 0; i < 6 && (await menu.locator('[aria-selected="true"]').getAttribute("data-ref")) !== bench; i++) await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(ta).toHaveValue(/evidence in \$art-[0-9a-f]{10} \(Spike benchmark notes\) $/);
  await expect(menu).toHaveCount(0);
  await page.screenshot({ path: path.join(out, "2-reference-in-composer.png") });

  await ta.press("Control+Enter");
  const link = page.getByRole("link", { name: "artifact · Spike benchmark notes" }).first();
  await expect(link).toHaveText("artifact · Spike benchmark notes");
  await expect(link).toHaveAttribute("href", /\/ui\/artifact\/art-[0-9a-f]{10}$/);
  await page.screenshot({ path: path.join(out, "3-sent-message-artifact-link.png") });
});

test("C2: the owner's topic page is the ticket page (criteria + sign-off, gates, files, work drawer, lifecycle) plus the topic panel", async ({ page }) => {
  await page.goto(`${BASE()}/ui/library/topics/${topic}?as=owner`);
  const header = page.getByTestId("work-header");
  await expect(header.getByRole("link", { name: "Library" })).toBeVisible();
  await expect(page.getByTestId("topic-source")).toBeVisible();
  await expect(page.getByTestId("topic-seed")).toHaveAttribute("href", "https://docs.pytest.org/en/stable/");
  await expect(page.getByTestId("topic-allowlist")).toContainText("docs.pytest.org");
  await expect(page.getByTestId("topic-experts")).toBeVisible(); // adding one needs a token-mode board; the vitest covers the list
  await page.getByTestId("actions-open").click();
  await expect(page.getByTestId("action-answer-decision")).toBeVisible();
  await expect(page.getByTestId("action-add-criterion")).toBeVisible();
  await expect(page.getByTestId("action-change-status")).toBeVisible();
  await page.screenshot({ path: path.join(out, "4-topic-page-actions.png") });
  await page.keyboard.press("Escape");

  await page.goto(`${BASE()}/ui/library/topics/${topic}?as=owner&view=work`);
  const work = page.getByTestId("ticket-work");
  await expect(work).toBeVisible();
  await expect(work.getByText("The sme's notes cover pytest fixtures and parametrisation")).toBeVisible();
  await expect(work.getByText("Process")).toBeVisible();
  await expect(work.getByText(/Linked documents/)).toBeVisible();
  await page.screenshot({ path: path.join(out, "5-work-drawer.png") });

  await page.goto(`${BASE()}/ui/library/topics/${topic}?as=owner&view=files`);
  await expect(page.getByText("Fixture notes").first()).toBeVisible();
  await page.screenshot({ path: path.join(out, "6-files-and-evidence.png") });
});
