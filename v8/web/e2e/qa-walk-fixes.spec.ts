// s-aa76c83998 items 3-6 (qa UI walk m-aa62e7bd8e): Playwright shots at 1280 and 390 px, with the asserts that make each a check.
// Throwaway board from THIS tree (never :9400). Shots go to e2e/evidence/qa-walk/.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { BASE, EPIC, expect, test } from "./fixtures";

const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "qa-walk");
test.use({ boardFile: "qa-walk", trace: "retain-on-failure" });
test.describe.configure({ mode: "serial", timeout: 120_000 });

const SIZES = [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const;
const shoot = async (page: Page, name: string, label: string) => {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE, `${name}-${label}.png`) });
};
const fulfil = (page: Page, glob: string, value: unknown) =>
  page.route(glob, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, value, hint: "" }) }));
const openAction = async (page: Page, key: string) => {
  await page.getByTestId("actions-open").click();
  await page.getByTestId(`action-${key}`).click();
};

for (const [label, size] of SIZES) {
  test(`item 3: Raise a decision offers only design sign-off and scope at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner`);
    await openAction(page, "raise-decision");
    const kind = page.getByTestId("gate-open-kind");
    await expect(kind).toBeVisible();
    expect(await kind.locator("option").allTextContents()).toEqual(["Design sign-off", "Scope"]);
    await shoot(page, "item3-raise-decision", label);
  });

  test(`item 4: an old open tab, older than the board, shows the reload banner at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.route("**/v1/health", (route) => route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ ok: true, version: "9.9.9", git_rev: "0000000-newer-than-this-bundle", started_at: "2999-01-01T00:00:00Z" }) }));
    await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner`);
    const banner = page.getByTestId("board-updated-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Heronry was updated. Reload to get the new version.");
    await expect(page.getByTestId("board-behind-banner")).toHaveCount(0);
    // F: the info tone (not the problem tone) and the standard secondary button, labelled Reload
    const tone = await banner.evaluate((el) => ({ bg: getComputedStyle(el).backgroundColor, ink: getComputedStyle(el).color }));
    const probe = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--accentwash").trim());
    expect(probe.length).toBeGreaterThan(0);
    const reload = banner.getByRole("button", { name: "Reload" });
    await expect(reload).toBeVisible();
    expect((await reload.boundingBox())!.height).toBeGreaterThanOrEqual(36); // the standard control height, not a native small button
    expect(tone.bg).not.toBe(await page.evaluate((v) => { const d = document.createElement("div"); d.style.background = v; document.body.appendChild(d); const c = getComputedStyle(d).backgroundColor; d.remove(); return c; }, probe));
    await shoot(page, "item4-update-banner", label);
  });

  test(`item 5: the glossary itself (Words on this page) has no Acceptance gate, has Requirement, and Scope lifts the story cap at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner`);
    await page.getByTestId("glossary-open").click();
    const panel = page.getByRole("dialog");
    await expect(panel).toBeVisible();
    const words = panel.getByRole("heading", { name: "Words on this page" });
    await expect(words).toBeVisible();
    const text = await panel.innerText();
    expect(text).not.toMatch(/Acceptance[^]{0,40}Decide whether the result is accepted/);
    expect(text).toMatch(/Requirement/);
    expect(text).toMatch(/holds the epic open until it is linked/);
    expect(text).toMatch(/Lift the limit on how many stories this epic may hold/);
    // C: the help text is for the owner
    for (const bad of [/#\d+/, /\/v1\//, /Astra/, /\bshell/i, /≠/, /\(acceptance\)/]) expect(text, String(bad)).not.toMatch(bad);
    // D: on a phone the sheet is the viewport minus a 16px gutter, and each term sits above its definition
    if (label === "390") {
      const box = (await panel.boundingBox())!;
      expect(Math.round(box.x)).toBe(16);
      expect(Math.round(box.width)).toBe(390 - 32);
      const dt = (await panel.locator("dt").first().boundingBox())!;
      const dd = (await panel.locator("dd").first().boundingBox())!;
      expect(dd.y).toBeGreaterThan(dt.y + dt.height - 2); // stacked, not side by side
    }
    await words.scrollIntoViewIfNeeded();
    await words.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await shoot(page, "item5-glossary", label);
  });
}

test("item 6a: the Work drawer's process chips wrap with no dangling connector at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner&view=work`);
  const strip = page.getByTestId("process-strip").first();
  await expect(strip).toBeVisible();
  const joints = await strip.locator("li[aria-hidden=true]").evaluateAll((els) => els.map((e) => getComputedStyle(e).display));
  expect(joints.every((d) => d === "none")).toBe(true);
  await shoot(page, "item6a-process-chips", "390");
});

test("item 6b: the help button scrolls away and never covers the spawn form's Effort select at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fulfil(page, "**/v1/pool/capabilities", { resume_parked: true, resume_closed: true, park: true, spawn: true });
  await page.goto(`${BASE()}/ui/seats?as=owner`);
  const effort = page.locator("select").filter({ has: page.locator("option[value=high]") }).first();
  await expect(effort).toBeVisible();
  await expect(page.getByTestId("glossary-open")).toHaveCSS("position", "absolute");
  // bring the select up under the help button's old spot (top right); a pinned button would sit on it
  await effort.evaluate((el) => { const top = el.getBoundingClientRect().top + window.scrollY; window.scrollTo(0, Math.max(0, top - 24)); });
  await page.waitForTimeout(150);
  const hit = await effort.evaluate((el) => { const b = el.getBoundingClientRect(); const top = document.elementFromPoint(b.left + b.width - 12, b.top + b.height / 2); return top === el || el.contains(top); });
  expect(hit, "the Effort select is the topmost element at its own centre-right").toBe(true);
  await shoot(page, "item6b-effort-select", "390");
});

test("item 6c: the composer is one line on a phone until it is opened", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner`);
  const bar = page.getByTestId("composer-collapsed-bar");
  await expect(bar).toBeVisible();
  expect((await bar.boundingBox())!.height).toBeLessThan(60);
  await shoot(page, "item6c-composer-collapsed", "390");
  await bar.click();
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  await shoot(page, "item6c-composer-open", "390");
});

test("item E: the expanded composer never sits on the line above it at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner`);
  await page.getByTestId("composer-collapsed-bar").click();
  const composer = page.getByTestId("conversation-composer");
  await expect(page.getByTestId("composer-collapse")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  const heading = page.getByRole("heading", { name: /^Conversation/ });
  await heading.scrollIntoViewIfNeeded();
  const h = (await heading.boundingBox())!;
  const toggle = (await page.getByTestId("composer-collapse").boundingBox())!;
  const c = (await composer.boundingBox())!;
  expect(h.y + h.height, "the heading ends above the toggle tab").toBeLessThanOrEqual(toggle.y);
  expect(h.y + h.height).toBeLessThanOrEqual(c.y);
  await shoot(page, "itemE-composer-expanded", "390");
  // desktop: the composer starts open; the heading still clears the toggle
  await page.setViewportSize({ width: 1280, height: 800 });
  await heading.scrollIntoViewIfNeeded();
  const h2 = (await heading.boundingBox())!;
  const t2 = (await page.getByTestId("composer-collapse").boundingBox())!;
  expect(h2.y + h2.height).toBeLessThanOrEqual(t2.y);
  await shoot(page, "itemE-composer-expanded", "1280");
});

test("item 6d: the header shows a skeleton, not Unknown, while the owner loads at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route(`**/v1/tickets/${EPIC()}/contextual*`, async (route) => { await new Promise((r) => setTimeout(r, 2500)); await route.continue(); });
  await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner`);
  const owner = page.getByTestId("work-owner");
  await expect(owner.getByTestId("work-owner-skeleton")).toBeAttached();
  expect(await owner.innerText()).not.toMatch(/Unknown/);
  await owner.scrollIntoViewIfNeeded();
  await shoot(page, "item6d-owner-skeleton", "390");
  await expect(owner).toContainText("owner", { timeout: 8000 });
});
