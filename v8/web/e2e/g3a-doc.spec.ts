import { expect, test, BASE } from "./fixtures";
import { seedEpic, type G3aFixture } from "./g3a.seed";

test.use({ boardFile: "g3a-doc" }); // one fresh board per spec file (fixtures.ts)

// G3a doc reader + drawer + §14 one-click sign-off, end-to-end. The reader sanitises and renders
// the doc (c-a0b2f8ddda); the shared drawer opens a doc in place over the epic (c-a44757ca87); the
// owner approves a doc-cited criterion in one click and the board records a pass (c-a0b2f8ddda).
let fx: G3aFixture;

test.beforeEach(async () => {
  // A fresh epic per test so the sign-off criterion is pending each time (a verdict is one-way).
  fx = await seedEpic();
});

test("the doc reader shows the title, version pills and sanitised body", async ({ page }) => {
  await page.goto(`${BASE()}/ui/doc/${fx.doc}?as=owner`);
  await expect(page.getByRole("heading", { level: 1, name: "Folio craft bars" })).toBeVisible();
  const versions = page.getByLabel("Versions");
  await expect(versions).toContainText("v2"); // latest
  await expect(versions).toContainText("v1");
  await expect(page.locator(".doc-md")).toContainText("Safe body text");
});

test("a hostile doc body (script, onerror, javascript: link) is stripped by the reader", async ({ page }) => {
  // v1 of the seeded doc carries the hostile markup (g3a.seed); v2 is the safe revision.
  await page.goto(`${BASE()}/ui/doc/${fx.doc}?version=1&as=owner`);
  const body = page.locator(".doc-md");
  await expect(body).toContainText("Safe body text");
  await expect(body.locator("script")).toHaveCount(0);
  await expect(body.locator("[onerror]")).toHaveCount(0);
  await expect(body.locator('a[href^="javascript:"]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned ?? 0)).toBe(0);
});

test("a doc opens in the shared drawer over the epic, and Esc restores the page", async ({ page }) => {
  await page.goto(`${BASE()}/ui/epic/${fx.epic}?as=owner`);
  await page.getByRole("tab", { name: /Documents/ }).click();
  await page.getByRole("button", { name: /Folio craft bars/ }).click();

  const panel = page.getByTestId("drawer-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("Safe body text");
  // The epic page is still mounted behind the scrim (its own <h1> title survives; the doc body
  // also renders an <h1> inside the drawer, so match the epic title by name, not `main h1`).
  await expect(page.getByRole("heading", { level: 1, name: fx.words })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
});

test("the owner approves a doc-cited criterion in one click and the board records a pass", async ({ page }) => {
  await page.goto(`${BASE()}/ui/doc/${fx.doc}?as=owner`);
  const pane = page.getByTestId("signoff-pane");
  await expect(pane).toBeVisible();

  // Nothing preselected: the chip reads Pending before the ruling.
  await expect(pane.getByTestId("verdict-chip")).toHaveText("Pending");
  await pane.getByTestId("approve").click();
  await expect(pane.getByTestId("verdict-chip")).toHaveText("Passed");

  // The board persisted it: the criterion now carries a pass verdict citing the doc version.
  const r = await fetch(`${BASE()}/v1/criteria?ticket_id=${fx.story}`, { headers: { "X-Participant": "owner" } });
  const j = (await r.json()) as { ok: boolean; value: { id: string; verdict: string; evidence_version: number | null }[] };
  const c = j.value.find((x) => x.id === fx.signoffCriterion)!;
  expect(c.verdict).toBe("pass");
  expect(c.evidence_version).toBe(2); // the current (latest) doc version the pane signed off
});
