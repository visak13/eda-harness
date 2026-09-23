import { test, expect, BASE } from "./fixtures";

// S22 (s-8ebd40da22) c-b1989de2f4 — consult #2: useDraftGuard invalidated every 250 ms window with
// cancelRefetch:true, so under a sustained event stream (one per 150 ms) with a 1 s API no refetch
// ever landed and the thread froze until the feed went quiet. Storm: 20 s of notes from another
// seat every 150 ms, every board GET delayed 1 s (the feed itself is not delayed). The page must keep
// moving during the storm and show the newest note within 2 s of the storm ending.
test.use({ boardFile: "s22-storm" });
test.setTimeout(90_000);

async function call(method: string, p: string, data: unknown, actor: string) {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", "X-Participant": actor }, body: JSON.stringify(data) });
  const j = (await r.json()) as { ok: boolean; value: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${p} ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

test("20 s storm at 150 ms with a 1 s API: the thread keeps moving and the newest note lands ≤ 2 s after", async ({ page }) => {
  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Storm epic" }, "owner")).id as string;
  await page.goto(`/ui/epic/${epic}?as=owner`);
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeVisible();
  await page.waitForTimeout(1500); // feed attached

  const pageLoads = { started: 0, finished: 0, failed: 0 };
  const isEpicPage = (u: string) => new URL(u).pathname.includes(epic) && !/\/v1\/(feed|events)/.test(u);
  const paths = new Map<string, number>();
  page.on("request", (r) => { if (isEpicPage(r.url()) && r.method() === "GET") { pageLoads.started++; const k = new URL(r.url()).pathname; paths.set(k, (paths.get(k) ?? 0) + 1); } });
  page.on("requestfinished", (r) => { if (isEpicPage(r.url()) && r.method() === "GET") pageLoads.finished++; });
  page.on("requestfailed", (r) => { if (isEpicPage(r.url()) && r.method() === "GET") pageLoads.failed++; });
  await page.route("**/v1/**", async (route) => {
    const url = route.request().url();
    if (route.request().method() === "GET" && !/\/v1\/(feed|events)/.test(url)) await new Promise((r) => setTimeout(r, 1000));
    await route.continue().catch(() => {});
  });

  const t0 = Date.now();
  let n = 0;
  let seenAt5s = false;
  while (Date.now() - t0 < 20_000) {
    n++;
    await call("POST", "/v1/messages", { ticket_id: epic, kind: "note", text: `storm note ${n}` }, "arch");
    if (!seenAt5s && Date.now() - t0 > 5_000) seenAt5s = (await page.getByText(/^storm note \d+$/).count()) > 0;
    const wait = t0 + n * 150 - Date.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  }
  const end = Date.now();
  const last = `storm note ${n}`;
  await expect(page.getByText(last, { exact: true })).toBeVisible({ timeout: 2_000 });
  const landedMs = Date.now() - end;
  console.log(`storm: ${n} notes in ${end - t0} ms; newest visible ${landedMs} ms after the storm; epic GETs started=${pageLoads.started} finished=${pageLoads.finished} failed=${pageLoads.failed}; a note visible by 5 s: ${seenAt5s}; per path ${JSON.stringify([...paths])}`);
  expect(seenAt5s, "the thread moved during the storm (not frozen until quiet)").toBe(true);
  expect(landedMs).toBeLessThanOrEqual(2_000);
  // Coalesced: per query, roughly one load per API round-trip (~20 in 20 s), not one per 250 ms window
  // (~80), and none aborted.
  for (const [p, count] of paths) expect(count, p).toBeLessThanOrEqual(30);
  expect(pageLoads.failed).toBe(0);
});
