import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, BASE, type Page } from "./fixtures";

// S14 reopen (qa m-c4f23e49f0, owner m-b841864899: "easy to understand as the admin tab", "everything aligns with our
// app theme"): the Design tab and the new Admin visuals at 1440 px in light and dark. The Remote-access diagrams
// take the theme's colours, the Slack fields have Admin's field width, the Roles form and Validate show no raw ids
// as visible text, and the roles graph keeps every edge clear of the boxes. Run ALONE
// (`npx playwright test e2e/s14-theme-look.spec.ts`); shots land in e2e/evidence/s14-theme-look/<scheme>-<page>.png.
// Read-only walk: it never saves anything (a spec board must not press Save caps, t-8713b03b24).

const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "s14-theme-look");

test.use({ boardFile: "s14-theme-look" });

/** Visible text under `sel` with code / monospace details and tooltips left out: what a person reads. */
const readable = (page: Page, sel: string) => page.locator(sel).first().evaluate((root) => {
  const c = root.cloneNode(true) as HTMLElement;
  c.querySelectorAll("code, textarea, [class*='keyName'], [class*='mono'], title").forEach((e) => e.remove());
  return c.textContent ?? "";
});
/** snake_case ids (tool, permission, rule and field keys) a person should never have to read. */
const RAW_ID = /\b[a-z]+_[a-z_]+\b/g;

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: Design and Admin read in plain words on the app theme`, async ({ browser }) => {
    const ctx = await browser.newContext({ colorScheme: scheme, viewport: { width: 1440, height: 1000 } });
    const page = await ctx.newPage();
    fs.mkdirSync(EVIDENCE, { recursive: true });
    const shot = (name: string) => page.screenshot({ path: path.join(EVIDENCE, `${scheme}-${name}.png`), fullPage: true });
    const bg = async () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

    // Design → Overview: the roles graph, edges clear of every box, each box's text inside it
    await page.goto(`${BASE()}/ui/design?wf=standard@1&as=owner&panel=overview`);
    await expect(page.getByTestId("pipeline-roles")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(scheme === "dark" ? "heronry-dark" : "heronry");
    const graph = await page.getByTestId("pipeline-roles").evaluate((svg) => {
      const nodes = [...svg.querySelectorAll<SVGGElement>("[data-testid^='role-node-']")].map((g) => {
        const r = g.querySelector("rect")!.getBoundingClientRect();
        const texts = [...g.querySelectorAll("text")].map((t) => t.getBoundingClientRect());
        return { id: g.dataset.testid!, r: { x: r.x, y: r.y, w: r.width, h: r.height }, texts: texts.map((t) => ({ x: t.x, y: t.y, w: t.width, h: t.height })) };
      });
      const m = (svg as SVGSVGElement).getScreenCTM()!;
      const edges = [...svg.querySelectorAll<SVGPathElement>("path[data-testid^='spawn-edge-'], [data-testid^='check-edge-'] path")].map((p) => {
        const host = p.hasAttribute("data-testid") ? p : p.parentElement!;
        const pts: { x: number; y: number }[] = [];
        for (let d = 0; d <= p.getTotalLength(); d += 3) { const q = p.getPointAtLength(d); pts.push({ x: q.x * m.a + m.e, y: q.y * m.d + m.f }); }
        return { from: host.getAttribute("data-from")!, to: host.getAttribute("data-to")!, pts };
      });
      return { nodes, edges };
    });
    for (const n of graph.nodes) for (const t of n.texts) {
      expect(t.x + t.w, `${n.id} text inside its box`).toBeLessThanOrEqual(n.r.x + n.r.w + 0.5);
      expect(t.y + t.h, `${n.id} text inside its box`).toBeLessThanOrEqual(n.r.y + n.r.h + 0.5);
    }
    for (const e of graph.edges) for (const n of graph.nodes) {
      const id = n.id.slice("role-node-".length);
      if (id === e.from || id === e.to) continue;
      expect(e.pts.some((p) => p.x > n.r.x + 1 && p.x < n.r.x + n.r.w - 1 && p.y > n.r.y + 1 && p.y < n.r.y + n.r.h - 1), `${e.from}→${e.to} through ${id}`).toBe(false);
    }
    await shot("design-overview");

    // Design → Roles: tools and permissions by name, ids only in tooltips
    await page.goto(`${BASE()}/ui/design?wf=standard@1&as=owner&panel=roles&role=engineer`);
    await expect(page.getByTestId("role-form-engineer")).toBeVisible();
    for (const sel of ["[data-field='bundle']", "[data-field='permissions']"]) {
      expect((await readable(page, sel)).match(RAW_ID) ?? [], `raw ids in ${sel}`).toEqual([]);
    }
    await shot("design-roles");

    // Design → Validate and publish: problems as plain titles and sentences
    await page.goto(`${BASE()}/ui/design?wf=standard@1&as=owner&panel=publish`);
    await expect(page.getByTestId("design-validate")).toBeVisible();
    expect((await readable(page, "[data-testid='design-validate']")).match(RAW_ID) ?? []).toEqual([]);
    await shot("design-validate");

    // Admin → Remote access: the six diagrams are inline and painted with the theme's colours
    await page.goto(`${BASE()}/ui/admin?tab=remote&as=owner`);
    const imgs = page.locator("[data-testid^='remote-step-'][data-testid$='-img']");
    await expect(imgs).toHaveCount(6);
    const pageBg = await bg();
    for (let i = 0; i < 6; i++) {
      const fill = await imgs.nth(i).locator("svg > rect").first().evaluate((r) => getComputedStyle(r).fill);
      expect(fill, `diagram ${i + 1} background follows --bg`).toBe(pageBg);
    }
    await shot("admin-remote");

    // Admin → Integrations: Slack fields at Admin's standard width
    await page.goto(`${BASE()}/ui/admin?tab=integrations&as=owner`);
    for (const id of ["slack-bot-token", "slack-webhook", "slack-board-url"]) {
      const w = (await page.getByTestId(id).boundingBox())!.width;
      expect(w, `${id} width`).toBeGreaterThanOrEqual(400);
    }
    await page.getByTestId("integration-slack").scrollIntoViewIfNeeded();
    await shot("admin-integrations");
    await ctx.close();
  });
}
