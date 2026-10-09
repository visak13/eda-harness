// qa report-689ceb50f0 (fail 4-6, architect m-b1eaae38c8): at 390 px the Library tabs broke letter by letter, the Epics list
// title had width 0, and Admin -> Teammates broke words mid-word. ONE sweep over every route at 390 and 1280: it fails when a
// visible text element is narrower than its own longest word (a word would break mid-word, or the text has no room at all),
// or when its text spills outside its box. A scroll container (overflow auto/scroll/hidden), an ellipsised line and a code
// block that scrolls are meant to be wider than their box and are skipped. Evidence: e2e/evidence/text-fits/.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { ADMIN } from "./board";
import { BASE, EPIC, expect, test } from "./fixtures";

const EVIDENCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "evidence", "text-fits");
test.use({ boardFile: "text-fits" });
test.describe.configure({ mode: "serial", timeout: 240_000 });

async function call(method: string, p: string, body?: unknown, who: Record<string, string> = { "X-Admin": ADMIN }): Promise<any> {
  const r = await fetch(`${BASE()}${p}`, { method, headers: { "content-type": "application/json", ...who }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(`${method} ${p}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value;
}
const owner = { "X-Participant": "owner" };
const arch = { "X-Participant": "arch" };
let story = "", design = "", report = "";

test.beforeAll(async () => {
  // a long title and a long unbroken id-like word: the rows that exposed the failures
  await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: "Make the Epics list readable on a phone: the title column keeps its width" }, owner);
  story = (await call("POST", "/v1/tickets", { kind: "story", work_type: "feature", title: "Popover story with a long enough title to wrap", parent_id: EPIC() }, owner)).id;
  design = (await call("POST", "/v1/docs", { doc_type: "design", title: "Layout design", body_md: "# Layout\n\n## Rules\nText has room.", scope: EPIC() }, arch)).id;
  report = (await call("POST", "/v1/docs", { doc_type: "note", title: "Evidence note", body_md: "# Evidence\nok", scope: EPIC() }, arch)).id;
  await call("POST", "/v1/links", { from_id: story, to_id: design, relation: "designed_by" }, arch);
  await call("POST", "/v1/messages", { ticket_id: story, kind: "note", text: "A note with a veryveryverylongunbrokenwordthatisstillshorterthanaphone in it." }, arch);
});

// What the board host would answer where the e2e board has nothing: a supervisor with long-named services, a running code-server, agent
// tokens for every seat role. The sweep routes below see these as the owner would on a busy install.
async function populate(page: Page): Promise<void> {
  const ok = (value: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, value, hint: "" }) });
  const svc = (service: string, extra: Record<string, unknown> = {}) => ({ service, state: "up", health: "up", pid: 18244, port: 19400, uptime: "3h 12m", rev: "b242385b", managed: true, ...extra });
  await page.route("**/v1/admin/services", (route) => route.fulfill(ok({
    supervisor: { running: true, control: true },
    services: [svc("board", { note: "the board and its web UI" }), svc("pool", { port: 19300 }), svc("feed-driver-for-the-architect-seat", { note: "restarts with the seat; last restart: the owner asked for it from the Admin console after the 0.10.7 update", rev: "6832c40b" }),
      svc("code-server", { port: 19500, note: "installed, started by heronry start code", autostart: true }), svc("embedder", { state: "down", health: "down", pid: null, port: null, uptime: null }), svc("tailnet-proxy", { managed: false })],
  })));
  await page.route("**/v1/admin/teammates", (route) => route.request().method() === "GET" ? route.fulfill(ok([
    ["maria-del-carmen", "owner", true, true, true, null], ["tobias", "owner", false, false, true, "2026-10-09T14:00:00Z"], ["guest-reviewer", "guest", false, false, false, null], ["dev-ops-lead", "owner", false, false, false, "2026-10-12T10:00:00Z"],
  ].map(([handle, role, admin, init, tok, inv]) => ({ id: handle, handle, role, admin, init_human: init, has_token: tok, last_seen: "2026-10-09T13:00:00Z", invite_expires: inv })))) : route.fallback());
  await page.route("**/v1/admin/tokens/agents", (route) => route.fulfill(ok(["architect", "engineer", "adversary", "reviewer", "qa", "designer"]
    .map((role) => ({ handle: `${role}.epic-0cec8d1c31`, participant_id: `${role}.epic-0cec8d1c31`, role, model: "claude-sonnet-5-5", last_seen: new Date().toISOString(), revoked: false })))));
  await page.route("**/v1/code", (route) => route.request().method() === "GET" ? route.fulfill(ok({ port: 19500, url: "http://127.0.0.1:19500", running: true, version: "4.116.0", default_folder: "C:\Users\owner\heronry", start_command: "heronry start code", installed: true })) : route.fallback());
  // synthetic data only: the real page shows this computer's tailnet name
  await page.route("**/v1/admin/tailnet", (route) => route.fulfill(ok({
    tailscale: { backend: "Running", dns: "example-host.example.ts.net" }, serve: null, serve_proxies: [], public_url: null, tailnet_url: "https://example-host.example.ts.net",
    public_mode: false, blockers: 0, auth_keys: { configured: true },
    rows: [["OK", "tokens.json", "every participant has a token"], ["OK", "humans", "2 people can sign in"], ["OK", "tailscale", "running and signed in"], ["OK", "certificates", "HTTPS is enabled for the tailnet"],
      ["WARN", "funnel", "off: this board is not on the public internet", "nothing to do"], ["OK", "board bind", "127.0.0.1 only"]].map(([level, area, text, fix]) => ({ level, area, text, fix })) })));
  const entry = (harness: string, provider: string) => ({ harness, provider, context_window: 1000000, auto_compact: 800000, effort_cap: "high" });
  await page.route("**/v1/admin/models", (route) => route.request().method() === "GET" ? route.fulfill(ok({
    models: { "claude-fable-5-1": entry("claude", "anthropic"), "claude-opus-5-5": entry("claude", "anthropic"), "gpt-6-sol": entry("codex", "openai") },
    role_models: { engineer: ["claude-opus-5-5", "gpt-6-sol"], adversary: ["claude-fable-5-1"] }, selected: ["claude", "codex"], warnings: [] })) : route.fallback());
  await page.route("**/v1/admin/harnesses**", (route) => route.request().method() === "GET" ? route.fulfill(ok({
    harnesses: [{ harness: "claude", selected: true, installed: true, path: "C:/bin/claude", version: "2.1.0", signed_in: true, latest: "2.2.0", live_seats: [], update: null }],
    selected: ["claude"], fable_ack: null, fable_notice: null })) : route.fallback());
  await page.route("**/v1/code/session", (route) => route.fulfill(ok({ token: "t", expires_at: Date.now() / 1000 + 60 })));
}

const routes = (): Array<[string, string]> => [
  ["epics", "/epics"],
  ["epic", `/epic/${EPIC()}`],
  ["ticket", `/ticket/${story}`],
  ["doc", `/doc/${design}`],
  ["records", `/records/${report}`],
  ["seats", "/seats"],
  ["settings", "/settings"],
  ["admin-services", "/admin?tab=services"],
  ["admin-models", "/admin?tab=models"],
  ["admin-teammates", "/admin?tab=teammates"],
  ["admin-remote", "/admin?tab=remote"],
  ["admin-integrations", "/admin?tab=integrations"],
  ["admin-settings", "/admin?tab=settings"],
  ["code", "/code"],
  ["design", "/design"],
  ["design-standard", "/design?wf=standard@1"],
  ["code-faq", "/code/faq"],
  ...["knowledge", "topics", "documents", "artifacts", "links", "tickets", "pains", "history"].map((s): [string, string] => [`library-${s}`, `/library/${s}`]),
];

// qa 0.10.8 (architect m-7e741f6860): open every <details> on the page, then check what the owner would see inside: no table is wider than a
// frame that does not scroll (its last column cut off), and no single-token word (an id, a handle, a model name) wraps across lines.
async function folds(page: Page): Promise<Offence[]> {
  const n = await page.evaluate(() => { let c = 0; for (const d of Array.from(document.querySelectorAll("details:not([open])"))) { (d as HTMLDetailsElement).open = true; c++; } return c; });
  if (n) await page.waitForTimeout(200);
  return page.evaluate(() => {
    const out: Array<{ path: string; text: string; why: string; box: number; need: number }> = [];
    const name = (el: Element) => `${el.tagName.toLowerCase()}${el.getAttribute("data-testid") ? "[" + el.getAttribute("data-testid") + "]" : ""}`;
    const shown = (el: Element) => { const cs = getComputedStyle(el); return cs.display !== "none" && cs.visibility !== "hidden" && el.getClientRects().length > 0 && !el.closest("[aria-hidden=true], [hidden], .sr-only"); };
    for (const t of Array.from(document.querySelectorAll("table"))) {
      if (!shown(t)) continue;
      const tr = t.getBoundingClientRect();
      let frame: HTMLElement | null = t.parentElement;
      while (frame && frame !== document.body && getComputedStyle(frame).overflowX === "visible") frame = frame.parentElement;
      const scrolls = frame ? ["auto", "scroll"].includes(getComputedStyle(frame).overflowX) : false;
      const right = frame && frame !== document.body ? frame.getBoundingClientRect().right : window.innerWidth;
      if (!scrolls && tr.right > right + 1) out.push({ path: name(t), text: (t.textContent ?? "").trim().slice(0, 40), why: "a table wider than a frame that does not scroll: its last column is cut off", box: Math.round(right), need: Math.round(tr.right) });
    }
    for (const el of Array.from(document.querySelectorAll("main *, [role=dialog] *"))) {
      if (el.children.length || !shown(el)) continue;
      const text = (el.textContent ?? "").trim();
      if (!/^[A-Za-z0-9_.@:/-]{5,}$/.test(text)) continue; // one token: an id, a handle, a model name
      const r = document.createRange(); r.selectNodeContents(el);
      const tops = Array.from(r.getClientRects()).map((q) => Math.round(q.top));
      if (Math.max(...tops) - Math.min(...tops) > 4) out.push({ path: name(el), text, why: "a single word wraps across lines", box: 0, need: 0 });
    }
    // a path, a file name or anything in code that breaks at its hyphen or slash, inside a longer sentence (architect m-7ae758c02c):
    // "docs/operator/remote-access.md" must not read "remote-" / "access.md". Plain hyphenated prose words are left to wrap.
    const walker = document.createTreeWalker(document.querySelector("main") ?? document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const node = n as Text; const parent = node.parentElement;
      if (!parent || !shown(parent) || parent.closest("script, style, pre")) continue;
      const inCode = Boolean(parent.closest("code, kbd, samp"));
      for (const m of node.data.matchAll(/[A-Za-z0-9_.@:/-]{6,}/g)) {
        const tok = m[0];
        const pathLike = /\/|\.[A-Za-z0-9]{2,4}$/.test(tok) && /[-/]/.test(tok);
        if (!(pathLike || (inCode && /-/.test(tok)))) continue;
        const r = document.createRange(); r.setStart(node, m.index!); r.setEnd(node, m.index! + tok.length);
        const tops = Array.from(r.getClientRects()).map((q) => Math.round(q.top));
        if (tops.length && Math.max(...tops) - Math.min(...tops) > 4) out.push({ path: name(parent), text: tok, why: "a path or code token breaks at a hyphen or slash", box: 0, need: 0 });
      }
    }
    return out;
  });
}

interface Offence { path: string; text: string; why: string; box: number; need: number }

async function sweep(page: Page): Promise<Offence[]> {
  return page.evaluate(() => {
    const out: Array<{ path: string; text: string; why: string; box: number; need: number }> = [];
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;left:-9999px;top:0";
    document.body.appendChild(probe);
    const label = (el: Element): string => {
      const id = el.getAttribute("data-testid");
      return `${el.tagName.toLowerCase()}${id ? `[${id}]` : ""}${typeof el.className === "string" && el.className ? "." + el.className.split(/\s+/)[0] : ""}`;
    };
    const skipOverflow = (el: Element): boolean => {
      for (let n: Element | null = el; n && n !== document.body; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (n !== el && /(auto|scroll)/.test(cs.overflowX) && n.scrollWidth > n.clientWidth) return true; // a scroller holds it
      }
      return false;
    };
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      if (el === probe || ["SCRIPT", "STYLE", "NOSCRIPT", "SVG", "PATH"].includes(el.tagName.toUpperCase())) continue;
      const own = Array.from(el.childNodes).filter((n) => n.nodeType === Node.TEXT_NODE).map((n) => n.textContent ?? "").join(" ").replace(/\s+/g, " ").trim();
      if (!own) continue;
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0 || el.getClientRects().length === 0) continue;
      if (el.closest("[aria-hidden=true], [hidden], option, select, textarea, input, .sr-only, pre, code, svg")) continue; // svg labels are drawn, not flowed
      if (cs.clip !== "auto" && cs.position === "absolute" && el.getBoundingClientRect().width <= 1) continue; // visually-hidden helper
      if (cs.textOverflow === "ellipsis") continue; // cut on purpose
      const r = el.getBoundingClientRect();
      const padX = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
      const inner = r.width - padX - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth);
      // longhands: the `font` shorthand reads back as "" when font-variant-numeric is set (tabular-nums), which measured the default 16px
      probe.style.fontFamily = cs.fontFamily; probe.style.fontSize = cs.fontSize; probe.style.fontWeight = cs.fontWeight; probe.style.fontStyle = cs.fontStyle;
      probe.style.letterSpacing = cs.letterSpacing;
      probe.style.textTransform = cs.textTransform;
      let longest = 0, word = "";
      for (const w of own.split(/[\s ]+/)) {
        if (w.length > 24) continue; // a run that long (a hash, a pasted token) may break anywhere; the spill check still covers it
        probe.textContent = w;
        const wd = probe.getBoundingClientRect().width;
        if (wd > longest) { longest = wd; word = w; }
      }
      if (inner + 1 < longest && !skipOverflow(el)) {
        out.push({ path: label(el), text: own.slice(0, 60), why: `narrower than its longest word "${word.slice(0, 30)}"`, box: Math.round(inner), need: Math.round(longest) });
      } else if (el.scrollWidth > el.clientWidth + 1 && /(visible)/.test(cs.overflowX) && cs.display !== "inline" && !skipOverflow(el)) {
        out.push({ path: label(el), text: own.slice(0, 60), why: "text spills outside its box", box: el.clientWidth, need: el.scrollWidth });
      }
    }
    probe.remove();
    return out;
  });
}

// Reach (architect m-45e36d1db6): a tab, button or link that lies outside the viewport sideways, with no scroll cue, cannot be
// found (the Library tabs at 390 left Links, Tickets, Pains and History off-screen); and an input whose placeholder is wider than
// the input shows it cut off (Find at 390). A scroller with a visible scrollbar is the cue: a table that scrolls is fine.
async function reach(page: Page): Promise<Offence[]> {
  return page.evaluate(() => {
    const out: Array<{ path: string; text: string; why: string; box: number; need: number }> = [];
    const name = (el: Element) => `${el.tagName.toLowerCase()}${el.getAttribute("data-testid") ? `[${el.getAttribute("data-testid")}]` : ""}`;
    const cueScroller = (el: Element): boolean => {
      for (let n = el.parentElement; n && n !== document.documentElement; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (/(auto|scroll)/.test(cs.overflowX) && n.scrollWidth > n.clientWidth && cs.scrollbarWidth !== "none") return true;
      }
      return false;
    };
    const vw = document.documentElement.clientWidth;
    for (const el of Array.from(document.querySelectorAll("button, a[href], [role=tab], [role=button]"))) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || el.getClientRects().length === 0) continue;
      if (el.closest("[aria-hidden=true], [hidden], .sr-only")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      if ((r.right > vw + 1 || r.left < -1) && !cueScroller(el)) {
        out.push({ path: name(el), text: (el.textContent ?? "").trim().slice(0, 40), why: "lies outside the viewport with no scroll cue", box: Math.round(r.right), need: vw });
      }
      // a control cut off by the box it sits in (Code header strip, Services table): overflow hidden/clip/auto/scroll on an ancestor
      // that the control reaches past.
      for (let n = el.parentElement; n && n !== document.documentElement; n = n.parentElement) {
        const ps = getComputedStyle(n);
        if (!/(hidden|clip|auto|scroll)/.test(ps.overflowX) || n === document.body || el instanceof SVGElement) continue; // a diagram scrolls by design
        const nr = n.getBoundingClientRect();
        if (r.right > nr.right + 1 || r.left < nr.left - 1) {
          out.push({ path: name(el), text: (el.textContent ?? "").trim().slice(0, 40), why: `is cut off by ${name(n)} (overflow ${ps.overflowX})`, box: Math.round(nr.right), need: Math.round(r.right) });
          break;
        }
      }
    }
    // A crumb or title cut with an ellipsis while the row it sits in has free width for the whole text (qa: /doc "Popover ..." in a
    // card that had room). The free width is what the nearest flex rows above it leave unused.
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const cs = getComputedStyle(el);
      if (cs.textOverflow !== "ellipsis" || cs.overflowX === "visible" || el.getClientRects().length === 0 || cs.visibility === "hidden") continue;
      const lost = el.scrollWidth - el.clientWidth;
      if (lost <= 1) continue;
      let free = 0;
      let row: HTMLElement | null = null;
      let wrapped = false;
      let n: HTMLElement | null = el.parentElement;
      for (let i = 0; n && i < 3; i++, n = n.parentElement) {
        const ps = getComputedStyle(n);
        if (!ps.display.includes("flex") || ps.flexDirection.startsWith("column")) continue;
        if (ps.flexWrap !== "nowrap") { row = null; wrapped = true; break; } // a wrapped row has no single free width
        const used = Array.from(n.children).filter((c) => getComputedStyle(c).display !== "none").reduce((w, c) => w + c.getBoundingClientRect().width, 0);
        const gaps = Math.max(0, n.children.length - 1) * (parseFloat(ps.columnGap) || 0);
        free = Math.max(free, n.clientWidth - parseFloat(ps.paddingLeft) - parseFloat(ps.paddingRight) - used - gaps);
        row = n;
      }
      // the row itself shrank to its content inside a wider column (the /doc card at 450px on a 1088px page)
      const column = el.closest("main");
      if (row && column && !wrapped) free += Math.max(0, column.clientWidth - 48 - row.getBoundingClientRect().width);
      if (free >= lost) out.push({ path: name(el), text: (el.textContent ?? "").trim().slice(0, 40), why: "text is cut off although its row has room for all of it", box: el.clientWidth, need: el.scrollWidth });
    }
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;white-space:pre;left:-9999px;top:0";
    document.body.appendChild(probe);
    for (const el of Array.from(document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input[placeholder], textarea[placeholder]"))) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || el.getClientRects().length === 0 || el.value) continue;
      probe.style.font = cs.font;
      probe.textContent = el.placeholder;
      const need = probe.getBoundingClientRect().width;
      const inner = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      if (inner + 1 < need && el.tagName === "INPUT") out.push({ path: name(el), text: el.placeholder.slice(0, 50), why: "placeholder is wider than its input", box: Math.round(inner), need: Math.round(need) });
      else if (el.tagName === "TEXTAREA" && el.clientHeight < 20) continue;
    }
    probe.remove();
    return out;
  });
}

// Cover: a fixed or sticky overlay (toast, composer, bar) must not lie over a button, link, tab, field or message text. A
// sticky bar sits over what is below it until the page scrolls clear, so sticky overlays are judged with the page scrolled to its
// end, where nothing is left to scroll under them; a fixed one is judged at the top as well. `only` limits it to one overlay.
async function cover(page: Page, only?: string, positions: readonly ("top" | "end")[] = ["top", "end"], pinned = false): Promise<Offence[]> {
  const found: Offence[] = [];
  for (const where of positions) {
    await page.evaluate((w) => window.scrollTo(0, w === "top" ? 0 : document.documentElement.scrollHeight), where);
    await page.waitForTimeout(150);
    const rows = await page.evaluate(({ only, where, pinned }) => {
      const out: Array<{ path: string; text: string; why: string; box: number; need: number }> = [];
      const name = (el: Element) => `${el.tagName.toLowerCase()}${el.getAttribute("data-testid") ? `[${el.getAttribute("data-testid")}]` : ""}`;
      const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
      const overlays = Array.from(document.body.querySelectorAll("*")).filter((el) => {
        const cs = getComputedStyle(el);
        if (cs.position !== "fixed" && cs.position !== "sticky") return false;
        if (cs.display === "none" || cs.visibility === "hidden" || el.getClientRects().length === 0) return false;
        if (el.closest("[aria-hidden=true], [hidden], [role=dialog], dialog")) return false; // a dialog is meant to cover the page
        const r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) return false;
        if (only && !el.matches(only)) return false;
        return cs.position === "fixed" || where === "end" || pinned;
      });
      if (!overlays.length) return out;
      const targets = Array.from(document.body.querySelectorAll("button, a[href], [role=tab], input, select, textarea, [data-testid=thread] li p, [data-quote-region]"));
      for (const t of targets) {
        const cs = getComputedStyle(t);
        if (cs.display === "none" || cs.visibility === "hidden" || t.getClientRects().length === 0) continue;
        if (t.closest("[aria-hidden=true], [hidden], .sr-only")) continue;
        if (overlays.some((o) => o.contains(t) || t.contains(o))) continue; // a control inside the overlay is not covered by it
        const r = t.getBoundingClientRect();
        const x0 = Math.max(0, r.left), x1 = Math.min(vw, r.right), y0 = Math.max(0, r.top), y1 = Math.min(vh, r.bottom);
        if (x1 - x0 < 4 || y1 - y0 < 4) continue;
        const top = document.elementFromPoint((x0 + x1) / 2, (y0 + y1) / 2);
        const over = top ? overlays.find((o) => o.contains(top)) : undefined;
        if (over && !t.contains(top)) out.push({ path: `${name(over)} over ${name(t)}`, text: (t.textContent ?? "").trim().slice(0, 40), why: `covers it (page scrolled to ${where})`, box: Math.round(y0), need: Math.round(y1) });
      }
      return out;
    }, { only, where, pinned });
    found.push(...rows);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  return found;
}

for (const [label, size] of [["390", { width: 390, height: 844 }], ["1280", { width: 1280, height: 800 }]] as const) {
  // Mark: the confirmation takes the composer's status slot. Nothing above the selection may move (more than 2px), nothing may
  // lie over a button, field or message, and the slot restores itself.
  test(`marking a requirement moves nothing above it and covers nothing, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.addInitScript(() => { try { localStorage.setItem("edp8.ui.owner.composer-collapsed", "0"); } catch { /* blocked */ } }); // the composer open: its tallest state
    await page.goto(`${BASE()}/ui/ticket/${story}?as=owner`);
    await page.waitForTimeout(900);
    await page.evaluate((text) => {
      const w = document.createTreeWalker(document.querySelector("[data-testid=thread]")!, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const at = (n as Text).data.indexOf(text);
        if (at < 0) continue;
        const r = document.createRange(); r.setStart(n, at); r.setEnd(n, at + text.length);
        const sel = window.getSelection()!; sel.removeAllRanges(); sel.addRange(r);
        document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
        return;
      }
    }, "A note with a");
    await expect(page.getByTestId("quote-popover")).toBeVisible();
    // every visible element that lies above the selection, and where it is now
    await page.evaluate(() => {
      const sel = window.getSelection()!.getRangeAt(0).getBoundingClientRect();
      const keep: Array<[Element, number, number]> = [];
      for (const el of Array.from(document.body.querySelectorAll("*"))) {
        if (el.closest("[data-testid=quote-popover]")) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1 || r.bottom > sel.top) continue;
        keep.push([el, Math.round(r.top + window.scrollY), Math.round(r.left + window.scrollX)]);
      }
      (window as unknown as { __above: typeof keep }).__above = keep;
    });
    await page.getByTestId("quote-popover-mark").click();
    await expect(page.getByTestId("composer-flash")).toHaveText("Requirement marked."); // trigger it first, then look
    const moved = await page.evaluate(() => (window as unknown as { __above: Array<[Element, number, number]> }).__above
      .map(([el, top, left]) => ({ el, dy: Math.abs(Math.round(el.getBoundingClientRect().top + window.scrollY) - top), dx: Math.abs(Math.round(el.getBoundingClientRect().left + window.scrollX) - left) }))
      .filter((m) => m.el.isConnected && (m.dy > 2 || m.dx > 2))
      .map((m) => `${m.el.tagName.toLowerCase()}${m.el.getAttribute("data-testid") ? "[" + m.el.getAttribute("data-testid") + "]" : ""} moved ${m.dy}px down/up, ${m.dx}px sideways`));
    const found = await cover(page, undefined, ["end"]);
    fs.mkdirSync(EVIDENCE, { recursive: true });
    await page.screenshot({ path: path.join(EVIDENCE, `mark-${label}.png` ) });
    expect(moved, "nothing above the selection moves when Mark confirms").toEqual([]);
    expect(found.map((o) => `${o.path} "${o.text}" ${o.why}`), "nothing lies under the composer").toEqual([]);
    await expect(page.getByTestId("composer-flash")).toHaveCount(0, { timeout: 8000 }); // the slot restores itself
  });

  test(`no visible text is narrower than its longest word or spills its box, on every route at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    fs.mkdirSync(EVIDENCE, { recursive: true });
    const bad: string[] = [];
    await populate(page);
    for (const [name, url] of routes()) {
      await page.goto(`${BASE()}/ui${url}${url.includes("?") ? "&" : "?"}as=owner`);
      await page.waitForTimeout(900); // the page settles (live feeds never go network-idle)
      // every state of the page: the route as loaded, then each of its tabs in turn (qa 0.10.7: only the first tab was ever swept)
      const tabs = await page.locator("[role=tab]").count();
      for (let t = -1; t < tabs; t++) {
        if (t >= 0) {
          const tab = page.locator("[role=tab]").nth(t);
          if (!(await tab.isVisible()) || (await tab.getAttribute("aria-selected")) === "true") continue;
          await tab.click();
          await page.waitForTimeout(400);
        }
        const state = t < 0 ? name : `${name}/tab${t}`;
        if (t < 0 && name === "admin-teammates") await page.getByTestId("teammate-tobias").scrollIntoViewIfNeeded();
        if (t < 0 && ["code", "admin-services", "admin-teammates"].includes(name)) await page.screenshot({ path: path.join(EVIDENCE, `ok-${name}-${label}.png`) }); // the fixed screens, as evidence
        const extra = [...await reach(page), ...await cover(page), ...await folds(page)];
        const found = await sweep(page);
        if (found.length || extra.length) {
          await page.screenshot({ path: path.join(EVIDENCE, `${state.replace("/", "-")}-${label}.png`), fullPage: false });
          for (const o of extra) bad.push(`${state}@${label}: ${o.path} "${o.text}" ${o.why} (${o.box}, ${o.need})`);
          for (const o of found) bad.push(`${state}@${label}: ${o.path} "${o.text}" ${o.why} (box ${o.box}px, needs ${o.need}px)`);
        }
      }
    }
    expect(bad, bad.join("\n")).toEqual([]);
  });
}

// qa report-138db92cad: the FIRST Mark on an epic used to insert an "Open requirements" line above the thread and push it down 50px.
// The count now lives in the header's Needs attention field. Run the Mark on an epic with NO open requirement, then on the same epic
// with one: nothing above the selection may move more than 2px either time.
async function markAndMeasure(page: Page, text: string): Promise<string[]> {
  await page.evaluate((t) => {
    const w = document.createTreeWalker(document.querySelector("[data-testid=thread]")!, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const at = (n as Text).data.indexOf(t);
      if (at < 0) continue;
      const r = document.createRange(); r.setStart(n, at); r.setEnd(n, at + t.length);
      const sel = window.getSelection()!; sel.removeAllRanges(); sel.addRange(r);
      document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      return;
    }
  }, text);
  await expect(page.getByTestId("quote-popover")).toBeVisible();
  await page.evaluate(() => {
    const sel = window.getSelection()!.getRangeAt(0).getBoundingClientRect();
    const keep: Array<[Element, number, number]> = [];
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      if (el.closest("[data-testid=quote-popover]")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1 || r.bottom > sel.top) continue;
      keep.push([el, Math.round(r.top + window.scrollY), Math.round(r.left + window.scrollX)]);
    }
    (window as unknown as { __above: typeof keep }).__above = keep;
  });
  await page.getByTestId("quote-popover-mark").click();
  await expect(page.getByTestId("quote-popover")).toHaveCount(0);
  await page.waitForTimeout(1500); // the requirements list refetches; a late banner would land here
  return page.evaluate(() => (window as unknown as { __above: Array<[Element, number, number]> }).__above
    .map(([el, top, left]) => ({ el, dy: Math.abs(Math.round(el.getBoundingClientRect().top + window.scrollY) - top), dx: Math.abs(Math.round(el.getBoundingClientRect().left + window.scrollX) - left) }))
    .filter((m) => m.el.isConnected && (m.dy > 2 || m.dx > 2))
    .map((m) => `${m.el.tagName.toLowerCase()}${m.el.getAttribute("data-testid") ? "[" + m.el.getAttribute("data-testid") + "]" : ""} moved ${m.dy}px down/up, ${m.dx}px sideways`));
}

for (const [label, size] of [["1280", { width: 1280, height: 800 }], ["390", { width: 390, height: 844 }]] as const) {
  test(`the first Mark on an epic with no open requirement moves nothing above it, at ${label}px`, async ({ page }) => {
    await page.setViewportSize(size);
    fs.mkdirSync(EVIDENCE, { recursive: true });
    const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: `First mark epic ${label}` }, owner)).id;
    await call("POST", "/v1/messages", { ticket_id: epic, kind: "note", text: "Requirement one: the export must keep every column. Requirement two: the import must report each skipped row." }, arch);
    await page.addInitScript(() => { try { localStorage.setItem("edp8.ui.owner.composer-collapsed", "0"); } catch { /* blocked */ } });
    await page.goto(`${BASE()}/ui/epic/${epic}?as=owner`);
    await page.waitForTimeout(900);
    await expect(page.getByTestId("work-attention")).toContainText("Nothing open");
    await page.screenshot({ path: path.join(EVIDENCE, `first-mark-before-${label}.png`) });
    const first = await markAndMeasure(page, "the export must keep every column");
    await expect(page.getByTestId("work-attention")).toContainText("1 open requirement");
    await expect(page.getByTestId("requirements-chip-open")).toHaveText("Open the list");
    await page.screenshot({ path: path.join(EVIDENCE, `first-mark-after-${label}.png`) });
    expect(first, "nothing above the selection moves on the first mark").toEqual([]);
    const second = await markAndMeasure(page, "the import must report each skipped row");
    await expect(page.getByTestId("work-attention")).toContainText("2 open requirements");
    expect(second.filter((m) => !m.startsWith("a[requirements-chip-open]")), "nothing above the selection moves on the second mark (the count itself changes its own link)").toEqual([]);
    expect(await page.getByText("the epic cannot finish until the architect links each one", { exact: false }).count(), "no separate banner line").toBe(0);
  });
}
