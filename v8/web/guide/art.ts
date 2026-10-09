// The demo's two attachments, made in a real browser: a phone screenshot of a Japanese conflict screen and a short
// screen recording. Shared by the guide specs (guide.spec.ts, vscode.spec.ts).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "@playwright/test";

export const CHROMIUM =
  process.env.EDP8_CHROMIUM ??
  path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1234", "chrome-win64", "chrome.exe");

/** The two attachments, made in a real browser: a phone screenshot of the conflict screen and a short recording. */
export async function makeArt(): Promise<{ conflictPng: Uint8Array; replayWebm: Uint8Array }> {
  const browser = await chromium.launch({ executablePath: CHROMIUM });
  const phone = await browser.newPage({ viewport: { width: 360, height: 640 }, deviceScaleFactor: 2 });
  await phone.setContent(CONFLICT_HTML);
  const conflictPng = await phone.screenshot();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "guide-video-"));
  const ctx = await browser.newContext({ viewport: { width: 640, height: 360 }, recordVideo: { dir, size: { width: 640, height: 360 } } });
  const rec = await ctx.newPage();
  await rec.setContent(REPLAY_HTML);
  await rec.waitForTimeout(4200);
  const video = rec.video()!;
  await ctx.close();
  const replayWebm = fs.readFileSync(await video.path());
  await browser.close();
  fs.rmSync(dir, { recursive: true, force: true });
  return { conflictPng, replayWebm };
}

const CONFLICT_HTML = `<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;font-family:"Yu Gothic UI","Meiryo","Segoe UI",sans-serif;background:#f6f3ee;color:#222}
header{background:#1f4e5a;color:#fff;padding:14px 16px;font-size:17px;font-weight:600}
.card{background:#fff;margin:12px;border-radius:12px;padding:14px;box-shadow:0 1px 3px #0002}
.who{font-size:12px;color:#667;margin-bottom:6px}.txt{font-size:15px;line-height:1.5}
button{display:block;width:100%;margin-top:10px;padding:10px;border:0;border-radius:8px;background:#1f4e5a;color:#fff;font-size:15px}
.hint{font-size:13px;color:#667;margin:12px 16px}
</style></head><body><header>この段落は2台で編集されました</header>
<p class="hint">どちらの版を残しますか？もう一方は履歴に残ります。</p>
<div class="card"><div class="who">スマートフォン・14:02（機内）</div><div class="txt">羽田に着いたら、ホテルの住所をタクシーの運転手に見せる。チェックインは15時から、朝食は7時から10時まで。</div><button>この版を残す</button></div>
<div class="card"><div class="who">ノートPC・14:20</div><div class="txt">羽田に着いたら、ホテルの住所をタクシーの運転手に見せる。チェックインは15時から。</div><button>この版を残す</button></div>
</body></html>`;

const REPLAY_HTML = `<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;font-family:"Segoe UI",sans-serif;background:#10262c;color:#e8f1f2;display:flex;gap:16px;padding:18px;box-sizing:border-box;height:100vh}
.dev{flex:1;background:#173840;border-radius:12px;padding:12px}.dev h3{margin:0 0 8px;font-size:14px;color:#9cc7cf}
p{margin:6px 0;padding:6px 8px;border-radius:6px;background:#1f4a54;font-size:13px;transition:all .6s}
.gone{opacity:.15;text-decoration:line-through}.sync{position:fixed;bottom:10px;left:0;right:0;text-align:center;font-size:13px;color:#9cc7cf}
</style></head><body>
<div class="dev"><h3>Phone (offline)</h3><p>Packing list</p><p id="a">Charger and adapter</p><p>Passport</p></div>
<div class="dev"><h3>Laptop</h3><p>Packing list</p><p id="b">Charger and adapter</p><p>Passport</p></div>
<div class="sync" id="s">phone deletes a paragraph while offline…</div>
<script>
setTimeout(()=>{document.getElementById('a').className='gone'},900);
setTimeout(()=>{document.getElementById('s').textContent='both devices sync…'},1900);
setTimeout(()=>{document.getElementById('b').className='gone';document.getElementById('s').textContent='the paragraph stays deleted on both'},2900);
</script></body></html>`;
