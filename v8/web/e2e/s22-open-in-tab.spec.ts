import fs from "node:fs";
import path from "node:path";
import { test, expect, BASE, type Page } from "./fixtures";

// S22 (s-8ebd40da22) c-e2b8c53a06 / task t-f5d27a6f2e — owner m-94117833e0: "any open in new tab
// action launches a new tab but I am asked to login again." The board is in TOKEN mode here
// (tokens.json names the owner), exactly like the fleet board: a tab without X-Token gets 401 on
// /v1/whoami and renders the identity panel. The owner's first tab carries the token once
// (?token=, stripped to sessionStorage); every tab opened from it must land logged in with no
// token in its address.
test.use({ boardFile: "s22-open-in-tab" });
const TOKEN = "s22-owner-secret";
const tokensPath = () => path.join(process.env.EDP8_E2E_HOME ?? "", "tokens.json");

async function call(method: string, p: string, data: unknown, actor: string) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", "X-Participant": actor }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${p} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

let seeded: { epic: string; other: string; doc: string } | null = null;
test.beforeAll(async () => {
  // Seed in trusted mode, THEN switch the board to token mode (it re-reads tokens.json by mtime).
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Tab session epic" }, "owner")).id as string;
  const other = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Linked epic" }, "owner")).id as string;
  const doc = (await call("POST", "/v1/docs", { doc_type: "design", title: "Tab session design", scope: epic, body_md: "# Tab session design\n\n## 1. One\n\nText." }, "arch")).id as string;
  await call("POST", "/v1/links", { from_id: epic, to_id: doc, relation: "designed_by" }, "arch");
  await call("PATCH", `/v1/tickets/${epic}`, { design_ref: doc }, "arch");
  await call("POST", "/v1/messages", { ticket_id: epic, kind: "note", text: `see ${BASE()}/ui/epic/${other}?as=owner` }, "arch");
  seeded = { epic, other, doc };
  fs.writeFileSync(tokensPath(), JSON.stringify({ owner: TOKEN }), "utf8");
});
test.afterAll(() => fs.rmSync(tokensPath(), { force: true }));

// The shell paints before /v1/whoami answers, so "no identity panel yet" proves nothing: every tab's
// identity probe status is recorded (context-wide, so a new tab's first request is never missed) and
// the tab counts as logged in only once its probe answered 200 and the panel is absent.
const probes = new WeakMap<Page, number[]>();
test.beforeEach(({ context }) => {
  context.on("response", (r) => {
    if (!new URL(r.url()).pathname.endsWith("/v1/whoami")) return;
    const pg = r.frame().page();
    probes.set(pg, [...(probes.get(pg) ?? []), r.status()]);
  });
});
async function loggedIn(page: Page) {
  await expect.poll(() => probes.get(page)?.length ?? 0, { timeout: 15_000 }).toBeGreaterThan(0);
  expect(probes.get(page), "every /v1/whoami from this tab answered 200").toEqual(probes.get(page)!.map(() => 200));
  await expect(page.getByTestId("identity-panel")).toHaveCount(0);
  expect(page.url()).not.toContain("token");
}

test("first tab: ?token= logs in and leaves the address bar", async ({ page }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner&token=${TOKEN}`);
  await loggedIn(page);
});

test("a tab without the session is asked to log in (the token mode is real)", async ({ page }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await expect(page.getByTestId("identity-panel")).toBeVisible();
  expect(probes.get(page)).toContain(401);
});

test("Ctrl-click on a message link opens a new tab that is logged in", async ({ page, context }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner&token=${TOKEN}`);
  await loggedIn(page);
  const link = page.getByTestId("message-md").getByRole("link", { name: new RegExp(seeded!.other) }).first();
  await expect(link).toBeVisible();
  expect(await link.getAttribute("href")).not.toContain("token");
  const [tab] = await Promise.all([context.waitForEvent("page"), link.click({ modifiers: ["Control"] })]);
  await loggedIn(tab);
  await expect(tab.getByText("Linked epic").first()).toBeVisible();
});

test("the design viewer's Open in tab lands logged in", async ({ page, context }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner&token=${TOKEN}`);
  await loggedIn(page);
  await page.getByTestId("work-design").click();
  const dialog = page.getByRole("dialog").filter({ hasText: "Tab session design" });
  await expect(dialog).toBeVisible();
  const [tab] = await Promise.all([context.waitForEvent("page"), dialog.getByRole("link", { name: /Open in tab/ }).click()]);
  await loggedIn(tab);
  await expect(tab.getByText("Tab session design").first()).toBeVisible();
});

test("a copied link pasted into a fresh tab of the same browser lands logged in", async ({ page, context }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner&token=${TOKEN}`);
  await loggedIn(page);
  const tab = await context.newPage(); // no opener at all: the address typed / pasted by hand
  await tab.goto(`/ui/epic/${seeded!.other}?as=owner`);
  await loggedIn(tab);
});
