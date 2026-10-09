// e0cec S12 sweep slice B (note-8f0629190d): #1 the topic page's thread and composer are the ticket page's, #4 the
// Library lessons view, #5 a pain's commit links only when the remote has it. One-off evidence spec on a private board
// and a privately built SPA: run it alone. Shots go to e2e/evidence/s12-sweep-b/ (git-ignored run output).
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { BASE, EPIC, expect, test } from "./fixtures";

// the e2e board is not a dev board, so name the checkout whose remote-tracking refs answer "is this commit pushed?"
test.use({ boardFile: "s12-sweep-b", boardEnv: { EDP8_REPO: path.resolve("..", "..") }, viewport: { width: 1440, height: 900 } });
test.describe.configure({ mode: "serial", timeout: 120_000 });
const out = path.resolve("e2e/evidence/s12-sweep-b");
const ADMIN = process.env.EDP8_ADMIN_TOKEN ?? "t";

async function call(method: string, route: string, who: string, body?: unknown): Promise<any> {
  const h: Record<string, string> = { "content-type": "application/json", "X-Participant": who, "X-Admin": ADMIN };
  const r = await fetch(BASE() + route, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${route} ${JSON.stringify(j)}`);
  return j.value;
}

let topic = "";

test.beforeAll(async () => {
  fs.mkdirSync(out, { recursive: true });
  const t = await call("POST", "/v1/topics", "owner", { title: "Python testing", seed_url: "https://docs.pytest.org/en/stable/", tags: ["python"] });
  topic = t.topic.id as string;
  const story = (await call("POST", "/v1/tickets", "arch", { kind: "story", work_type: "feature", title: "Sweep spike", parent_id: EPIC() })).id as string;
  await call("POST", "/v1/artifacts", "arch", { form: "url", uri: "https://example.test/spike/report", note: "Spike report page", ticket_id: story });
  await call("POST", "/v1/messages", `sme.${topic}`, { ticket_id: topic, to: "owner", kind: "question", text: "Fixtures or factories for the examples?" });
  const keep = await call("POST", "/v1/lessons", "owner", { domain: "operations", topic: "restart", text: "restart the board by pid, never by image name" });
  const old = await call("POST", "/v1/lessons", "owner", { domain: "blender", topic: "bake", text: "bake the modifiers before export", scope_kind: "project", project: "blender" });
  await call("POST", `/v1/lessons/${old.id}/retire`, "owner", { reason: "superseded by the exporter" });
  void keep;
});

test("#1 the owner's topic page carries the ticket page's thread and composer features", async ({ page }) => {
  await page.goto(`${BASE()}/ui/library/topics/${topic}?as=owner`);
  await expect(page.getByTestId("conversation")).toBeVisible();
  await expect(page.getByTestId("topic-thread")).toHaveCount(0);
  await expect(page.getByTestId("order-toggle")).toBeVisible();
  await expect(page.getByTestId("composer-attach")).toBeVisible();
  await expect(page.getByTestId("kind-picker")).toBeVisible();
  await expect(page.getByTestId("thread-message").filter({ hasText: "Fixtures or factories" })).toBeVisible();
  const ta = page.getByTestId("composer-text");
  await ta.click();
  await page.keyboard.type("see $art");
  await expect(page.getByTestId("refs-menu").locator("[data-ref^=art-]")).not.toHaveCount(0);
  await page.screenshot({ path: path.join(out, "1-topic-thread-composer-dollar-search.png") });
  await page.keyboard.press("Escape");
  await page.getByTestId("thread-message").first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, "1-topic-thread-messages-and-reply.png") });
});

test("#4 lessons show their scope, open a detail view, and the Retired filter lists a retired lesson", async ({ page }) => {
  await page.goto(`${BASE()}/ui/library/knowledge?as=owner`);
  await expect(page.getByTestId("knowledge-lesson")).toHaveCount(2);
  await expect(page.getByTestId("lesson-scope-tag").first()).toBeVisible();
  await page.getByTestId("knowledge-status-filter").selectOption("retired");
  await expect(page.getByTestId("knowledge-lesson")).toHaveCount(1);
  await page.getByTestId("knowledge-lesson-open").click();
  await expect(page.getByTestId("lesson-reason")).toContainText("superseded by the exporter");
  await expect(page.getByTestId("lesson-retire")).toHaveCount(0);
  await page.screenshot({ path: path.join(out, "4-retired-lesson-detail.png") });
  await page.getByTestId("knowledge-status-filter").selectOption("active");
  await page.getByTestId("knowledge-lesson-open").click();
  await expect(page.getByTestId("lesson-detail")).toContainText("framework epics");
  await page.screenshot({ path: path.join(out, "4-active-lesson-owner-retire.png") });
  page.once("dialog", (d) => void d.accept());
  await page.getByTestId("lesson-retire-reason").fill("stale");
  await page.getByTestId("lesson-retire").click();
  await expect(page.getByTestId("lesson-detail").getByTestId("lesson-reason")).toContainText("stale");
});

test("#5 a pain's commit links only when the remote has it", async ({ page }) => {
  const pushed = execFileSync("git", ["rev-list", "-1", "--remotes"], { encoding: "utf8" }).trim();
  const mk = async (symptom: string, commit: string) => {
    const p = await call("POST", "/v1/pains", "owner", { severity: "low", area: "tools", symptom, expected: "works", evidence: "e2e" });
    await call("POST", `/v1/pains/${p.id}/resolve`, "owner", { status: "fixed", commit });
  };
  await mk("fixed and pushed", pushed);
  await mk("fixed but unpushed", "0123abc4567");
  await page.goto(`${BASE()}/ui/library/pains?as=owner&status=fixed`);
  await expect(page.getByTestId("pain-row")).toHaveCount(2);
  await expect(page.getByRole("link", { name: `commit ${pushed}` })).toBeVisible();
  await expect(page.getByRole("link", { name: /commit 0123abc4567/ })).toHaveCount(0);
  await expect(page.getByTestId("pain-row").filter({ hasText: "unpushed" }).locator("code")).toHaveText("0123abc456");
  await page.screenshot({ path: path.join(out, "5-pains-commit-link-vs-plain-sha.png") });
});
