import { expect, test } from "@playwright/test";
import { seedEpic, type G3aFixture } from "./g3a.seed";

// G3a doc reader + drawer + §14 one-click sign-off, end-to-end. The reader sanitises and renders
// the doc (c-a0b2f8ddda); the shared drawer opens a doc in place over the epic (c-a44757ca87); the
// owner approves a doc-cited criterion in one click and the board records a pass (c-a0b2f8ddda).
const BASE = process.env.EDP8_E2E_BASE!;
let fx: G3aFixture;

test.beforeEach(async () => {
  // A fresh epic per test so the sign-off criterion is pending each time (a verdict is one-way).
  fx = await seedEpic();
});

test("the doc reader shows the title, version pills and sanitised body", async ({ page }) => {
  await page.goto(`${BASE}/app/doc/${fx.doc}?as=owner`);
  await expect(page.getByRole("heading", { level: 1, name: "Folio craft bars" })).toBeVisible();
  const versions = page.getByLabel("Versions");
  await expect(versions).toContainText("v2"); // latest
  await expect(versions).toContainText("v1");
  await expect(page.locator(".doc-md")).toContainText("Safe body text");
});

test("a doc opens in the shared drawer over the epic, and Esc restores the page", async ({ page }) => {
  await page.goto(`${BASE}/app/epic/${fx.epic}?as=owner`);
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
  await page.goto(`${BASE}/app/doc/${fx.doc}?as=owner`);
  const pane = page.getByTestId("signoff-pane");
  await expect(pane).toBeVisible();

  // Nothing preselected: the chip reads Pending before the ruling.
  await expect(pane.getByTestId("verdict-chip")).toHaveText("Pending");
  await pane.getByTestId("approve").click();
  await expect(pane.getByTestId("verdict-chip")).toHaveText("Passed");

  // The board persisted it: the criterion now carries a pass verdict citing the doc version.
  const r = await fetch(`${BASE}/v1/criteria?ticket_id=${fx.story}`, { headers: { "X-Participant": "owner" } });
  const j = (await r.json()) as { ok: boolean; value: { id: string; verdict: string; evidence_version: number | null }[] };
  const c = j.value.find((x) => x.id === fx.signoffCriterion)!;
  expect(c.verdict).toBe("pass");
  expect(c.evidence_version).toBe(2); // the current (latest) doc version the pane signed off
});
