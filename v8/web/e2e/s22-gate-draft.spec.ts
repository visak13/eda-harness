import { test, expect, BASE, type Page } from "./fixtures";

// S22 (s-8ebd40da22) c-5689957b8c — consult #3: a live refresh after the gate was answered elsewhere
// dropped it from the list, which unmounted the GateForm and lost the unsent ruling. Two browser
// contexts (two tabs of the owner): A types a ruling; live refetches keep it; B answers the gate;
// A keeps its text and shows "answered elsewhere" instead of the form vanishing.
test.use({ boardFile: "s22-gate-draft" });

async function call(method: string, p: string, data: unknown, actor: string) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", "X-Participant": actor }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${p} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

async function openGates(page: Page) {
  await page.goto(`/ui/me?as=owner`);
  await page.getByRole("tab", { name: /Gates/ }).click();
  await expect(page.getByTestId("gate-form")).toBeVisible();
  await page.waitForTimeout(1500); // live feed attached
}

test("A's unsent ruling survives live refetches and B answering the gate", async ({ browser }) => {
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Gate draft epic" }, "owner")).id as string;
  await call("POST", `/v1/gates/${epic}/demo/open`, { note: "rule on the demo" }, "arch");
  const a = await (await browser.newContext()).newPage();
  const b = await (await browser.newContext()).newPage();
  await openGates(a);
  await openGates(b);

  const RULING = "Ship it, but keep the old menu for one more week.\nSecond line of my ruling.";
  await a.getByTestId("gate-answer").fill(RULING);

  // Live refetches under the draft: events on the gate's epic (notes from a seat).
  for (let i = 0; i < 5; i++) await call("POST", "/v1/messages", { ticket_id: epic, kind: "note", text: `refresh ${i}` }, "arch");
  await a.waitForTimeout(1500);
  await expect(a.getByTestId("gate-answer")).toHaveValue(RULING);
  await expect(a.getByTestId("gate-answered-elsewhere")).toHaveCount(0);

  // B answers the same gate.
  await b.getByTestId("gate-answer").fill("Approved from the other tab.");
  await b.getByTestId("gate-submit").click();
  await expect.poll(async () => (await (await fetch(`${BASE()}/v1/gates/${epic}`, { headers: { "X-Participant": "owner" } })).json()).value?.length ?? 0).toBe(0);

  // A: the form is still mounted, the text intact, the notice shown, no Answer button.
  await expect(a.getByTestId("gate-answered-elsewhere")).toBeVisible({ timeout: 5_000 });
  await expect(a.getByTestId("gate-answer")).toHaveValue(RULING);
  await expect(a.getByTestId("gate-submit")).toHaveCount(0);
  await a.screenshot({ path: "e2e/evidence/s22/gate-answered-elsewhere.png" });
  // B (answered, nothing unsent): the gate is simply gone.
  await expect(b.getByTestId("gate-form")).toHaveCount(0);

  // A dismisses: the retained form goes away.
  await a.getByTestId("gate-dismiss").click();
  await expect(a.getByTestId("gate-form")).toHaveCount(0);
});
