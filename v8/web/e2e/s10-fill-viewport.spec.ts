import { test, expect, BASE, type Page } from "./fixtures";

// S10 (s-edd2eda8f6, owner m-e587ecc667, screenshot art-71bad5407f): with the title bar collapsed the
// conversation and its composer ended ~170 px above the viewport bottom — the thread list is capped at
// 56vh and nothing filled the rest. The conversation region must reach the viewport bottom on the epic,
// story and task pages, in both title-bar states and both composer states, wide and narrow (≤850 px).
// Criterion c-9d29b4df62: the bottom edge equals the viewport height ±2 px with the title bar collapsed.
test.use({ boardFile: "s10-fill-viewport" });
const SHOTS = "e2e/evidence/s10";
const PHASE = process.env.S10_PHASE ?? "after";

async function call(method: string, p: string, data: unknown, actor: string) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", "X-Participant": actor }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${p} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

let pages: [string, string, "epic" | "ticket"][] = [];
test.beforeAll(async () => {
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Fill the viewport" }, "owner")).id as string;
  const story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "bug", parent_id: epic, title: "Short thread story" }, "arch")).id as string;
  const task = (await call("POST", "/v1/tickets", { kind: "task", work_type: "bug", parent_id: story, title: "Empty thread task" }, "arch")).id as string;
  for (const t of ["First status line.", "Second line with a bit more text to read.", "Third."]) {
    await call("POST", "/v1/messages", { ticket_id: epic, kind: "note", text: t }, "arch");
  }
  await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: "One message on the story." }, "arch");
  pages = [["epic", `/ui/epic/${epic}`, "epic"], ["story", `/ui/ticket/${story}`, "ticket"], ["task", `/ui/ticket/${task}`, "ticket"]];
});

async function open(page: Page, url: string, kind: string, header: boolean, composer: boolean) {
  await page.goto(`/ui/epics?as=owner`);
  await page.evaluate(([k, h, c]) => {
    localStorage.setItem(`edp8.ui.owner.${k}-header-collapsed`, h ? "1" : "0");
    localStorage.setItem(`edp8.ui.owner.composer-collapsed`, c ? "1" : "0");
  }, [kind, header, composer] as const);
  await page.goto(`${url}?as=owner`);
  await expect(page.getByTestId("conversation-composer")).toBeVisible();
}

/** Section bottom (document coordinates), the viewport height and the document height. */
function measure(page: Page) {
  return page.evaluate(() => {
    const s = document.querySelector("[data-testid=conversation]")!.getBoundingClientRect();
    return { bottom: s.bottom + window.scrollY, vh: document.documentElement.clientHeight, doc: document.documentElement.scrollHeight };
  });
}

for (const [w, h] of [[1917, 962], [800, 962]] as const) {
  test(`title bar collapsed: the conversation ends at the viewport bottom (${w}x${h})`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    for (const [name, url, kind] of pages) for (const composer of [false, true]) {
      await open(page, url, kind, true, composer);
      const label = `${name} ${w} composer ${composer ? "collapsed" : "expanded"}`;
      await expect.poll(async () => (await measure(page)).bottom, { message: label }).toBeGreaterThan(h - 3);
      const m = await measure(page);
      expect(Math.abs(m.bottom - m.vh), `${label}: section bottom ${m.bottom} vs viewport ${m.vh}`).toBeLessThanOrEqual(2);
      expect(m.doc, `${label}: no page scroll`).toBeLessThanOrEqual(m.vh + 2);
      await page.screenshot({ path: `${SHOTS}/${PHASE}-spec-${name}-${w}-hdrCollapsed-cmp${composer ? "Collapsed" : "Expanded"}.png` });
    }
  });

  test(`title bar expanded: no band under the conversation (${w}x${h})`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    for (const [name, url, kind] of pages) for (const composer of [false, true]) {
      await open(page, url, kind, false, composer);
      const label = `${name} ${w} expanded composer ${composer ? "collapsed" : "expanded"}`;
      await expect.poll(async () => (await measure(page)).bottom, { message: label }).toBeGreaterThan(h - 3);
      const m = await measure(page);
      expect(m.doc - m.bottom, `${label}: nothing below the conversation`).toBeLessThanOrEqual(2);
    }
  });
}

test("collapsing the title bar in place refills the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1917, height: 962 });
  const [, url, kind] = pages[0];
  await open(page, url, kind, false, false);
  await page.getByTestId("header-collapse").first().click();
  await expect.poll(async () => { const m = await measure(page); return Math.abs(m.bottom - m.vh); }).toBeLessThanOrEqual(2);
  await page.getByTestId("composer-collapse").click();
  await expect.poll(async () => { const m = await measure(page); return Math.abs(m.bottom - m.vh); }).toBeLessThanOrEqual(2);
});
