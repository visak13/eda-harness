// t-6356c06c40 live look (criterion c-717675b8d6): the LIVE /ui/code on :9400 reopens code-server's
// last folder instead of always v8. In Chromium, as the running seat:
//   form     : which folder form the server-side default would redirect to (`C:\...` from a CLI
//              positional via path.resolve, vs the SPA's `/c:/...`): each is opened in the frame and
//              the Source Control view is read (a phantom workspace shows no repository).
//   live     : 1. a plain /ui/code frames code-server with NO folder param;
//              2. File: Open Folder... picks another folder (v8/web) in the frame;
//              3. reloading /ui/code reopens that folder (the frame's redirected URL + Explorer root);
//              4. a deep link (?folder=v8&file=README.md&line=3) opens its own folder at line 3;
//              The deep link last leaves the owner's last folder at v8.
//   nohistory: 5. right after `.\edp.ps1 restart code` with coder.json's `query` removed, start-code
//              seeded v8 and a plain /ui/code opens v8 as the git repository.
//   node measure/t6356-lastfolder-live.cjs form|live|nohistory
// Screenshots + run.log: e2e/evidence/t6356-lastfolder-live/<mode>/ (gitignored).
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const BOARD = process.env.EDP8_BOARD_URL ?? "http://127.0.0.1:9400";
const SEAT = process.env.EDP_HANDLE;
const BRANCH = require("node:child_process").execSync("git branch --show-current", { cwd: __dirname }).toString().trim();
const TOKEN = process.env.EDP8_TOKEN;
const V8 = path.resolve(__dirname, "..", "..");
const CODER_JSON = path.join(V8, ".data", "code", "user", "coder.json");
const slashC = (p) => "/" + p.replace(/\\/g, "/").replace(/^([A-Za-z]):/, (_, d) => `${d.toLowerCase()}:`);
const mode = process.argv[2] ?? "live";
const OUT = path.join(__dirname, "..", "e2e", "evidence", "t6356-lastfolder-live", mode);
fs.mkdirSync(OUT, { recursive: true });
const logf = path.join(OUT, "run.log");
fs.writeFileSync(logf, "");
const L = (s) => { const l = `${new Date().toISOString()} ${s}`; console.log(l); fs.appendFileSync(logf, l + "\n"); };
let fails = 0;
const check = (ok, what) => { L(`${ok ? "PASS" : "FAIL"} ${what}`); if (!ok) fails++; };

(async () => {
  if (!SEAT || !TOKEN) throw new Error("EDP_HANDLE and EDP8_TOKEN must be set (the running seat)");
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
  L(`browser chromium ${browser.version()}`);
  const shot = (n) => page.screenshot({ path: path.join(OUT, `${n}.png`) });
  const f = page.frameLocator("iframe").first();
  const codeFrame = () => page.frames().find((fr) => /:9410\//.test(fr.url()));
  const frameQuery = () => { const u = new URL(codeFrame()?.url() ?? "about:blank"); return u.searchParams; };
  const workbench = async () => {
    await f.locator("div.monaco-workbench").waitFor({ timeout: 90000 });
    await page.waitForTimeout(5000);
  };
  const quick = f.locator(".quick-input-widget");
  const cmd = async (t) => {
    for (let i = 0; i < 5 && !(await quick.isVisible()); i++) { await f.locator("div.monaco-workbench").press("F1"); await page.waitForTimeout(700); }
    await quick.locator("input").fill(`>${t}`);
    await page.waitForTimeout(800);
    await quick.locator("input").press("Enter");
  };
  const explorerRoot = async () => {
    await cmd("View: Show Explorer");
    await page.waitForTimeout(1500);
    return ((await f.locator(".explorer-folders-view .pane-header, .pane-header[aria-label*='Explorer'], .split-view-view .pane-header").allInnerTexts()).join(" | ")).replace(/\s+/g, " ");
  };
  const scmText = async () => {
    await cmd("View: Show Source Control");
    await page.waitForTimeout(4000);
    return (await f.locator(".part.sidebar").innerText()).replace(/\s+/g, " ");
  };
  // the Changes rows' descriptions: a subfolder when the root is the repository, the full path when
  // degraded (the Graph pane is left out: commit subjects may quote a C:\ path)
  const absChange = async () => {
    const d = await f.locator(".scm-view .monaco-list-row .label-description").allInnerTexts();
    L(`  ${d.length} change descriptions read`);
    return d.find((t) => /[A-Za-z]:\\/.test(t)) ?? null;
  };
  const openUi = async (search = "") => {
    const sep = search ? "&" : "?";
    await page.goto(`${BOARD}/ui/code${search}${sep}as=${encodeURIComponent(SEAT)}&token=${encodeURIComponent(TOKEN)}`);
    await page.locator("iframe").first().waitFor({ timeout: 30000 });
    await workbench();
  };
  try {
    if (mode === "form") {
      await openUi();
      for (const [name, folder] of [["slashc", slashC(V8)], ["backslash", V8]]) {
        const src = `http://127.0.0.1:9410/?folder=${encodeURIComponent(folder)}`;
        await page.locator("iframe").first().evaluate((el, s) => { el.src = s; }, src);
        await page.waitForTimeout(1000);
        await workbench();
        L(`${name}: frame url ${codeFrame()?.url()}`);
        const scm = await scmText();
        L(`${name}: scm "${scm.slice(0, 300)}"`);
        await shot(`form-${name}`);
        // healthy = the repository's branch, and its changes listed relative (a degraded root lists each by full path)
        const abs = await absChange();
        L(`${name}: first change listed by absolute path: ${abs ?? "none"}`);
        const healthy = scm.includes(`on "${BRANCH}"`) && !/no source control providers|initialize repository|open a folder/i.test(scm) && !abs;
        check(name === "slashc" ? healthy : !healthy, name === "slashc"
          ? `${name}: the SPA's /c:/ form opens v8 as the git repository, changes listed relative`
          : `${name}: the C:\\ form a CLI positional redirects to is degraded (changes listed by full path), so no positional default`);
      }
    } else if (mode === "nohistory") {
      // run right after `.\edp.ps1 restart code` with coder.json's query removed: start-code seeds v8
      const q = JSON.parse(fs.readFileSync(CODER_JSON, "utf8")).query ?? null;
      L(`5 coder.json query at start = ${JSON.stringify(q)}`);
      check(q?.folder === slashC(V8), "5 start-code seeded the /c:/ v8 default into an empty history");
      await openUi();
      L(`5 iframe src ${await page.locator("iframe").first().getAttribute("src")}; frame url ${codeFrame()?.url()}`);
      check((frameQuery().get("folder") ?? "") === slashC(V8), "5 with no code-server history a plain /ui/code opens v8 (in the /c:/ form)");
      const scm = await scmText();
      L(`5 scm "${scm.slice(0, 300)}"`);
      const abs = await absChange();
      L(`5 first change listed by absolute path: ${abs ?? "none"}`);
      check(scm.includes(`on "${BRANCH}"`) && !/no source control providers|initialize repository|open a folder/i.test(scm) && !abs,"5 the v8 default opens as the git repository (changes listed relative, not by full path)");
      await shot("5-no-history-v8");
    } else {
      const other = path.join(V8, "web");
      // 1. a plain open carries no folder param
      await openUi();
      const src = await page.locator("iframe").first().getAttribute("src");
      L(`1 iframe src ${src}`);
      check(src === "http://127.0.0.1:9410/", "1 a plain /ui/code frames code-server with no folder param");
      L(`1 frame url after redirect ${codeFrame()?.url()}`);
      // 2. open another folder through the workbench (File: Open Folder...)
      await cmd("File: Open Folder...");
      await quick.locator("input").waitFor({ timeout: 15000 });
      await quick.locator("input").fill(other.replace(/\\/g, "/") + "/");
      await page.waitForTimeout(1200);
      await shot("2-open-folder-dialog");
      await quick.locator("input").press("Enter");
      await page.waitForTimeout(1500);
      const ok = quick.locator(".quick-input-action a, a.monaco-button, .monaco-button", { hasText: /^OK$/ });
      if (await ok.count()) await ok.first().click().catch(() => {});
      await page.waitForFunction(() => true);
      await page.waitForTimeout(3000);
      await workbench();
      L(`2 frame url after Open Folder ${codeFrame()?.url()}`);
      // the simple dialog once settled on a neighbour (eda-base3); any folder but v8 proves the point
      const opened = frameQuery().get("folder") ?? "";
      const isV8 = (x) => x.toLowerCase().replace(/\\/g, "/").replace(/^\/?/, "/") === slashC(V8).toLowerCase();
      check(!!opened && !isV8(opened), `2 Open Folder navigated the frame to another folder (${opened}; asked for v8/web)`);
      await shot("2-opened-web");
      // 3. reload the tab: code-server reopens v8/web
      await openUi();
      L(`3 frame url after reload ${codeFrame()?.url()}`);
      const reopened = frameQuery().get("folder") ?? "";
      check(reopened.toLowerCase() === opened.toLowerCase() && !isV8(reopened), `3 reloading /ui/code reopens the last folder (${reopened}), not v8`);
      const root = await explorerRoot();
      L(`3 explorer "${root}"`);
      const leaf = opened.split("/").pop() ?? "";
      check(!!leaf && root.toUpperCase().split(" | ")[0] === leaf.toUpperCase(), `3 the Explorer root is ${leaf}`);
      await shot("3-reload-reopens-web");
      // 4. a deep link opens its own folder at its line
      await openUi(`?folder=${encodeURIComponent(V8)}&file=README.md&line=3`);
      await page.waitForTimeout(3000);
      L(`4 frame url ${codeFrame()?.url()}`);
      check((frameQuery().get("folder") ?? "") === slashC(V8), "4 the deep link opens its own folder (v8)");
      const tab = await f.locator(".tabs-container .tab.active").innerText().catch(() => "");
      const status = await f.locator(".statusbar").innerText().catch(() => "");
      L(`4 active tab "${tab.trim()}" status "${status.replace(/\s+/g, " ").slice(0, 200)}"`);
      check(/README\.md/.test(tab) && /Ln 3\b/.test(status), "4 README.md is open at line 3");
      await shot("4-deeplink-readme-l3");
    }
  } catch (e) {
    L(`FAIL error ${String(e.message ?? e).slice(0, 400)}`);
    fails++;
    await shot("error").catch(() => {});
  }
  await browser.close();
  L(fails ? `RESULT FAIL ${fails}` : "RESULT PASS");
  process.exit(fails ? 1 : 0);
})();
