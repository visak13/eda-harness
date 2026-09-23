import { test, expect, BASE, type Page } from "./fixtures";

// S22 (s-8ebd40da22) c-b5ad036473 — consult #6: choosing a version in the design viewer must write
// ?v=N to the address, so reload, copy-link and Open in tab open version N; no ?v= opens the latest.
test.use({ boardFile: "s22-version-link" });

async function call(method: string, p: string, data: unknown, actor: string) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", "X-Participant": actor }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${p} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

const body = (n: number) => `# Versioned design\n\n## 1. Body of version ${n}\n\nMarker V${n}-MARK.`;
let seeded: { epic: string; doc: string } | null = null;
test.beforeAll(async () => {
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Version link epic" }, "owner")).id as string;
  const doc = (await call("POST", "/v1/docs", { doc_type: "design", title: "Versioned design", scope: epic, body_md: body(1) }, "arch")).id as string;
  await call("PATCH", `/v1/docs/${doc}`, { body_md: body(2) }, "arch");
  await call("PATCH", `/v1/docs/${doc}`, { body_md: body(3) }, "arch");
  await call("POST", "/v1/links", { from_id: epic, to_id: doc, relation: "designed_by" }, "arch");
  await call("PATCH", `/v1/tickets/${epic}`, { design_ref: doc }, "arch");
  seeded = { epic, doc };
});

const viewer = (page: Page) => page.getByRole("dialog").filter({ hasText: "Versioned design" });

async function pickVersion(page: Page, n: number) {
  const dialog = viewer(page);
  await dialog.getByTestId("version-now").click();
  await dialog.getByTestId("version-entry").filter({ hasText: `Version ${n}` }).first().click();
  await expect(dialog.getByTestId("version-now")).toContainText(`Version ${n}`);
  await expect(dialog.getByText(`V${n}-MARK`)).toBeVisible();
}

test("no ?v= opens the latest version", async ({ page }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  await expect(viewer(page).getByTestId("version-now")).toContainText("Version 3");
  await expect(viewer(page).getByText("V3-MARK")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("v")).toBeNull();
});

test("choosing a version writes ?v=N; reload reopens version N", async ({ page }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  await pickVersion(page, 1);
  await expect.poll(() => new URL(page.url()).searchParams.get("v")).toBe("1");
  expect(new URL(page.url()).searchParams.get("doc")).toBe(seeded!.doc);
  await page.reload();
  await expect(viewer(page).getByTestId("version-now")).toContainText("Version 1");
  await expect(viewer(page).getByText("V1-MARK")).toBeVisible();
  // Picking again moves the address with it (replace, no history entry per click).
  const before = await page.evaluate(() => history.length);
  await pickVersion(page, 2);
  await expect.poll(() => new URL(page.url()).searchParams.get("v")).toBe("2");
  expect(await page.evaluate(() => history.length)).toBe(before);
});

test("the ?v=N address and Open in tab both open version N in a new tab", async ({ page, context }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner`);
  await page.getByTestId("work-design").click();
  await pickVersion(page, 2);
  await expect.poll(() => new URL(page.url()).searchParams.get("v")).toBe("2");
  // The copied address, pasted into another tab.
  const copied = await context.newPage();
  await copied.goto(page.url());
  await expect(viewer(copied).getByTestId("version-now")).toContainText("Version 2");
  await expect(viewer(copied).getByText("V2-MARK")).toBeVisible();
  // Open in tab from the viewer.
  const [tab] = await Promise.all([context.waitForEvent("page"), viewer(page).getByRole("link", { name: /Open in tab/ }).click()]);
  await expect(tab.getByText("V2-MARK")).toBeVisible();
  await expect(tab.getByTestId("version-now")).toContainText("Version 2");
  // Choosing on the dedicated page writes ?v= there too.
  await tab.getByTestId("version-now").click();
  await tab.getByTestId("version-entry").filter({ hasText: "Version 1" }).first().click();
  await expect(tab.getByText("V1-MARK")).toBeVisible();
  await expect.poll(() => new URL(tab.url()).searchParams.get("v")).toBe("1");
  await tab.reload();
  await expect(tab.getByText("V1-MARK")).toBeVisible();
});

test("closing the viewer drops ?v=", async ({ page }) => {
  await page.goto(`/ui/epic/${seeded!.epic}?as=owner&doc=${seeded!.doc}&v=1`);
  await expect(viewer(page).getByText("V1-MARK")).toBeVisible();
  await viewer(page).getByRole("button", { name: "Close" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("v")).toBeNull();
  await expect.poll(() => new URL(page.url()).searchParams.get("doc")).toBeNull();
});
