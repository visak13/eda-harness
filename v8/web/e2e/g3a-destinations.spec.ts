import { expect, test } from "@playwright/test";
import { seedEpic, type G3aFixture } from "./g3a.seed";

// G3a destinations (S8+S9), proven end-to-end through the real Folio shell served at /app:
// epics list + filter (c-af7da9d034), epic page steer/work-filter/thread-toggle (c-af7da9d034),
// ticket deeplink + crumb, library sections + legacy redirects (c-e0b24cd134). Each block seeds
// its own epic via /v1 so the specs are order-independent.
const BASE = process.env.EDP8_E2E_BASE!;
let fx: G3aFixture;

test.beforeAll(async () => {
  fx = await seedEpic();
});

test.describe("epics list", () => {
  test("lists the seeded epic with a criteria tally, and status/q filters bind to the query string", async ({ page }) => {
    await page.goto(`${BASE}/app/epics?as=owner`);
    const list = page.getByTestId("epic-list");
    await expect(list).toContainText(fx.words);
    // The story carries 2 criteria (0 passed) → a tally, never a bare bar.
    await expect(list).toContainText(/of\s+\d+\s+passed|None defined/);

    // Typing a search term updates the URL (?q=) and re-filters without a reload. No epic matches
    // the nonsense term, so the seeded row leaves the page (the list may drop to the empty state).
    await page.getByLabel("Search epic titles and descriptions").fill("nonesuchzzz");
    await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("nonesuchzzz");
    // Scope to main: the sidebar's "In view" recents also carry the title, so assert the row left
    // the list itself (which may drop to its empty state).
    await expect(page.locator("main").getByText(fx.words)).toHaveCount(0);
  });
});

test.describe("epic page", () => {
  test("shows the owner steer as a directive, filters work, and the thread order toggles", async ({ page }) => {
    await page.goto(`${BASE}/app/epic/${fx.epic}?as=owner`);

    // Directive callout carries the owner's steer text.
    await expect(page.getByTestId("directive")).toHaveText(fx.steer);

    // Work tab → tree + 5-column kanban + a filter bar that narrows the tree.
    await page.getByRole("tab", { name: /Work/ }).click();
    await expect(page.getByTestId("work-tree")).toContainText("Epic page destination");
    await expect(page.getByTestId("kanban")).toBeVisible();
    await page.getByTestId("work-filters").getByLabel("Search words").fill("zzz-no-match");
    await expect(page.getByTestId("work-tree")).not.toContainText("Epic page destination");

    // Thread tab → the newest/oldest order toggle flips its own label/state.
    await page.getByRole("tab", { name: /Thread/ }).click();
    const toggle = page.getByTestId("order-toggle");
    const before = (await toggle.textContent())?.trim();
    await toggle.click();
    await expect.poll(async () => (await toggle.textContent())?.trim()).not.toBe(before);

    // 'Steer this epic' jumps to the composer primed as a steer.
    await page.getByRole("button", { name: "Steer this epic" }).click();
    await expect(page.getByPlaceholder(/posts as a steer/)).toBeVisible();
  });
});

test.describe("ticket page", () => {
  test("a ticket deeplink renders the status word and a crumb back to its epic", async ({ page }) => {
    await page.goto(`${BASE}/app/ticket/${fx.story}?as=owner`);
    await expect(page.getByTestId("status-chip")).toBeVisible();
    const crumb = page.getByRole("link", { name: new RegExp(fx.epic) });
    await expect(crumb).toBeVisible();
    await crumb.click();
    await expect.poll(() => new URL(page.url()).pathname).toContain(`/epic/${fx.epic}`);
  });
});

test.describe("library + legacy redirects", () => {
  test("the library lists all five sections and the tickets table renders", async ({ page }) => {
    await page.goto(`${BASE}/app/library/tickets?as=owner`);
    await expect(page.getByTestId("tickets-table")).toBeVisible();
    for (const s of ["Documents", "Artifacts", "Links", "Tickets", "History"]) {
      await expect(page.getByRole("link", { name: s })).toBeVisible();
    }
  });

  test("/tickets → /library/tickets and /activity → /library/history, preserving ?as=", async ({ page }) => {
    await page.goto(`${BASE}/app/tickets?as=owner`);
    await expect.poll(() => new URL(page.url()).pathname).toContain("/library/tickets");
    expect(new URL(page.url()).searchParams.get("as")).toBe("owner");

    await page.goto(`${BASE}/app/activity?as=owner`);
    await expect.poll(() => new URL(page.url()).pathname).toContain("/library/history");
    expect(new URL(page.url()).searchParams.get("as")).toBe("owner");
  });
});
