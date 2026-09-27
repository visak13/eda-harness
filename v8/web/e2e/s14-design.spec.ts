import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, BASE, type Page } from "./fixtures";

// S14 (s-42a72db3dd; design-e963c656f5 §4.14): the Design tab against a real spawned board, run ALONE
// (`npx playwright test e2e/s14-design.spec.ts`). One serial walk of the admin flow — duplicate Standard,
// publish, a v2 with a new model, card, cap, hook and a custom role (a planted error shows inline and links
// to its panel; a card-less role is refused), dry run, diff, publish v2, New Epic pinned to it — then a
// dry-run stall that blocks Publish, "upstream changed" with its merge, and the read-only view.
// Screenshots land in e2e/evidence/s14-design/ (c-4e99b1d4d7).

const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "s14-design");
fs.mkdirSync(EVIDENCE, { recursive: true });
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(EVIDENCE, `${name}.png`), fullPage: true });

test.use({ boardFile: "s14-design" });
test.describe.configure({ mode: "serial" });

// t-0c16c00424 folded the panels into five sections; the walk keeps naming the panel it means (t-67d19c5807)
const SECTION: Record<string, string> = { Hooks: "Hooks and caps", Caps: "Hooks and caps", Gates: "Checks and gates", Diff: "Validate and publish" };
const tab = (page: Page, name: string) => page.getByRole("tab", { name: SECTION[name] ?? name, exact: true }).click();

async function validateClean(page: Page) {
  await page.getByTestId("design-validate-run").click();
  await expect(page.getByTestId("validate-ok")).toBeVisible();
}

test("admin: duplicate Standard, publish team@1, then team@2 with model, card, cap, hook and a custom role", async ({ page }) => {
  await page.goto(`${BASE()}/ui/epics?as=owner`);
  await page.getByRole("link", { name: "Design" }).click();
  await expect(page.getByTestId("design-page")).toBeVisible();
  await expect(page.getByTestId("pipeline-roles")).toBeVisible();
  await expect(page.getByTestId("flow-gate-design_signoff")).toBeVisible();
  await shot(page, "01-standard-pipeline");

  // Duplicate Standard under a new id, publish it unchanged: team@1
  await page.getByTestId("wf-duplicate-standard@1").click();
  await page.getByTestId("duplicate-id").fill("team");
  await page.getByTestId("duplicate-submit").click();
  await expect(page.getByTestId("design-title")).toContainText("team@1");
  await page.getByTestId("design-publish").click();
  await expect(page.getByTestId("design-done")).toContainText("team@1 is published");

  // v2: the next version of team
  await page.getByTestId("design-duplicate").click();
  await page.getByTestId("duplicate-submit").click();
  await expect(page.getByTestId("design-title")).toContainText("team@2");
  await expect(page.getByTestId("design-state")).toHaveText("draft");

  // a role's model (from the S12 catalog) and its card
  await tab(page, "Roles");
  await page.getByTestId("role-chip-engineer").click();
  const model = page.getByTestId("role-model");
  const values = await model.locator("option").evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value).filter(Boolean));
  expect(values.length).toBeGreaterThan(0);
  const current = await model.inputValue();
  await model.selectOption(values.find((v) => v !== current) ?? values[0]);
  await page.getByTestId("role-card-fork").click();
  const card = page.getByTestId("role-card");
  await card.fill(`${await card.inputValue()}\n\n## Team rule\n\nEvery story ships with a screenshot.`);
  await expect(page.getByTestId("role-card-preview")).toContainText("Every story ships with a screenshot.");
  await shot(page, "02-role-model-and-card");

  // a hook toggled, a cap planted at 0
  await tab(page, "Hooks");
  await page.getByTestId("hook-toggle-review_story_last").click();
  await tab(page, "Caps");
  await page.getByTestId("cap-stories_per_epic").fill("0");

  // Validate: the planted error shows inline and links to its panel
  await page.getByTestId("design-validate-run").click();
  await expect(page.getByTestId("problem-cap_below_1")).toBeVisible();
  await shot(page, "03-validate-planted-error");
  await page.getByTestId("problem-go-cap_below_1").click();
  await expect(page.getByTestId("design-caps")).toBeVisible();
  await expect(page.getByTestId("cap-stories_per_epic")).toBeFocused();
  await page.getByTestId("cap-stories_per_epic").fill("10");

  // Add role: a blank role (no card, no bundle) is refused; then an auditor from the checker template
  await tab(page, "Roles");
  await page.getByTestId("role-add-open").click();
  await page.getByTestId("role-add-template").selectOption("blank");
  await page.getByTestId("role-add-id").fill("helper");
  await page.getByTestId("role-add-spawner").selectOption("architect");
  await page.getByTestId("role-add-save").click();
  await page.getByTestId("design-validate-run").click();
  await expect(page.getByTestId("problem-card_missing")).toBeVisible();
  await expect(page.getByTestId("problem-bundle_missing")).toBeVisible();
  await shot(page, "04-validate-refuses-cardless-role");
  await page.getByTestId("problem-go-card_missing").click();
  await expect(page.getByTestId("role-form-helper")).toBeVisible();
  await page.getByTestId("role-remove").click();

  await page.getByTestId("role-add-open").click();
  await page.getByTestId("role-add-template").selectOption("checker");
  await page.getByTestId("role-add-id").fill("auditor");
  await page.getByTestId("role-add-label").fill("Auditor");
  await page.getByTestId("role-add-spawner").selectOption("architect");
  await page.getByTestId("role-add-save").click();
  await expect(page.getByTestId("role-form-auditor")).toBeVisible();
  await shot(page, "05-custom-role-auditor");
  await validateClean(page);

  // Dry run and diff against team@1
  await page.getByTestId("design-dryrun-run").click();
  await expect(page.getByTestId("dryrun-ok")).toBeVisible();
  await expect(page.getByTestId("dryrun-timeline")).toContainText("spawns");
  await shot(page, "06-dry-run");
  await tab(page, "Diff");
  await page.getByTestId("diff-against").selectOption("team@1");
  await expect(page.getByTestId("diff-table")).toContainText("roles.auditor");
  await expect(page.getByTestId("diff-table")).toContainText("caps.stories_per_epic");
  await shot(page, "07-diff-against-v1");

  await page.getByTestId("design-publish").click();
  await expect(page.getByTestId("design-done")).toContainText("team@2 is published");
  await expect(page.getByTestId("design-state")).toHaveText("published");
  await shot(page, "08-published-v2");
});

test("New Epic pins team@2 and the epic page shows it", async ({ page }) => {
  await page.goto(`${BASE()}/ui/epics?as=owner`);
  await page.getByTestId("new-epic-open").click();
  await page.getByTestId("new-epic-title").fill("Runs on team v2");
  await page.getByTestId("new-epic-words").fill("An epic on the team workflow.");
  await expect(page.getByTestId("new-epic-workflow")).toHaveValue("standard@1");
  await page.getByTestId("new-epic-workflow").selectOption("team@2");
  await shot(page, "09-new-epic-picker");
  await page.getByTestId("new-epic-create").click();
  await expect(page).toHaveURL(/\/ui\/epic\//);
  await expect(page.getByTestId("work-workflow")).toHaveText("team@2");
  await shot(page, "10-epic-pins-team-v2");
  // the list now shows the pin
  await page.goto(`${BASE()}/ui/design?as=owner`);
  await expect(page.getByTestId("wf-pins-team@2")).toContainText("pinned by 1 epic");
});

test("a dry-run stall blocks Publish; upstream changed merges into a new draft", async ({ page }) => {
  // fork@1 copies team@2 (its upstream) before team@3 exists
  await page.goto(`${BASE()}/ui/design?wf=team@2&as=owner`);
  await page.getByTestId("design-duplicate").click();
  await page.getByRole("radio", { name: /as a new workflow/ }).check();
  await page.getByTestId("duplicate-id").fill("fork");
  await page.getByTestId("duplicate-submit").click();
  await expect(page.getByTestId("design-title")).toContainText("fork@1");
  await tab(page, "Caps");
  await page.getByTestId("cap-tasks_per_story").fill("4");
  await page.getByTestId("design-save").click();
  await expect(page.getByTestId("design-state")).toHaveText("draft");

  // team@3: the epic acceptance checker pointed at a role that is not the epic's checker → stall
  await page.goto(`${BASE()}/ui/design?wf=team@2&as=owner`);
  await page.getByTestId("design-duplicate").click();
  await page.getByTestId("duplicate-submit").click();
  await expect(page.getByTestId("design-title")).toContainText("team@3");
  await tab(page, "Hooks");
  await page.getByTestId("hook-param-criteria_auto_done-epic_checker").selectOption("engineer");
  await page.getByTestId("design-publish").click();
  await expect(page.getByTestId("problem-dry_run_stall")).toBeVisible();
  await expect(page.getByTestId("design-state")).not.toHaveText("published");
  await page.getByTestId("problem-go-dry_run_stall").click();
  await page.getByTestId("dryrun-run").click();
  await expect(page.getByTestId("dryrun-stall")).toContainText("Stalls at");
  await shot(page, "11-dry-run-stall-blocks-publish");

  await tab(page, "Hooks");
  await page.getByTestId("hook-param-criteria_auto_done-epic_checker").selectOption("qa");
  await tab(page, "Caps");
  await page.getByTestId("cap-stories_per_epic").fill("12");
  await page.getByTestId("design-publish").click();
  await expect(page.getByTestId("design-done")).toContainText("team@3 is published");

  // fork@1 now sees team@2 → team@3 upstream
  await page.goto(`${BASE()}/ui/design?wf=fork@1&as=owner`);
  await expect(page.getByTestId("upstream-banner")).toContainText("team@2 → team@3");
  await page.getByTestId("upstream-show").click();
  await expect(page.getByTestId("upstream-diff")).toContainText("caps.stories_per_epic");
  await shot(page, "12-upstream-changed");
  await page.getByTestId("upstream-merge").click();
  await expect(page.getByTestId("upstream-merged")).toContainText("fork@2");
  await expect(page.getByTestId("design-title")).toContainText("fork@2");
  await shot(page, "13-upstream-merged");
  await tab(page, "Caps");
  await expect(page.getByTestId("cap-stories_per_epic")).toHaveValue("12");
  await expect(page.getByTestId("cap-tasks_per_story")).toHaveValue("4");
});

test("a non-admin reads the Design tab read-only", async ({ page }) => {
  await page.goto(`${BASE()}/ui/design?wf=team@2&as=tokuser`);
  await expect(page.getByTestId("design-readonly")).toBeVisible();
  await expect(page.getByTestId("design-title")).toContainText("team@2");
  await expect(page.getByTestId("design-publish")).toHaveCount(0);
  await expect(page.getByTestId("design-duplicate")).toHaveCount(0);
  await tab(page, "Roles");
  await expect(page.getByTestId("role-add-open")).toHaveCount(0);
  await expect(page.getByTestId("role-model")).toBeDisabled();
  await shot(page, "14-non-admin-read-only");
  const res = await fetch(`${BASE()}/v1/workflows/duplicate`, {
    method: "POST", headers: { "X-Participant": "tokuser", "content-type": "application/json" }, body: JSON.stringify({ ref: "team@2", new_id: "nope" }),
  });
  // the board refuses the write itself (a scope error), not only the UI
  expect(res.ok).toBe(false);
  expect(JSON.stringify(await res.json())).toContain("admins only");
});
