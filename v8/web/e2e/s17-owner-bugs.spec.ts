import { test, expect, BASE, type Page } from "./fixtures";
import type { APIRequestContext } from "@playwright/test";

// S17 (s-1eb48690c6): the owner's UI bug report m-132ba5bf1e, one test per item. Screenshots land in
// the IGNORED e2e/evidence/s17/ dir; S17_PHASE=before|after names them (a before run is taken on the
// pre-fix bundle, so only the capture test runs meaningfully there).
test.use({ boardFile: "s17" });
const PHASE = process.env.S17_PHASE ?? "after";
const SHOTS = "e2e/evidence/s17";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${PHASE}-${name}.png` });

interface Seed { epic: string; story: string }
let seeded: Seed | null = null;

async function call(request: APIRequestContext, method: string, path: string, data: unknown, actor: string, admin = false) {
  const headers: Record<string, string> = admin ? { "X-Admin": "t" } : { "X-Participant": actor };
  const res = await request.fetch(`${BASE()}${path}`, { method, headers, data });
  expect(res.ok(), `${method} ${path}: ${await res.text()}`).toBe(true);
  return (await res.json()).value;
}

/** One epic with a story, three seats, 24 linked docs (a Files & evidence list that must scroll) and
 *  a Markdown-heavy message. Seeded once per board. */
async function seed(request: APIRequestContext): Promise<Seed> {
  if (seeded) return seeded;
  const epic = (await call(request, "POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Owner bug sweep" }, "owner")).id as string;
  const story = (await call(request, "POST", "/v1/tickets", { kind: "story", work_type: "bug", parent_id: epic, title: "Readable seats and chat" }, "arch")).id as string;
  for (const [id, role] of [["engineer.s17", "engineer"], ["qa.s17", "qa"], ["reviewer.s17-with-a-rather-long-handle", "reviewer"]]) {
    await call(request, "POST", "/v1/participants", { type: "agent", role, handle: id, id }, "", true);
  }
  await call(request, "PATCH", `/v1/tickets/${story}`, { assignee: "engineer.s17" }, "arch");
  for (let n = 1; n <= 24; n++) {
    const doc = await call(request, "POST", "/v1/docs", {
      doc_type: n % 3 ? "note" : "design", title: `Evidence record ${n} — a reasonably long document title to wrap`, scope: epic,
      body_md: `# Record ${n}\n\nBody.`,
    }, "arch");
    await call(request, "POST", "/v1/links", { from_id: epic, to_id: doc.id, relation: n % 2 ? "evidence_for" : "uses_strategy" }, "arch");
  }
  await call(request, "POST", "/v1/messages", { ticket_id: epic, kind: "note", text: [
    "Status for **S17**:",
    "",
    "| Item | State |",
    "|---|---|",
    "| gap | fixed |",
    "| seats | fixed |",
    "",
    "```ts",
    "const ok = 1;",
    "```",
    "",
    "- first bullet",
    "- second bullet",
    "",
    "See [the docs](https://example.com/docs) and <b>raw</b> <script>window.__pwned = 1</script>",
  ].join("\n") }, "arch");
  seeded = { epic, story };
  return seeded;
}

test("capture: files & evidence, seats, epic, account menu", async ({ page, request }) => {
  const { epic } = await seed(request);
  for (const [w, h] of [[1440, 900], [844, 390], [320, 568]] as const) {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`/ui/epic/${epic}?as=owner&view=files`);
    const dialog = page.getByRole("dialog", { name: "Files & evidence", exact: true });
    await expect(dialog).toBeVisible();
    await shot(page, `files-${w}-top`);
    await dialog.locator("[class*=body]").last().evaluate((el) => { el.scrollTop = el.scrollHeight; });
    await page.mouse.wheel(0, 600);
    await shot(page, `files-${w}-scrolled`);
  }
  for (const [w, h] of [[1440, 900], [844, 900]] as const) {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`/ui/seats?as=owner`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForTimeout(400);
    await shot(page, `seats-${w}`);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${epic}?as=owner`);
  await expect(page.getByTestId("conversation")).toBeVisible();
  await shot(page, "epic-1440");
  await page.setViewportSize({ width: 1440, height: 600 });
  await page.getByTestId("account-open").click();
  await page.getByRole("dialog", { name: "Account and preferences" }).evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await shot(page, "account-600-scrolled");
});

// Item 1 — c-f142c65a60: the Files & evidence sheet meets the viewport's top/right/bottom edges (no
// inset strip showing the page behind) and fills the width below 960px, at every scroll position.
test("files & evidence: no gap shows the page behind, at 320/844/1440 and after scrolling", async ({ page, request }) => {
  const { epic } = await seed(request);
  for (const [w, h] of [[1440, 900], [844, 390], [320, 568]] as const) {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`/ui/epic/${epic}?as=owner&view=files`);
    const panel = page.getByRole("dialog", { name: "Files & evidence", exact: true });
    await expect(panel).toContainText("Evidence record 23");
    for (const scrolled of [false, true]) {
      if (scrolled) {
        await panel.locator("[class*=body]").last().evaluate((el) => { el.scrollTop = el.scrollHeight; });
        await page.mouse.wheel(0, 800);
      }
      const b = (await panel.boundingBox())!;
      expect(Math.round(b.y), `${w} top`).toBe(0);
      expect(Math.round(b.y + b.height), `${w} bottom`).toBe(h);
      expect(Math.round(b.x + b.width), `${w} right`).toBe(w);
      if (w < 960) expect(Math.round(b.x), `${w} left`).toBe(0);
      // Every edge strip the old inset panel left see-through now hits the panel itself.
      const points: [number, number][] = [[w - 2, 2], [w - 2, h - 2], [w - 2, Math.round(h / 2)], [Math.round(b.x) + 16, h - 2]];
      if (w < 960) points.push([2, 2], [2, h - 2]);
      for (const [x, y] of points) {
        const inside = await page.evaluate(([px, py]) => {
          const hit = document.elementFromPoint(px, py);
          return Boolean(hit?.closest('[data-testid="drawer-panel"]'));
        }, [x, y]);
        expect(inside, `${w}${scrolled ? " scrolled" : ""} point ${x},${y} is inside the panel`).toBe(true);
      }
    }
    await shot(page, `files-${w}-scrolled`);
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
  }
});

// Item 2 — c-7822cf388d: the seats table fills the canvas, uses one type scale, and at 844 the rows
// stack as labelled cards with no horizontal scroll and no word broken inside a button.
test("seats: consistent scale at 1440, stacked and scroll-free at 844", async ({ page, request }) => {
  await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/seats?as=owner`);
  const table = page.getByRole("table", { name: "Seats" });
  await expect(table.getByTestId("seat-row").first()).toBeVisible();
  const main = (await page.getByRole("main").boundingBox())!;
  const tb = (await table.boundingBox())!;
  expect(tb.width, "table fills the canvas").toBeGreaterThan(main.width - 32 - 72 - 4);
  const heads = await table.locator("thead th").evaluateAll((ths) => ths.map((th) => getComputedStyle(th).fontSize));
  expect(new Set(heads)).toEqual(new Set(["12px"]));
  const cellPads = await table.locator("tbody td").evaluateAll((tds) => [...new Set(tds.map((td) => getComputedStyle(td).paddingTop))]);
  expect(cellPads).toEqual(["16px"]);
  await shot(page, "seats-1440");
  await page.setViewportSize({ width: 844, height: 900 });
  await page.waitForTimeout(200);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no horizontal scroll at 844").toBe(true);
  const msgBtn = table.getByTestId("seat-message").first();
  expect(Math.round((await msgBtn.boundingBox())!.height), "Message is one line").toBeLessThanOrEqual(40);
  await expect(table.locator("thead")).toBeHidden();
  await shot(page, "seats-844");
});

// Item 3 + 8 — c-7a3c3ec439: Word-style collapse of the title bar and the message box, remembered
// across reloads; the epic title appears at most twice (rail + breadcrumb), never again in the header.
test("epic: title bar + message box collapse, persisted; title shown at most twice", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${epic}?as=owner`);
  await expect(page.getByTestId("conversation")).toBeVisible();
  const visibleTitles = () => page.getByText("Owner bug sweep", { exact: true }).evaluateAll((els) => els.filter((e) => {
    const r = e.getBoundingClientRect();
    return r.width > 2 && r.height > 2 && getComputedStyle(e).visibility !== "hidden";
  }).length);
  expect(await visibleTitles(), "rail + breadcrumb only").toBeLessThanOrEqual(2);
  await expect(page.getByRole("heading", { level: 1, name: "Owner bug sweep" })).toHaveCount(1); // still named for AT

  const draft = page.getByRole("textbox", { name: "Message", exact: true });
  await draft.fill("Draft survives collapse");
  await page.getByRole("button", { name: "Collapse title bar" }).click();
  await expect(page.getByTestId("work-metadata")).toBeHidden();
  await page.getByRole("button", { name: "Collapse message box" }).click();
  await expect(draft).toBeHidden();
  await expect(page.getByTestId("composer-collapsed-bar")).toBeVisible();
  await shot(page, "epic-collapsed-1440");
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand title bar" })).toBeVisible();
  await expect(page.getByTestId("work-metadata")).toBeHidden();
  await expect(page.getByTestId("composer-collapsed-bar")).toBeVisible();
  await page.getByTestId("composer-collapsed-bar").click();
  await expect(draft).toBeVisible();
  await expect(draft).toHaveValue("Draft survives collapse");
  await page.getByRole("button", { name: "Expand title bar" }).click();
  await expect(page.getByTestId("work-metadata")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Collapse title bar" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeVisible();
  // Renders without storage: a throwing localStorage must not break the page.
  await page.addInitScript(() => { Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } }); });
  await page.reload();
  await expect(page.getByTestId("conversation")).toBeVisible();
  await expect(page.getByRole("button", { name: "Collapse title bar" })).toBeVisible();
});

// Item 4 — c-33ffd96baf: the rail collapses to an icon rail, the conversation gains the width, and
// the choice survives a reload.
test("left menu: collapse to icon rail widens the messages and is remembered", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${epic}?as=owner`);
  const list = page.getByTestId("thread");
  await expect(list).toBeVisible();
  const before = (await list.boundingBox())!.width;
  await page.getByRole("button", { name: "Collapse menu" }).click();
  await expect(page.getByRole("complementary", { name: "Primary" })).toHaveJSProperty("offsetWidth", 64);
  await page.waitForTimeout(250);
  const after = (await list.boundingBox())!.width;
  expect(after - before, "messages gain the freed rail width").toBeGreaterThanOrEqual(120);
  await expect(page.getByRole("link", { name: /Seats/ })).toBeVisible();
  await shot(page, "rail-collapsed-1440");
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand menu" })).toBeVisible();
  await page.getByRole("button", { name: "Expand menu" }).click();
  await expect(page.getByRole("complementary", { name: "Primary" })).toHaveJSProperty("offsetWidth", 192);
});

// Item 5 — c-b1f32f8b33: a thread message renders a table, a code fence, bold, a list and a link;
// raw HTML is shown as text, never executed.
test("chat: messages render Markdown safely", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/ui/epic/${epic}?as=owner`);
  const md = page.getByTestId("message-md").first();
  await expect(md.locator("table td").first()).toHaveText("gap");
  await expect(md.locator("pre code")).toHaveText("const ok = 1;");
  await expect(md.locator("strong")).toHaveText("S17");
  await expect(md.locator("ul li")).toHaveCount(2);
  await expect(md.getByRole("link", { name: "the docs" })).toHaveAttribute("href", "https://example.com/docs");
  await expect(md).toContainText("<b>raw</b>");
  await expect(md.locator("script, b")).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  await md.scrollIntoViewIfNeeded();
  await shot(page, "chat-markdown-1440");
});

// Item 6 — c-066a9b347a: (a) the account menu header stays pinned while its body scrolls; (b) the
// help is a floating top-right button with a tooltip; (c) Enable notifications lives on Settings.
test("chrome: pinned account header, floating help tooltip, notifications on Settings", async ({ page, request }) => {
  const { epic } = await seed(request);
  await page.setViewportSize({ width: 1440, height: 600 });
  await page.goto(`/ui/epic/${epic}?as=owner`);
  await page.getByTestId("account-open").click();
  const menu = page.getByRole("dialog", { name: "Account and preferences" });
  const heading = menu.getByRole("heading", { name: "Account", exact: true });
  const top = (await heading.boundingBox())!.y;
  const body = menu.getByTestId("anchored-body");
  expect(await body.evaluate((el) => el.scrollHeight > el.clientHeight), "menu body overflows at 600px").toBe(true);
  await body.evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await page.waitForTimeout(100);
  expect(Math.round((await heading.boundingBox())!.y), "header pinned").toBe(Math.round(top));
  await expect(menu.getByRole("button", { name: "Close Account and preferences" })).toBeInViewport();
  await expect(menu.getByTestId("glossary-open")).toHaveCount(0);
  await expect(menu.getByRole("button", { name: "Enable notifications" })).toHaveCount(0);
  await shot(page, "account-600-scrolled");
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 1440, height: 900 });
  const help = page.getByRole("button", { name: "What am I looking at? (Ctrl /)" });
  const hb = (await help.boundingBox())!;
  expect(hb.x + hb.width, "top-right").toBeGreaterThan(1440 - 64);
  expect(hb.y, "top-right").toBeLessThan(40);
  const actions = (await page.getByRole("button", { name: /Actions/ }).first().boundingBox())!;
  expect(actions.x + actions.width <= hb.x || actions.y >= hb.y + hb.height, "does not cover Actions").toBe(true);
  await help.focus();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await shot(page, "help-tooltip-1440");
  await help.click();
  await expect(page.getByRole("dialog", { name: "What am I looking at?" })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto(`/ui/settings?as=owner&tab=notifications`);
  await expect(page.getByRole("region", { name: "Board notifications" }).getByRole("button", { name: "Enable notifications" })).toBeVisible();
  await shot(page, "settings-notifications-1440");
});
