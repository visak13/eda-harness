import fs from "node:fs";
import path from "node:path";
import { test, expect, BASE } from "./fixtures";
import { seedEpic, type G3aFixture } from "./g3a.seed";

// S12 sweep slice A (note-8f0629190d #3 #8 #9 #10 #12 #13) against a private spawned board in token mode.
const OWNER_TOKEN = "s12a-owner-token";
const tokensPath = () => path.join(process.env.EDP8_E2E_HOME ?? "", "tokens.json");
const ownerH = { "X-Participant": "owner", "X-Token": OWNER_TOKEN, "content-type": "application/json" };
const SHOTS = path.join(process.cwd(), "e2e", "evidence", "s12-sweep-a");
let fx: G3aFixture;

test.use({ boardFile: "s12-sweep-a" });
test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  fx = await seedEpic();
  fs.writeFileSync(tokensPath(), JSON.stringify({ owner: OWNER_TOKEN, agents: {} }), "utf8");
});
test.afterAll(() => fs.rmSync(tokensPath(), { force: true }));

const go = (page: import("@playwright/test").Page, tab: string) => page.goto(`${BASE()}/ui/admin?tab=${tab}&as=owner&token=${OWNER_TOKEN}`);
const remoteOn = async (page: import("@playwright/test").Page, delayMs = 0) => page.route("**/v1/admin/tailnet", async (route) => {
  try {
    const res = await route.fetch();
    const body = await res.json();
    body.value.public_mode = true;
    body.value.public_url = "https://host.tail.ts.net";
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    await route.fulfill({ response: res, json: body });
  } catch { /* the test ended with a request in flight */ }
});

test("#3 the server refuses a bad handle (400) and the form shows an inline error", async ({ page }) => {
  for (const bad of ["Bad Name!", "../etc", "x".repeat(70)]) {
    const r = await fetch(`${BASE()}/v1/admin/teammates`, { method: "POST", headers: ownerH, body: JSON.stringify({ handle: bad }) });
    expect(r.status, bad).toBe(400);
  }
  await remoteOn(page);
  await go(page, "teammates");
  await page.getByTestId("invite-handle").fill("Bad Name!");
  await expect(page.getByTestId("invite-handle-error")).toBeVisible();
  await expect(page.getByTestId("invite-submit")).toBeDisabled();
  await page.getByTestId("invite").screenshot({ path: path.join(SHOTS, "03-invalid-handle.png") });
});

test("#9 no 'Invite is off' notice while Remote access is still loading", async ({ page }) => {
  await remoteOn(page, 2500);
  await go(page, "teammates");
  await page.getByTestId("invite-handle").fill("alex");
  await page.waitForTimeout(600);
  await expect(page.getByTestId("invite-off-reason")).toHaveCount(0);
  await expect(page.getByTestId("how-inviting-remote-off")).toHaveCount(0);
  await page.getByTestId("admin-teammates").screenshot({ path: path.join(SHOTS, "09-invite-loading.png") });
  await expect(page.getByTestId("invite-submit")).toBeEnabled({ timeout: 8000 });
  await expect(page.getByTestId("invite-off-reason")).toHaveCount(0);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("#10 Remote access counts its setup steps and the link opens in a new tab", async ({ page }) => {
  await remoteOn(page);
  await go(page, "remote");
  await expect(page.getByTestId("remote-progress")).toContainText("setup steps done (step 1 only explains)");
  await expect(page.getByRole("link", { name: "https://host.tail.ts.net" })).toHaveAttribute("target", "_blank");
  await page.getByTestId("remote-progress").screenshot({ path: path.join(SHOTS, "10-remote-progress.png") });
});

test("#8 Seat harnesses say Checking while the probe runs", async ({ page }) => {
  await page.route("**/v1/admin/harnesses*", async (route) => { await new Promise((r) => setTimeout(r, 2500)); await route.continue(); });
  await go(page, "integrations");
  const card = page.getByTestId("integration-harnesses");
  await expect(card.getByTestId("harnesses-status")).toContainText("Checking");
  await expect(card.getByTestId("harnesses-checking")).toBeVisible();
  await card.screenshot({ path: path.join(SHOTS, "08-harnesses-checking.png") });
  await expect(card.getByTestId("harnesses-checking")).toHaveCount(0, { timeout: 15000 });
  await card.screenshot({ path: path.join(SHOTS, "08-harnesses-loaded.png") });
});

test("#12 closing Models with unsaved edits asks before discarding", async ({ page }) => {
  await page.goto(`${BASE()}/ui/epic/${fx.epic}?as=owner&token=${OWNER_TOKEN}`);
  await page.getByTestId("actions-open").click();
  await page.getByTestId("action-models").click();
  const dialog = page.getByTestId("models-dialog");
  await expect(dialog).toBeVisible();
  const effort = dialog.locator("select[data-testid$='-effort-engineer'], select[data-testid='models-effort-engineer']").first();
  const current = await effort.inputValue();
  await effort.selectOption(current === "low" ? "medium" : "low");
  const messages: string[] = [];
  page.once("dialog", (d) => { messages.push(d.message()); void d.dismiss(); });
  await page.getByRole("button", { name: "Close" }).click();
  await expect.poll(() => messages.length).toBe(1);
  expect(messages[0]).toMatch(/unsaved/i);
  await expect(dialog).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, "12-models-kept-open.png") });
  page.once("dialog", (d) => { void d.accept(); });
  await page.getByRole("button", { name: "Close" }).click();
  await expect(dialog).toHaveCount(0);
});

test("#13 1M windows are marked and the doctor window warning shows", async ({ page }) => {
  await page.route("**/v1/admin/models", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    const body = await res.json();
    body.value.window_problems = [{ model: "claude-opus-5-5", code: "compact_above_window", what: "claude-opus-5-5 compacts at 350000 tokens but its real window is 200000", fix: "lower auto_compact below 200000, or give it a 1M context_window" }];
    return route.fulfill({ response: res, json: body });
  });
  await go(page, "models");
  await expect(page.getByTestId("window-problem-claude-opus-5-5")).toBeVisible();
  await expect(page.getByTestId("model-row-claude-opus-5-5")).toContainText("(1M)");
  await page.screenshot({ path: path.join(SHOTS, "13-models-1m-and-warning.png"), fullPage: true });
});
