// architect m-32ad10fada (qa m-8e768c0c0a): the six 0.10.8 UI defects, shot at 1280 and 390. SHOT_SET=before|after names the
// folder under e2e/evidence/qafix2/. Assertions run only in the "after" set (the "before" set records what qa saw).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { BASE, EPIC, expect, test } from "./fixtures";

const SET = process.env.SHOT_SET ?? "after";
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "qafix2", SET);
test.use({ boardFile: "qafix2-shots" });
test.describe.configure({ mode: "serial", timeout: 180_000 });

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Participant": "owner" }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const arch = { "X-Participant": "arch" };
const after = (fn: () => Promise<void>) => (SET === "after" ? fn() : Promise.resolve());
let story = "";

test.beforeAll(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Make the Epics list readable on a phone: the title column keeps its width" });
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "A ticket title long enough that it needs several lines on a phone, so it must stay readable", parent_id: EPIC() })).id;
  await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: "A note." }, arch);
});

const shoot = (page: Page, name: string, label: string) => page.screenshot({ path: path.join(OUT, `${name}-${label}.png`), fullPage: false });
const go = async (page: Page, url: string) => { await page.goto(`${BASE()}/ui${url}${url.includes("?") ? "&" : "?"}as=owner`); await page.waitForTimeout(900); };

for (const [label, size] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`1 first mark: the header cell and the thread keep their place, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: `Shift epic ${label}` })).id;
    await call("POST", "/v1/messages", { ticket_id: epic, kind: "note", text: "Requirement one: the export must keep every column." }, arch);
    await page.addInitScript(() => { try { localStorage.setItem("edp8.ui.owner.composer-collapsed", "0"); } catch { /* blocked */ } });
    await go(page, `/epic/${epic}`);
    const top = () => page.getByTestId("thread").evaluate((el) => (el as HTMLElement).getBoundingClientRect().top + window.scrollY);
    const cell = () => page.getByTestId("work-attention").evaluate((el) => el.getBoundingClientRect().height);
    const t0 = await top(), h0 = await cell();
    await shoot(page, "1-first-mark-before-mark", label);
    await page.evaluate((text) => {
      const w = document.createTreeWalker(document.querySelector("[data-testid=thread]")!, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const at = (n as Text).data.indexOf(text); if (at < 0) continue;
        const r = document.createRange(); r.setStart(n, at); r.setEnd(n, at + text.length);
        const sel = window.getSelection()!; sel.removeAllRanges(); sel.addRange(r);
        document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true })); return;
      }
    }, "the export must keep every column");
    await page.getByTestId("quote-popover-mark").click();
    await expect(page.getByTestId("work-attention")).toContainText("1 open requirement");
    await page.waitForTimeout(800);
    const t1 = await top(), h1 = await cell();
    fs.writeFileSync(path.join(OUT, `1-first-mark-${label}.txt`), `thread top ${t0} -> ${t1}; Needs-attention cell ${h0}px -> ${h1}px\n`);
    await shoot(page, "1-first-mark-after-mark", label);
    await after(async () => { expect(t1, "the thread's offsetTop is unchanged across the first Mark").toBe(t0); expect(h1, "both states of the cell are the same height").toBe(h0); });
  });

  test(`2 admin seats & models: model ids never break inside a word, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    const ok = (value: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, value, hint: "" }) });
    const entry = (harness: string, provider: string) => ({ harness, provider, context_window: 1000000, auto_compact: 800000, effort_cap: "high" });
    await page.route("**/v1/admin/models", (route) => route.request().method() === "GET" ? route.fulfill(ok({
      models: { "claude-fable-5-1": entry("claude", "anthropic"), "claude-opus-5-5": entry("claude", "anthropic"), "claude-sonnet-5-5": entry("claude", "anthropic"), "gpt-6-sol": entry("codex", "openai") },
      role_models: { engineer: ["claude-sonnet-5-5", "gpt-6-sol"], architect: ["claude-opus-5-5"], adversary: ["claude-fable-5-1"] },
      selected: ["claude", "codex"], warnings: [] })) : route.fallback());
    await page.route("**/v1/admin/harnesses**", (route) => route.request().method() === "GET" ? route.fulfill(ok({
      harnesses: [{ harness: "claude", selected: true, installed: true, path: "C:/bin/claude", version: "2.1.0", signed_in: true, latest: "2.2.0", live_seats: [], update: null },
        { harness: "codex", selected: true, installed: true, path: "C:/bin/codex", version: "0.40.0", signed_in: true, latest: "0.41.0", live_seats: [], update: null }],
      selected: ["claude", "codex"], fable_ack: null, fable_notice: null })) : route.fallback());
    await go(page, "/admin?tab=models");
    await page.waitForTimeout(600);
    await page.getByTestId("models-table").scrollIntoViewIfNeeded(); await page.evaluate(() => window.scrollBy(0, -80));
    await shoot(page, "2-seats-models", label);
    await after(async () => {
      const broken = await page.evaluate(() => {
        const out: string[] = [];
        for (const el of Array.from(document.querySelectorAll("main *"))) {
          if (el.children.length) continue;
          const t = (el.textContent ?? "").trim();
          if (!/^[\w./:-]{6,}$/.test(t)) continue; // one token: a model id
          const r = document.createRange(); r.selectNodeContents(el);
          if (new Set(Array.from(r.getClientRects()).map((q) => Math.round(q.top))).size > 1) out.push(t);
        }
        return out;
      });
      expect(broken, "no model id wraps").toEqual([]);
    });
  });

  test(`3 library topics: Open topic is one line, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await go(page, "/library/topics");
    await shoot(page, "3-library-topics", label);
    await after(async () => {
      const b = await page.getByTestId("topic-open-button").boundingBox();
      expect(b!.height, "one line of a 40px button").toBeLessThanOrEqual(44);
    });
  });

  test(`4 library tickets: the title is readable, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await go(page, "/library/tickets");
    await shoot(page, "4-library-tickets", label);
    await after(async () => {
      const b = await page.getByTestId("tickets-table").getByText("A ticket title long enough").first().boundingBox();
      expect(b!.width, "the title column keeps room").toBeGreaterThan(label === "390" ? 250 : 200);
    });
  });

  test(`5 epics: the tally says No criteria yet once, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await go(page, "/epics");
    await shoot(page, "5-epics-none-defined", label);
    await after(async () => {
      for (const row of await page.getByTestId("epic-row").all()) expect(await row.getByText("No criteria yet").count()).toBeLessThanOrEqual(1);
    });
  });

  test(`6 guest: no Quick task or New epic, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.route("**/v1/whoami", async (route) => {
      const res = await route.fetch(); const body = await res.json();
      body.value = { ...body.value, role: "guest", admin: false, participant: body.value.participant ? { ...body.value.participant, role: "guest", admin: false } : body.value.participant };
      await route.fulfill({ response: res, json: body });
    });
    await go(page, "/epics");
    await shoot(page, "6-guest-epics", label);
    await after(async () => {
      await expect(page.getByTestId("quick-task-open")).toHaveCount(0);
      await expect(page.getByTestId("new-epic-open")).toHaveCount(0);
    });
  });
}
