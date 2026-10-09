// s-341902c31f (qa c-4c274905e3): the epic page's Assigned seats panel offers Close on a live seat and Resume on a closed one
// (the Seats page's presence rule), never both on every seat. Throwaway board from THIS tree (never :9400).
// Screenshots go to e2e/evidence/assigned-seats/.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ADMIN } from "./board";
import { BASE, EPIC, expect, test } from "./fixtures";

const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "assigned-seats");
test.use({ boardFile: "assigned-seats", trace: "retain-on-failure" });
test.describe.configure({ mode: "serial", timeout: 120_000 });

async function call(method: string, p: string, body: unknown, who: Record<string, string>): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const admin = { "X-Admin": ADMIN };
const arch = { "X-Participant": "arch" };
let live = "", closed = "";

test.beforeAll(async () => {
  for (const [role, state] of [["engineer", "alive"], ["engineer", "dead"]] as const) {
    const story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: `${state} seat story`, parent_id: EPIC() }, arch)).id;
    const id = `${role}.${story}`;
    await call("POST", "/v1/participants", { type: "agent", role, handle: id, id }, admin);
    await call("PATCH", `/v1/tickets/${story}`, { assignee: id }, arch);
    await call("PUT", `/v1/sessions/sess-${state}`, { participant_id: id, ticket_id: story, pool_id: "e2e", state, ...(state === "dead" ? { reason: "closed by self: done" } : {}) }, admin);
    if (state === "alive") live = id; else closed = id;
  }
});

for (const [label, size] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`assigned seats: a live seat shows Close only, a closed seat Resume only, at ${label}px`, async ({ page }) => {
    await page.route("**/v1/pool/capabilities", (route) => route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ ok: true, value: { resume_parked: true, resume_closed: true, park: true, spawn: true }, hint: "" }) }));
    await page.setViewportSize(size);
    await page.goto(`${BASE()}/ui/epic/${EPIC()}?as=owner`);
    await page.getByTestId("actions-open").click();
    await page.getByTestId("action-assign-spawn").click();
    const liveRow = page.locator(`[data-testid=assigned-seat][data-seat="${live}"]`);
    const closedRow = page.locator(`[data-testid=assigned-seat][data-seat="${closed}"]`);
    await expect(liveRow).toHaveAttribute("data-presence", /working|stale/);
    await expect(closedRow).toHaveAttribute("data-presence", "closed");
    await expect(liveRow.getByTestId("assigned-seat-close")).toBeVisible();
    await expect(liveRow.getByTestId("assigned-seat-resume")).toHaveCount(0);
    await expect(closedRow.getByTestId("assigned-seat-resume")).toBeVisible();
    await expect(closedRow.getByTestId("assigned-seat-close")).toHaveCount(0);
    // each row says what state the seat is in, and the buttons sit in the same columns on every row
    await expect(liveRow.getByTestId("assigned-seat-state")).toHaveText(/Working|Presence not refreshed/);
    await expect(closedRow.getByTestId("assigned-seat-state")).toHaveText("Closed");
    const mx = async (row: typeof liveRow) => Math.round((await row.getByTestId("assigned-seat-message").boundingBox())!.x);
    const mw = async (row: typeof liveRow) => Math.round((await row.getByTestId("assigned-seat-message").boundingBox())!.width);
    expect(await mx(liveRow)).toBe(await mx(closedRow));
    expect(await mw(liveRow)).toBe(await mw(closedRow));
    // no hole: within a row, no two buttons are more than 16px apart
    for (const row of [liveRow, closedRow]) {
      const xs = await row.locator("a[data-testid=assigned-seat-message], button").evaluateAll((els) =>
        els.map((e) => { const r = e.getBoundingClientRect(); return { l: r.left, r: r.right }; }).sort((a, b) => a.l - b.l));
      for (let i = 1; i < xs.length; i++) expect(xs[i].l - xs[i - 1].r, "gap between buttons").toBeLessThanOrEqual(16);
    }
    // the epic itself has no assignee (the seats work its stories): the dialog and the page header both say Unassigned
    await expect(page.getByTestId("assign-current")).toHaveText("Unassigned");
    await expect(page.getByTestId("work-assigned")).toHaveText(/Unassigned/);
    fs.mkdirSync(EVIDENCE, { recursive: true });
    await page.screenshot({ path: path.join(EVIDENCE, `assigned-seats-${label}.png`) });
  });
}
