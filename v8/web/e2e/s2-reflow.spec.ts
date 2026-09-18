import { test, expect, BASE } from "./fixtures";
import { seedEpic, type G3aFixture } from "./g3a.seed";
test.use({ boardFile: "s2-reflow" });
let fixture: G3aFixture;
let artifact: string;
const token = "W".repeat(300);
test.beforeAll(async () => {
  fixture = await seedEpic();
  const headers = { "X-Participant": "owner", "Content-Type": "application/json" };
  const created = await fetch(`${BASE()}/v1/artifacts`, { method: "POST", headers, body: JSON.stringify({ form: "url", uri: `https://example.test/${token}`, note: token }) });
  expect(created.ok).toBeTruthy(); artifact = (await created.json()).value.id;
  const doc = await fetch(`${BASE()}/v1/docs/${fixture.doc}`, { method: "PATCH", headers: { ...headers, "X-Participant": "architect.g3a-1" }, body: JSON.stringify({ body_md: `# Long content\n\n${token}\n\nhttps://example.test/${token}\n\n${"Long prose ".repeat(100)}` }) });
  expect(doc.ok).toBeTruthy();
  for (const id of [fixture.epic, fixture.story]) {
    const response = await fetch(`${BASE()}/v1/messages`, { method: "POST", headers: { "X-Participant": "owner", "Content-Type": "application/json" }, body: JSON.stringify({ ticket_id: id, kind: "note", text: `${token} https://example.test/${token} @${token} long prose `.repeat(3) }) });
    expect(response.ok).toBeTruthy();
    const updated = await fetch(`${BASE()}/v1/tickets/${id}`, { method: "PATCH", headers: { "X-Participant": "owner", "Content-Type": "application/json" }, body: JSON.stringify({ description: token, tags: [token] }) });
    expect(updated.ok).toBeTruthy();
  }
});
for (const [width,height] of [[1440,900],[1280,800],[1100,768],[1024,768],[768,600],[390,844],[320,568],[844,390]]) {
  test(`route inventory long tokens ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width,height });
    const routes = ["me", "epics", `epic/${fixture.epic}`, `ticket/${fixture.story}`, "seats", "library/tickets", "library/docs", "library/artifacts", "library/activity", `doc/${fixture.doc}`, `artifact/${artifact}`];
    for (const route of routes) {
      await page.goto(`/ui/${route}${route.includes("?") ? "&" : "?"}as=owner`);
      await expect(page.locator("main")).toBeVisible();
      if (route.startsWith("epic/")) await page.getByRole("tab", { name: /Thread/ }).click();
      await page.waitForTimeout(150);
      const overflow = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth,
        offenders: [...document.querySelectorAll("main *")].filter((el) => el.getBoundingClientRect().right > innerWidth + 1).slice(0,12).map((el) => `${el.tagName}.${el.className}`) }));
      expect(overflow.width, `${route}: ${JSON.stringify(overflow)}`).toBeLessThanOrEqual(width + 1);
      if (width === 320 && route.startsWith("ticket/")) await page.screenshot({ path: "e2e/evidence/s2-reflow-320.png" });
    }
  });
}
