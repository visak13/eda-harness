import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, BASE, type Page } from "./fixtures";

// t-67d19c5807 (qa m-e633397a42): the Design tab's pipeline drawing at 1280, 1440 and 1920 px. The status flow
// reaches "done" inside its scroll box, no actor label is cut mid-word, and no edge or edge label crosses a
// role box. Run ALONE (`npx playwright test e2e/s14-pipeline-look.spec.ts`); screenshots land in
// e2e/evidence/s14-pipeline-look/<tag>-<width>.png (tag from EDP8_E2E_SHOT_TAG, default "after").

const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "s14-pipeline-look");
const TAG = process.env.EDP8_E2E_SHOT_TAG ?? "after";

test.use({ boardFile: "s14-pipeline-look" });

type Box = { x: number; y: number; width: number; height: number };
const overlap = (a: Box, b: Box, pad = 0) =>
  a.x < b.x + b.width - pad && b.x < a.x + a.width - pad && a.y < b.y + b.height - pad && b.y < a.y + a.height - pad;

/** Boxes of the role nodes and of every edge label, in SVG user units. */
async function rolesGeometry(page: Page) {
  return page.getByTestId("pipeline-roles").evaluate((svg) => {
    const box = (el: SVGGraphicsElement) => {
      const b = el.getBBox();
      const m = el.getCTM()!; const s = (svg as SVGSVGElement).getCTM()!.inverse().multiply(m);
      return { x: b.x + s.e, y: b.y + s.f, width: b.width, height: b.height };
    };
    const nodes = [...svg.querySelectorAll<SVGGElement>("[data-testid^='role-node-'] rect")].map((r) => ({
      id: r.parentElement!.getAttribute("data-testid")!.slice("role-node-".length), ...box(r) }));
    const labels = [...svg.querySelectorAll<SVGTextElement>("[data-testid^='check-edge-'] text")].map((t) => ({ text: t.textContent ?? "", ...box(t) }));
    // Sample each edge path; a sample strictly inside a box it does not start or end at is a crossing.
    const edges = [...svg.querySelectorAll<SVGPathElement>("path[data-testid^='spawn-edge-'], [data-testid^='check-edge-'] path")].map((p) => {
      const host = p.hasAttribute("data-testid") ? p : p.parentElement!;
      const id = host.getAttribute("data-testid")!;
      const from = host.getAttribute("data-from") ?? ""; const to = host.getAttribute("data-to") ?? "";
      const len = p.getTotalLength(); const pts: { x: number; y: number }[] = [];
      for (let d = 0; d <= len; d += 3) { const q = p.getPointAtLength(d); pts.push({ x: q.x, y: q.y }); }
      return { id, from, to, pts };
    });
    return { nodes, labels, edges };
  });
}

for (const width of [1280, 1440, 1920]) {
  test(`pipeline drawing at ${width}px: full status flow, whole actor labels, edges clear of boxes`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`${BASE()}/ui/design?wf=standard@1&as=owner`);
    await expect(page.getByTestId("pipeline-roles")).toBeVisible();
    fs.mkdirSync(EVIDENCE, { recursive: true });
    await page.getByTestId("design-pipeline").screenshot({ path: path.join(EVIDENCE, `${TAG}-${width}.png`) });

    // 1. every main-path status through done is reachable: inside the viewport of its scroll box, or the box scrolls
    const flow = page.getByTestId("pipeline-flow");
    const wrap = flow.locator("xpath=..");
    const done = page.getByTestId("flow-status-done");
    const scrollable = await wrap.evaluate((el) => el.scrollWidth > el.clientWidth && getComputedStyle(el).overflowX !== "hidden");
    const wb = (await wrap.boundingBox())!; const db = (await done.boundingBox())!;
    if (!scrollable) expect(db.x + db.width, "done sits inside the flow box").toBeLessThanOrEqual(wb.x + wb.width + 0.5);
    await done.scrollIntoViewIfNeeded();
    await expect(done).toBeInViewport();
    const cardBox = (await page.getByTestId("design-pipeline").boundingBox())!;
    expect(wb.x + wb.width, "the flow box stays inside its card").toBeLessThanOrEqual(cardBox.x + cardBox.width + 0.5);

    // 2. actor labels under the arrows: the full "who takes it" text, never a mid-word cut
    const labels = await flow.locator("[data-testid^='flow-edge-']").evaluateAll((gs) =>
      gs.map((g) => ({ aria: g.getAttribute("aria-label") ?? "", shown: [...g.querySelectorAll("text")].map((t) => (t.querySelector("tspan") ? [...t.querySelectorAll("tspan")] : [t]).map((s) => s.textContent ?? "").join(" ")).join(" ") })));
    expect(labels.length).toBeGreaterThan(0);
    for (const l of labels) {
      const who = l.aria.slice(l.aria.indexOf(": ") + 2);
      const shown = l.shown.replace(/\s+/g, " ").trim();
      expect(shown === who || who.split(/\s+/).join(" ") === shown, `label "${shown}" is the whole "${who}"`).toBe(true);
    }

    // ... and the wrapped labels don't run into each other or the pills
    const flowBoxes = await flow.evaluate((svg) => {
      const r = (el: Element) => { const b = el.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height }; };
      return { labels: [...svg.querySelectorAll("[data-testid^='flow-edge-'] text")].map(r), pills: [...svg.querySelectorAll("[data-testid^='flow-status-'] rect")].map(r) };
    });
    for (let i = 0; i < flowBoxes.labels.length; i++) {
      for (const p of flowBoxes.pills) expect(overlap(flowBoxes.labels[i], p), `flow label ${i} clear of a pill`).toBe(false);
      for (let j = i + 1; j < flowBoxes.labels.length; j++) expect(overlap(flowBoxes.labels[i], flowBoxes.labels[j]), `flow labels ${i}/${j} apart`).toBe(false);
    }

    // the roles graph shows every column inside its box (no last column off-canvas)
    const rolesSvg = (await page.getByTestId("pipeline-roles").boundingBox())!;
    const rolesWrap = (await page.getByTestId("pipeline-roles").locator("xpath=..").boundingBox())!;
    expect(rolesSvg.x + rolesSvg.width, "roles graph fits its box").toBeLessThanOrEqual(rolesWrap.x + rolesWrap.width + 0.5);

    // 3. roles graph: edges don't pass through a box they don't start/end at; labels don't touch any box
    const g = await rolesGeometry(page);
    for (const l of g.labels) for (const n of g.nodes) expect(overlap(l, n), `label "${l.text}" clear of ${n.id}`).toBe(false);
    for (let i = 0; i < g.labels.length; i++) for (let j = i + 1; j < g.labels.length; j++)
      expect(overlap(g.labels[i], g.labels[j]), `labels "${g.labels[i].text}" / "${g.labels[j].text}" apart`).toBe(false);
    for (const e of g.edges) {
      expect(e.from && e.to, `${e.id} names its ends`).toBeTruthy();
      for (const n of g.nodes) {
        if (n.id === e.from || n.id === e.to) continue;
        const inside = e.pts.some((p) => p.x > n.x + 1 && p.x < n.x + n.width - 1 && p.y > n.y + 1 && p.y < n.y + n.height - 1);
        expect(inside, `${e.id} runs through ${n.id}`).toBe(false);
      }
    }
  });
}
