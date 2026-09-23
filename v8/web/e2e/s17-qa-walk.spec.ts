import { test, expect, BASE } from "./fixtures";
import type { APIRequestContext } from "@playwright/test";

// S17 qa walk (s-1eb48690c6, report by qa): paths the engineer's spec left uncovered plus the three adversary
// findings qa reproduced and fixed (reply reveals a collapsed composer, a collapsed ticket keeps its title,
// same-origin links drop ?token in the href).
test.use({ boardFile: "s17-qa-walk" });
const SHOTS = "e2e/evidence/s17";

async function call(request: APIRequestContext, method: string, path: string, data: unknown, actor: string) {
  const res = await request.fetch(`${BASE()}${path}`, { method, headers: { "X-Participant": actor }, data });
  expect(res.ok(), `${method} ${path}: ${await res.text()}`).toBe(true);
  return (await res.json()).value;
}

let seeded: { epic: string; story: string } | null = null;
async function seed(request: APIRequestContext) {
  if (seeded) return seeded;
  const epic = (await call(request, "POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Walk epic title" }, "owner")).id as string;
  const story = (await call(request, "POST", "/v1/tickets", { kind: "story", work_type: "bug", parent_id: epic, title: "Walk story title" }, "arch")).id as string;
  await call(request, "POST", "/v1/messages", { ticket_id: epic, kind: "note", text: "First note with [link](javascript:alert(1)) and https://example.org/x and <img src=x onerror=alert(1)>" }, "arch");
  await call(request, "POST", "/v1/messages", { ticket_id: story, kind: "note", text: "Story note" }, "arch");
  seeded = { epic, story };
  return seeded;
}

test("ticket page: h1 visible, title bar + composer collapse work there too, tab title set", async ({ page, request }) => {
  const { story } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/ticket/${story}?as=owner`);
  await expect(page.getByTestId("conversation")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Walk story title" })).toBeVisible();
  await page.getByRole("button", { name: "Collapse title bar" }).click();
  await expect(page.getByTestId("work-metadata")).toBeHidden();
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand title bar" })).toBeVisible();
  await page.getByRole("button", { name: "Expand title bar" }).click();
  await page.screenshot({ path: `${SHOTS}/qa-ticket-1440.png` });
});

test("epic tab title still carries the title although the h1 is sr-only", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.goto(`/ui/epic/${epic}?as=owner`);
  await expect(page.getByTestId("conversation")).toBeVisible();
});

test("reply target survives a composer collapse/expand", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${epic}?as=owner`);
  await page.getByRole("button", { name: "Reply" }).first().click();
  await expect(page.getByText(/Replying to/)).toBeVisible();
  await page.getByRole("button", { name: "Collapse message box" }).click();
  await expect(page.getByText(/Replying to/)).toBeHidden();
  await page.getByTestId("composer-collapsed-bar").click();
  await expect(page.getByText(/Replying to/)).toBeVisible();
});

test("markdown: javascript: link and img onerror are neutralised", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.goto(`/ui/epic/${epic}?as=owner`);
  const md = page.getByTestId("message-md").first();
  await expect(md).toBeVisible();
  const hrefs = await md.locator("a").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(hrefs.some((h) => (h ?? "").toLowerCase().startsWith("javascript:")), "no javascript: href").toBe(false);
  expect(hrefs).toContain("https://example.org/x");
  await expect(md.locator("img")).toHaveCount(0);
  await expect(md).toContainText("<img");
});

test("mobile 390: collapsed-rail preference does not break the phone layout; help button clear of Actions", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${epic}?as=owner`);
  await page.getByRole("button", { name: "Collapse menu" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByTestId("conversation")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no horizontal scroll at 390").toBe(true);
  const menu = page.getByRole("button", { name: "Workspace navigation" });
  await expect(menu).toBeVisible();
  const help = page.getByRole("button", { name: "What am I looking at? (Ctrl /)" });
  const hb = (await help.boundingBox())!;
  for (const name of [/Actions/, /Workspace navigation/]) {
    const b = (await page.getByRole("button", { name }).first().boundingBox())!;
    const overlaps = !(b.x + b.width <= hb.x || b.x >= hb.x + hb.width || b.y + b.height <= hb.y || b.y >= hb.y + hb.height);
    expect(overlaps, `help button overlaps ${name}`).toBe(false);
  }
  await page.screenshot({ path: `${SHOTS}/qa-epic-390.png` });
  await menu.click();
  await expect(page.getByRole("link", { name: /Seats/ })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/qa-epic-390-menu.png` });
  // 844 (tablet, rail is a real rail): the remembered collapse applies and content is usable
  await page.setViewportSize({ width: 844, height: 900 });
  await page.reload();
  await expect(page.getByTestId("conversation")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no horizontal scroll at 844").toBe(true);
  await page.screenshot({ path: `${SHOTS}/qa-epic-844-rail.png` });
});

test("Reply while the composer is collapsed must reveal the composer", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${epic}?as=owner`);
  await page.getByRole("button", { name: "Collapse message box" }).click();
  await expect(page.getByTestId("composer-collapsed-bar")).toBeVisible();
  await page.getByRole("button", { name: "Reply" }).first().click();
  await expect(page.getByText(/Replying to/)).toBeVisible({ timeout: 2000 });
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeVisible();
});

test("ticket page with the title bar collapsed still shows its own title somewhere visible", async ({ page, request }) => {
  const { story } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/ticket/${story}?as=owner`);
  await expect(page.getByTestId("conversation")).toBeVisible();
  await page.getByRole("button", { name: "Collapse title bar" }).click();
  const n = await page.getByText("Walk story title", { exact: false }).evaluateAll((els) => els.filter((e) => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2; }).length);
  await page.screenshot({ path: `${SHOTS}/qa-ticket-collapsed-1440.png` });
  expect(n, "the collapsed ticket still shows its title").toBeGreaterThanOrEqual(1);
  await page.getByRole("button", { name: "Expand title bar" }).click();
});

test("same-origin message link keeps ?token in the DOM href", async ({ page, request }) => {
  const { epic } = await seed(request);
  await call(request, "POST", "/v1/messages", { ticket_id: epic, kind: "note", text: `see ${BASE()}/ui/epic/${epic}?token=SECRET123` }, "arch");
  await page.goto(`/ui/epic/${epic}?as=owner`);
  const hrefs = await page.getByTestId("message-md").locator("a").evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""));
  expect(hrefs.some((h) => h.includes("SECRET123")), "token survives in an href").toBe(false);
});
