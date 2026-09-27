// S22 performance trace (one script, the installed Chromium; NOT the e2e suite). Against a PRIVATE board
// (scripts/perf/private_board.py) it loads each main page cold and records:
//   * initial JS/CSS bytes (encoded, as transferred) and every /v1 call with its duration,
//   * long tasks over 50 ms (PerformanceObserver 'longtask'),
//   * React commits (a devtools-hook shim counts onCommitFiberRoot),
// then, on the epic view, posts N notes through the API and counts React commits and /v1 refetches per event.
//
//   node web/scripts/perf-trace.mjs --base http://127.0.0.1:PORT --token-file <dir>/tokens.json \
//        --epic epic-… --ticket s-… --out trace.json [--events 20]
import { chromium } from "@playwright/test";
import fs from "node:fs";

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const base = arg("base");
const token = JSON.parse(fs.readFileSync(arg("token-file"), "utf8")).owner;
const epic = arg("epic");
const ticket = arg("ticket");
const nEvents = Number(arg("events", "20"));
const out = arg("out", "trace.json");
const H = { "X-Participant": "owner", "X-Token": token, "Content-Type": "application/json" };

const INIT = `
  window.__perf = { longtasks: [], commits: 0 };
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__perf.longtasks.push(Math.round(e.duration)); })
      .observe({ type: "longtask", buffered: true });
  } catch {}
  let nextId = 1;
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
    supportsFiber: true, renderers: new Map(), isDisabled: false,
    inject(r) { const id = nextId++; this.renderers.set(id, r); return id; },
    checkDCE() {}, onScheduleFiberRoot() {}, onCommitFiberUnmount() {}, onPostCommitFiberRoot() {},
    onCommitFiberRoot() { window.__perf.commits++; },
  };
`;

const pages = [
  ["epics", "/ui/epics"],
  ["epic", `/ui/epic/${epic}`],
  ["ticket", `/ui/ticket/${ticket}`],
  ["admin", "/ui/admin"],
  ["design", "/ui/design"],
  ["code", "/ui/code"],
];

const browser = await chromium.launch();
const result = { base, pages: {}, events: null };
try {
  for (const [name, path] of pages) {
    const ctx = await browser.newContext();
    await ctx.addInitScript(INIT);
    const page = await ctx.newPage();
    const reqs = [];
    let pending = 0, lastDone = Date.now();
    const isApi = (u) => { const p = new URL(u).pathname; return p.startsWith("/v1/") && !p.startsWith("/v1/feed"); };
    page.on("request", (r) => { if (isApi(r.url())) pending++; });
    page.on("requestfailed", (r) => { if (isApi(r.url())) { pending--; lastDone = Date.now(); } });
    page.on("requestfinished", (r) => { if (isApi(r.url())) { pending--; lastDone = Date.now(); } });
    const settle = async () => { while (pending > 0 || Date.now() - lastDone < 1000) await page.waitForTimeout(100); };
    const assets = { js: 0, css: 0, jsFiles: 0 };
    page.on("requestfinished", async (req) => {
      const u = new URL(req.url());
      const t = req.timing();
      const size = (await req.sizes().catch(() => null))?.responseBodySize ?? 0;
      if (u.pathname.startsWith("/v1/") && !u.pathname.startsWith("/v1/feed")) {
        reqs.push({ path: u.pathname, ms: Math.round(t.responseEnd), bytes: size });
      } else if (u.pathname.endsWith(".js")) { assets.js += size; assets.jsFiles++; }
      else if (u.pathname.endsWith(".css")) assets.css += size;
    });
    // first visit carries the session (?as&token); the SPA strips the token from the bar
    const t0 = Date.now();
    await page.goto(`${base}${path}?as=owner&token=${encodeURIComponent(token)}`, { waitUntil: "load" });
    await page.waitForTimeout(300);
    await settle();
    const loadMs = Date.now() - t0 - 1000;
    const perf = await page.evaluate(() => window.__perf);
    // navigation milestones (ms from navigation start): where a slower settle comes from
    const nav = await page.evaluate(() => {
      const n = performance.getEntriesByType("navigation")[0];
      const api = performance.getEntriesByType("resource").filter((r) => new URL(r.name).pathname.startsWith("/v1/")
        && !new URL(r.name).pathname.startsWith("/v1/feed"));
      const js = performance.getEntriesByType("resource").filter((r) => r.name.endsWith(".js"));
      const r = (x) => Math.round(x);
      return { dcl: r(n.domContentLoadedEventEnd), load: r(n.loadEventEnd),
               lastJsEnd: r(Math.max(0, ...js.map((e) => e.responseEnd))),
               firstApiStart: r(Math.min(...api.map((e) => e.startTime))), lastApiEnd: r(Math.max(...api.map((e) => e.responseEnd))),
               apiSpans: api.map((e) => [new URL(e.name).pathname.split("/").pop().slice(0, 12), r(e.startTime), r(e.responseEnd)]),
               jsSpans: js.map((e) => [e.name.split("/").pop().slice(0, 14), r(e.startTime), r(e.responseEnd)]) };
    });
    result.pages[name] = { loadMs, nav, ...assets, longtasks: perf.longtasks.length, longtaskMs: perf.longtasks,
                           commits: perf.commits, api: reqs };
    if (name === "epic") {
      // live refresh: N notes on the ticket, 1 s apart; count commits and /v1 refetches they cause
      const before = { commits: perf.commits, api: reqs.length };
      for (let i = 0; i < nEvents; i++) {
        await fetch(`${base}/v1/messages`, { method: "POST", headers: H,
          body: JSON.stringify({ kind: "note", ticket_id: ticket, text: `perf probe ${i}` }) });
        await page.waitForTimeout(1000);
      }
      await page.waitForTimeout(2000);
      const after = await page.evaluate(() => window.__perf);
      result.events = { events: nEvents, commits: after.commits - before.commits,
                        refetches: reqs.length - before.api,
                        commitsPerEvent: +((after.commits - before.commits) / nEvents).toFixed(2),
                        refetchesPerEvent: +((reqs.length - before.api) / nEvents).toFixed(2),
                        refetchPaths: Object.entries(reqs.slice(before.api).reduce((m, r) => ((m[r.path] = (m[r.path] ?? 0) + 1), m), {})),
                        longtasksDuring: after.longtasks.length - perf.longtasks.length };
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}
fs.writeFileSync(out, JSON.stringify(result, null, 1));
for (const [n, p] of Object.entries(result.pages)) {
  console.log(`${n.padEnd(7)} load ${p.loadMs} ms  nav ${JSON.stringify({ ...p.nav, apiSpans: undefined, jsSpans: undefined })}  js ${(p.js / 1024).toFixed(0)} KB (${p.jsFiles} files)  longtasks ${p.longtasks} [${p.longtaskMs.join(",")}]  commits ${p.commits}  api ${p.api.length}`);
}
console.log("events", JSON.stringify(result.events));
