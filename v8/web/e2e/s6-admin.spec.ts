import fs from "node:fs";
import path from "node:path";
import { test, expect, BASE } from "./fixtures";

// S6 (s-e6b4fa59d5; design-e963c656f5 §4.8): the Admin console, /ui/join and /ui/setup against a real
// spawned board. Admin routes need an admin human's X-Participant + X-Token, so this file's board runs in
// token mode (a tokens.json under its private EDP8_HOME, removed after): `owner` is the init human (admin),
// `tokuser` a credentialled human who is not.
const OWNER_TOKEN = "s6-owner-token";
const OTHER_TOKEN = "s6-tokuser-token";
const tokensPath = () => path.join(process.env.EDP8_E2E_HOME ?? "", "tokens.json");
const ownerH = { "X-Participant": "owner", "X-Token": OWNER_TOKEN, "content-type": "application/json" };

test.use({ boardFile: "s6-admin" });
test.beforeAll(() => fs.writeFileSync(tokensPath(), JSON.stringify({ owner: OWNER_TOKEN, tokuser: OTHER_TOKEN, agents: {} }), "utf8"));
test.afterAll(() => fs.rmSync(tokensPath(), { force: true }));

test("an admin sees Admin in the rail and six tabs; Settings renders every registry key", async ({ page }) => {
  await page.goto(`${BASE()}/ui/epics?as=owner&token=${OWNER_TOKEN}`);
  await page.getByTestId("nav-admin").click();
  await expect(page.getByTestId("admin-page")).toBeVisible();
  for (const name of ["Services", "Settings", "Teammates", "Remote access", "Integrations", "Seats & models"]) {
    await expect(page.getByRole("tab", { name })).toBeVisible();
  }
  await expect(page.getByTestId("service-board")).toBeVisible();
  await expect(page.getByTestId("capacity")).toBeVisible();

  const listing = await (await fetch(`${BASE()}/v1/admin/settings`, { headers: ownerH })).json();
  const rows = (listing.value.groups as { settings: { tier?: string }[] }[]).flatMap((g) => g.settings);
  const basic = rows.filter((s) => s.tier === "basic").length;
  await page.getByRole("tab", { name: "Settings" }).click();
  // t-5dd0cc18ea: the basic tier shows by default; "Show advanced" adds the rest of the registry
  await expect(page.getByTestId("setting-field")).toHaveCount(basic);
  expect(basic).toBeGreaterThan(0);
  expect(basic).toBeLessThan(rows.length);
  await page.locator("label", { has: page.getByTestId("settings-show-advanced") }).click();
  await expect(page.getByTestId("settings-show-advanced")).toBeChecked();
  await expect(page.getByTestId("setting-field")).toHaveCount(rows.length);
  expect(rows.length).toBeGreaterThan(50); // internal registry keys never reach the listing (97 at 0.9.0)
  // env-set keys are read-only on this board too (EDP8_PORT is set by the harness)
  await expect(page.getByTestId("setting-board.port-input")).toBeDisabled();
});

test("a non-admin human gets no rail entry and a refusal on /ui/admin", async ({ page }) => {
  await page.goto(`${BASE()}/ui/admin?as=tokuser&token=${OTHER_TOKEN}`);
  await expect(page.getByTestId("admin-forbidden")).toBeVisible();
  await expect(page.getByTestId("nav-admin")).toHaveCount(0);
  await expect(page.getByRole("tablist")).toHaveCount(0);
});

test("invite → /ui/join in another browser context lands signed in; revoke → 401", async ({ page, browser }) => {
  // This board is not in public mode, so Invite is off: the link would only work over the tailnet.
  await page.goto(`${BASE()}/ui/admin?tab=teammates&as=owner&token=${OWNER_TOKEN}`);
  await page.getByTestId("invite-handle").fill("carol");
  await expect(page.getByTestId("invite-submit")).toBeDisabled();
  await expect(page.getByTestId("invite-off-reason")).toBeVisible();
  await expect(page.getByTestId("how-inviting-remote-off")).toBeVisible();

  // Remote access on (public_mode is the SPA's gate; the invite route itself does not need a tailnet), then invite.
  await page.route("**/v1/admin/tailnet", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.value.public_mode = true;
    await route.fulfill({ response: res, json: body });
  });
  await page.reload();
  await expect(page.getByTestId("invite-off-reason")).toHaveCount(0);
  await page.getByTestId("invite-handle").fill("carol");
  await page.getByTestId("invite-submit").click();
  const link = (await page.getByTestId("invite-link").innerText()).match(/https?:\/\/\S+/)![0];
  await expect(page.getByTestId("invite-vscode-link")).toContainText("vscode://edp.edp-code/signin");

  const other = await browser.newContext();
  const carol = await other.newPage();
  await carol.goto(link);
  await expect(carol.getByTestId("join-ok")).toContainText("You are signed in as carol");
  expect(carol.url()).not.toContain("code=");
  const token = await carol.evaluate(() => sessionStorage.getItem("edp8.token"));
  const who = () => fetch(`${BASE()}/v1/whoami`, { headers: { "X-Participant": "carol", "X-Token": token ?? "" } }).then((r) => r.status);
  expect(await who()).toBe(200);

  // the same link again is refused in the board's words
  const again = await (await browser.newContext()).newPage();
  await again.goto(link);
  await expect(again.getByTestId("join-error")).toContainText("already used or has expired");

  await page.reload();
  await page.getByTestId("teammate-carol-revoke").click();
  await expect.poll(who).toBe(401);
  await other.close();
});

test("/ui/setup: a signed-in admin walks from sign-in through tools to the harness step", async ({ page }) => {
  await page.goto(`${BASE()}/ui/setup?as=owner&token=${OWNER_TOKEN}`);
  await expect(page.getByTestId("setup-signed-in")).toContainText("owner");
  await page.getByTestId("setup-next").click();
  // the tools (prerequisites) step sits between sign-in and harnesses
  await expect(page.getByTestId("setup-tools")).toBeVisible();
  await page.getByTestId("setup-next").click();
  await expect(page.getByTestId("harness-selection")).toBeVisible();
});
