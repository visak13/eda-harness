import path from "node:path";
import { expect, test, BASE } from "./fixtures";
import { seedEpic, type G3aFixture } from "./g3a.seed";

test.use({ boardFile: "s12-sweep-c" });

const SHOTS = path.join(process.cwd(), "e2e", "evidence", "s12-sweep-c");
const ADMIN = () => process.env.EDP8_ADMIN_TOKEN ?? "t";
let fx: G3aFixture;
let dupDoc = "";

async function call(method: string, p: string, body: unknown, headers: Record<string, string>) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
  return (await r.json()) as { value?: { id: string } };
}

test.beforeAll(async () => {
  fx = await seedEpic();
  await call("POST", "/v1/participants", { type: "agent", role: "architect", handle: "archc", id: "architect.s12c" }, { "X-Admin": ADMIN() });
  dupDoc = (await call("POST", "/v1/docs", { doc_type: "design", title: "Same Title Twice", body_md: "# Same Title Twice\n\nbody text", scope: fx.epic }, { "X-Participant": "architect.s12c" })).value!.id;
});

test("#2 the doc page source select is themed and fits a 390px column", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(`/ui/doc/${fx.doc}?as=owner`);
  const select = page.getByRole("combobox", { name: /Conversation source/ });
  await expect(select).toBeVisible();
  const m = await page.evaluate(() => {
    const s = document.querySelector("select")!;
    return { sw: document.documentElement.scrollWidth, iw: window.innerWidth, w: s.getBoundingClientRect().width, bg: getComputedStyle(s).backgroundColor };
  });
  expect(m.sw).toBeLessThanOrEqual(m.iw);
  expect(m.w).toBeLessThanOrEqual(m.iw);
  expect(m.bg).not.toBe("rgb(255, 255, 255)");
  await page.screenshot({ path: path.join(SHOTS, "02-doc-select-390-dark.png") });
});

test("#6 Escape closes the design drawer even when focus fell to body", async ({ page }) => {
  await page.goto(`/ui/epic/${fx.epic}?doc=${fx.doc}&as=owner`);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);
  await page.screenshot({ path: path.join(SHOTS, "06-drawer-open-focus-on-body.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await page.screenshot({ path: path.join(SHOTS, "06-drawer-closed-by-escape.png") });
});

test("#14 a doc whose body opens with its own title shows it once", async ({ page }) => {
  await page.goto(`/ui/doc/${dupDoc}?as=owner`);
  await expect(page.getByTestId("doc-title")).toHaveText("Same Title Twice");
  await expect(page.getByRole("heading", { name: "Same Title Twice" })).toHaveCount(1);
  await page.screenshot({ path: path.join(SHOTS, "14-doc-title-once.png") });
});

test("#11 admin and design pages carry their own screen-reader description", async ({ page }) => {
  for (const [route, re] of [["admin", /teammates/], ["design", /workflows/]] as const) {
    await page.goto(`/ui/${route}?as=owner`);
    await expect(page.getByTestId("page-framing")).toHaveText(re);
    expect(await page.getByTestId("page-framing").textContent()).not.toMatch(/Decisions collects/);
  }
});
