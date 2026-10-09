// e0cec S5 look evidence (c-cefaeb51a3): screenshots of the guest UI, the epic People panel and the invite dialog,
// taken against a PRIVATE board serving a private build (never the fleet board or the shared dist).
//   node scripts/guest-screens.mjs <base> <probes.json> <outDir> <ownerToken> <guestToken>
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const [base, probes, outDir, ownerTok, guestTok] = process.argv.slice(2);
const { A, B } = JSON.parse(fs.readFileSync(probes, "utf8"));
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const results = [];

async function as(who, token, url, name, act) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 820 } });
  const page = await ctx.newPage();
  const sep = url.includes("?") ? "&" : "?";
  await page.goto(`${base}${url}${sep}as=${who}&token=${token}`);
  await page.waitForLoadState("domcontentloaded"); // the live feed (SSE) keeps the network busy
  const facts = act ? await act(page) : {};
  await page.waitForTimeout(600); // let the last query settle before the shot
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  results.push({ name, who, url, ...facts });
  await ctx.close();
}

const rail = async (page) => {
  const nav = page.getByRole("navigation", { name: "Sections" });
  return {
    rail: await nav.getByRole("link").allInnerTexts(),
    handle: await page.getByTestId("whoami-handle").innerText(),
    adminLink: await page.getByTestId("nav-admin").count(),
    askHelp: await page.getByTestId("ask-help").count(),
  };
};

await as("gina", guestTok, `/ui/epic/${A.epic}`, "1-guest-epic", async (page) => {
  await page.getByTestId("actions-open").waitFor();
  return rail(page);
});
await as("gina", guestTok, `/ui/epic/${A.epic}`, "2-guest-actions", async (page) => {
  await page.getByTestId("actions-open").click();
  const items = await page.getByTestId("actions-menu").getByRole("menuitem").allInnerTexts();
  return { actions: items, ...(await rail(page)) };
});
await as("gina", guestTok, `/ui/ticket/${A.story}`, "3-guest-story", async (page) => {
  await page.getByTestId("actions-open").waitFor();
  await page.getByTestId("actions-open").click();
  return { actions: await page.getByTestId("actions-menu").getByRole("menuitem").allInnerTexts() };
});
await as("gina", guestTok, `/ui/epic/${B.epic}`, "4-guest-non-member-epic", async (page) => {
  await page.getByRole("alert").first().waitFor();
  return { alert: await page.getByRole("alert").first().innerText() };
});
await as("owner", ownerTok, `/ui/epic/${A.epic}`, "5-owner-people-panel", async (page) => {
  await page.getByTestId("actions-open").click();
  await page.getByTestId("action-people").click();
  await page.getByTestId("people-row").first().waitFor();
  return { members: await page.getByTestId("people-row").allInnerTexts(),
           actions: await page.getByTestId("actions-menu").getByRole("menuitem").count() };
});
await as("owner", ownerTok, `/ui/admin?tab=teammates`, "6-owner-invite-defaults-guest", async (page) => {
  await page.getByTestId("invite-role").waitFor();
  return { inviteRole: await page.getByTestId("invite-role").inputValue(),
           adminDisabled: await page.getByTestId("invite-admin").isDisabled() };
});

await browser.close();
fs.writeFileSync(path.join(outDir, "screens.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
