import { expect, test, BASE } from "./fixtures";

test.use({ boardFile: "theme" }); // one fresh board per spec file (fixtures.ts)

// Criterion c-250f85164e (e2e half): the radiogroup switches theme and it survives a
// reload with no flash (pre-paint), and with nothing stored the app follows the OS media
// queries. Theme ids: heronry, heronry-dark (the defaults since the S7 rebrand c01e685), folio, dusk, ember, folio-hc.
const themeOf = (page: import("@playwright/test").Page) =>
  page.evaluate(() => document.documentElement.dataset.theme);

test("picking Ember sets data-theme=ember + color-scheme dark, and survives a reload", async ({ page }) => {
  await page.goto(`${BASE()}/ui/epics?as=owner`);

  await page.getByRole("button", { name: "Account and preferences" }).click();
  await page.getByRole("radio", { name: "Ember" }).check();

  await expect.poll(() => themeOf(page)).toBe("ember");
  const scheme = await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme);
  expect(scheme).toContain("dark");

  // Reload: the inline pre-paint script must re-apply Ember before React mounts.
  await page.reload();
  expect(await themeOf(page)).toBe("ember");
});

// S7 rebrand (s-5b508d7608, c01e685): Heronry dark is the prefers-dark default, no longer Ember.
test("nothing stored + prefers-color-scheme: dark → Heronry dark", async ({ browser }) => {
  const ctx = await browser.newContext({ colorScheme: "dark" });
  const page = await ctx.newPage();
  await page.goto(`${BASE()}/ui/epics?as=owner`);
  expect(await themeOf(page)).toBe("heronry-dark");
  await ctx.close();
});

test("nothing stored + prefers-contrast: more → Folio HC (beats dark)", async ({ browser }) => {
  const ctx = await browser.newContext({ colorScheme: "dark" });
  const page = await ctx.newPage();
  await page.emulateMedia({ contrast: "more" }); // set before navigation so pre-paint sees it
  await page.goto(`${BASE()}/ui/epics?as=owner`);
  expect(await themeOf(page)).toBe("folio-hc");
  await ctx.close();
});
