import { test, expect, BASE } from "./fixtures";

// S19 qa (owner m-a168021c98 / art-1cd391eb24): the owner opened the LIVE design doc from the epic
// page with NO open review (`?doc=<design>` only) and saw (1) a pinned title block wasting space and
// (2) doc text scrolling through the gap between the pinned title and the drawer header. Reproduce
// that exact path on the fixed build: no design_signoff gate, long body, scroll, at the owner's
// viewport (~1680×870 CSS at 110 %) and at 1440×900.
test.use({ boardFile: "s19-qa-noreview" });
const SHOTS = "e2e/evidence/s19";

async function call(method: string, path: string, data: unknown, actor: string) {
  const r = await fetch(`${BASE()}${path}`, { method, headers: { "content-type": "application/json", "X-Participant": actor }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${path} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}
const BODY = ["# Conversation-first board: contextual review, retro character and Usage widget — proposed v7", "", "**Not approved. No implementation dispatched.** " + "This revision incorporates owner feedback. ".repeat(12), "", ...Array.from({ length: 14 }, (_, i) => `## ${i + 1}. Section ${i + 1}\n\n${"The owner should understand, discuss and act on work without learning internal event/lifecycle mechanics or losing the working conversation. ".repeat(6)}\n\n- Status, owner and assignee stay near the epic title.\n- The current design is linked prominently beside History.\n`)].join("\n");

let seeded: { epic: string; doc: string } | null = null;
async function seed() {
  if (seeded) return seeded;
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Board UI improvements" }, "owner")).id as string;
  const doc = (await call("POST", "/v1/docs", { doc_type: "design", title: "Conversation-first board: contextual review, retro character and Usage widget — proposed v7", scope: epic, body_md: BODY }, "arch")).id as string;
  await call("POST", "/v1/links", { from_id: epic, to_id: doc, relation: "designed_by" }, "arch");
  await call("PATCH", `/v1/tickets/${epic}`, { design_ref: doc }, "arch");
  seeded = { epic, doc };
  return seeded;
}

for (const [w, h] of [[1680, 870], [1440, 900]] as const) {
  test(`design doc without an open review, scrolled, ${w}x${h}`, async ({ page }) => {
    const { epic, doc } = await seed();
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`/ui/epic/${epic}?doc=${doc}&as=owner`);
    const panel = page.getByTestId("drawer-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByText("Section 1", { exact: false }).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/qa-noreview-${w}-top.png` });
    // Scroll the document: the owner sees body text passing between the pinned title and the header.
    await page.evaluate(() => {
      const els = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="drawer-panel"] *'));
      for (const el of els) if (el.scrollHeight > el.clientHeight + 20) el.scrollTop = 700;
    });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/qa-noreview-${w}-scrolled.png` });
    // Measure: the pinned block's height and whether any body text box overlaps it.
    const m = await page.evaluate(() => {
      const panel = document.querySelector('[data-testid="drawer-panel"]')!;
      const h1 = panel.querySelector("h1");
      const sticky = Array.from(panel.querySelectorAll<HTMLElement>("*")).filter((e) => ["sticky", "fixed"].includes(getComputedStyle(e).position));
      return { h1: h1?.getBoundingClientRect().toJSON(), sticky: sticky.map((e) => ({ cls: e.className, r: e.getBoundingClientRect().toJSON() })) };
    });
    console.log(`${w}x${h} ${JSON.stringify(m)}`);
  });
}
