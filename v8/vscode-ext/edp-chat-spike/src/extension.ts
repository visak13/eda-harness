// C1 spike (s-a8f1b90d2f), throwaway: measures placement, webview CSP + postMessage per browser,
// the board feed from the Node host, and the diff commands. Not the chat (that is C3).
import * as vscode from 'vscode';
import { randomBytes } from 'node:crypto';
import { appendFileSync } from 'node:fs';
import type { API, Change, GitExtension, Repository } from './git';

let out: vscode.OutputChannel;
function log(line: string) {
  const l = `${new Date().toISOString()} ${line}`;
  out.appendLine(l);
  const f = vscode.workspace.getConfiguration('edpSpike').get<string>('logFile');
  if (f) { try { appendFileSync(f, l + '\n'); } catch { /* best effort */ } }
}

type Variant = 'external' | 'inline';

function html(web: vscode.Webview, media: vscode.Uri, variant: Variant, where: string, padKb = 0): string {
  const nonce = randomBytes(16).toString('base64');
  const csp = `default-src 'none'; img-src ${web.cspSource}; style-src ${web.cspSource} 'nonce-${nonce}'; script-src 'nonce-${nonce}';`;
  const css = `body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);padding:8px}
#status{font-weight:bold}.ok{color:var(--vscode-testing-iconPassed)}.bad{color:var(--vscode-errorForeground)}
li{margin:4px 0;padding:4px;border-left:3px solid var(--vscode-focusBorder)}`;
  const js = `(function(){const vs=acquireVsCodeApi();const s=document.getElementById('status');
const ua=navigator.userAgent;document.getElementById('ua').textContent=ua;
let t0=performance.now();
window.addEventListener('message',e=>{const m=e.data;
 if(m.type==='pong'){const rtt=Math.round(performance.now()-t0);s.textContent='round-trip OK '+rtt+' ms';s.className='ok';vs.postMessage({type:'ack',rtt,ua});}
 if(m.type==='feed'){const li=document.createElement('li');li.textContent=m.text;document.getElementById('feed').appendChild(li);}
});
s.textContent='script ran, waiting for pong';t0=performance.now();vs.postMessage({type:'ready',ua});})();`;
  const head = variant === 'external'
    ? `<link rel="stylesheet" href="${web.asWebviewUri(vscode.Uri.joinPath(media, 'spike.css'))}">`
    : `<style nonce="${nonce}">${css}</style>`;
  const script = variant === 'external'
    ? `<script nonce="${nonce}" src="${web.asWebviewUri(vscode.Uri.joinPath(media, 'spike.js'))}"></script>`
    : `<script nonce="${nonce}">${padKb ? `/*${'x'.repeat(padKb * 1024)}*/` : ''}${js}</script>`;  // pad = inline size-ceiling probe
  return `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">${head}</head><body>
<h3>EDP chat spike: ${where}</h3><div>assets: <b id="variant">${variant}${padKb ? ` +${padKb} KB` : ''}</b></div>
<div id="status" class="bad">script did not run</div><div><small id="ua"></small></div>
<ul id="feed"></ul>${script}</body></html>`;
}

// media/spike.css and media/spike.js are byte copies of the css/js strings above (variant A serves
// them via asWebviewUri, variant B inlines them), so the two variants differ only in delivery.

function wire(web: vscode.Webview, variant: () => Variant, where: string) {
  return web.onDidReceiveMessage((m: { type?: string; rtt?: number; ua?: string }) => {
    if (m?.type === 'ready') { log(`${where} ready variant=${variant()} ua=${m.ua}`); void web.postMessage({ type: 'pong' }); }
    else if (m?.type === 'ack') log(`${where} ROUNDTRIP ok rtt=${m.rtt}ms variant=${variant()} ua=${m.ua}`);
    else log(`${where} dropped unknown message`);
  });
}

class SpikeView implements vscode.WebviewViewProvider {
  view?: vscode.WebviewView;
  variant: Variant = 'external';
  padKb = 0;
  constructor(private media: vscode.Uri) {}
  resolveWebviewView(v: vscode.WebviewView) {
    this.view = v;
    v.webview.options = { enableScripts: true, localResourceRoots: [this.media] };
    wire(v.webview, () => this.variant, 'view');
    this.render();
    log(`view resolved (location: secondarySidebar contribution)`);
  }
  render() { if (this.view) this.view.webview.html = html(this.view.webview, this.media, this.variant, 'view', this.padKb);
    log(`view html set: ${this.view?.webview.html.length} chars`); }
  post(text: string) { void this.view?.webview.postMessage({ type: 'feed', text }); }
}

let feedCtrl: AbortController | undefined;

async function feedProbe(view: SpikeView) {
  const cfg = vscode.workspace.getConfiguration('edpSpike');
  const board = cfg.get<string>('boardUrl')!, ticket = cfg.get<string>('ticket')!;
  const participant = await vscode.window.showInputBox({ title: 'Spike: participant id', ignoreFocusOut: true });
  if (!participant) return;
  // empty = header-only (a pre-token agent seat; the board is not in public mode)
  const token = await vscode.window.showInputBox({ title: 'Spike: token (empty = none)', password: true, ignoreFocusOut: true });
  if (token === undefined) return;
  feedCtrl?.abort();
  const ctrl = feedCtrl = new AbortController();
  const t0 = Date.now();
  log(`feed probe start watch=true ticket=${ticket} participant=${participant} x-token=${token ? 'sent' : 'none'}`);
  try {
    const res = await fetch(new URL('/v1/feed?since=-1&watch=true', board), {
      headers: { 'X-Participant': participant, ...(token ? { 'X-Token': token } : {}) }, signal: ctrl.signal, redirect: 'error',
    });
    log(`feed HTTP ${res.status} after ${Date.now() - t0}ms`);
    if (!res.ok || !res.body) return;
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buf = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) { log('feed stream closed'); return; }
      buf += value;
      let i: number;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, i); buf = buf.slice(i + 2);
        const data = frame.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trimStart()).join('\n');
        if (!data) { log(`feed comment ${frame.slice(0, 40)}`); continue; }
        const ev = JSON.parse(data) as { seq: number; kind: string; subject_id?: string; created_at?: string; data?: { text?: string; preview?: string } };
        if (ev.subject_id !== ticket) continue;
        const lag = ev.created_at ? Date.now() - Date.parse(ev.created_at) : NaN;
        const text = ev.data?.preview ?? ev.data?.text ?? '';
        log(`FEED seq=${ev.seq} kind=${ev.kind} subject=${ev.subject_id} lag=${lag}ms text=${JSON.stringify(text).slice(0, 120)}`);
        view.post(`${ev.kind} seq ${ev.seq} (+${lag} ms): ${text}`);
      }
    }
  } catch (e) {
    log(`feed ended: ${(e as Error).name} ${(e as Error).message}`);
  }
}

async function repoAndChanges(): Promise<{ git: API; repo: Repository; sha: string; changes: Change[] } | undefined> {
  const exp = vscode.extensions.getExtension<GitExtension>('vscode.git');
  const git = (exp!.isActive ? exp!.exports : await exp!.activate()).getAPI(1);
  const repo = git.repositories[0];
  if (!repo) { log('diff: no repository open'); return; }
  const short = vscode.workspace.getConfiguration('edpSpike').get<string>('commit')!;
  const c = await repo.getCommit(short);
  const changes = await repo.diffBetween(`${c.hash}^`, c.hash);
  log(`diff: repo=${repo.rootUri.fsPath} commit=${c.hash} parents=${c.parents.length} files=${changes.length}`);
  return { git, repo, sha: c.hash, changes };
}

async function diffProbe() {
  const r = await repoAndChanges(); if (!r) return;
  const ch = r.changes.find(x => x.status === 5 /* MODIFIED */) ?? r.changes[0];
  const left = r.git.toGitUri(ch.originalUri, `${r.sha}^`), right = r.git.toGitUri(ch.uri, r.sha);
  log(`diff: vscode.diff left=${left.toString()} right=${right.toString()}`);
  await vscode.commands.executeCommand('vscode.diff', left, right, `${vscode.workspace.asRelativePath(ch.uri)} (${r.sha.slice(0, 7)})`);
  log(`diff: vscode.diff resolved; active tab=${vscode.window.tabGroups.activeTabGroup.activeTab?.label}`);
}

async function changesProbe() {
  const r = await repoAndChanges(); if (!r) return;
  const res = r.changes.map(ch => [ch.uri, r.git.toGitUri(ch.originalUri, `${r.sha}^`), r.git.toGitUri(ch.uri, r.sha)] as const);
  await vscode.commands.executeCommand('vscode.changes', `Commit ${r.sha.slice(0, 7)}`, res);
  log(`changes: vscode.changes resolved with ${res.length} files; active tab=${vscode.window.tabGroups.activeTabGroup.activeTab?.label}`);
}

export function activate(ctx: vscode.ExtensionContext) {
  out = vscode.window.createOutputChannel('EDP chat spike');
  const media = vscode.Uri.joinPath(ctx.extensionUri, 'media');
  const view = new SpikeView(media);
  log(`activate vscode=${vscode.version} appHost=${vscode.env.appHost} uiKind=${vscode.env.uiKind}`);
  ctx.subscriptions.push(
    out,
    vscode.window.registerWebviewViewProvider('edpChatSpike.view', view),
    vscode.commands.registerCommand('edpSpike.useInline', () => { view.variant = 'inline'; view.padKb = 0; view.render(); }),
    vscode.commands.registerCommand('edpSpike.inlinePad', async () => {
      const kb = Number(await vscode.window.showInputBox({ title: 'Spike: inline padding (KB)', value: '1024' }));
      if (Number.isFinite(kb)) { view.variant = 'inline'; view.padKb = kb; view.render(); }
    }),
    vscode.commands.registerCommand('edpSpike.useExternal', () => { view.variant = 'external'; view.padKb = 0; view.render(); }),
    vscode.commands.registerCommand('edpSpike.panelBeside', () => {
      const p = vscode.window.createWebviewPanel('edpChatSpike.panel', 'EDP chat spike (panel)', vscode.ViewColumn.Beside,
        { enableScripts: true, localResourceRoots: [media] });
      wire(p.webview, () => view.variant, 'panel');
      p.webview.html = html(p.webview, media, view.variant, 'panel');
    }),
    vscode.commands.registerCommand('edpSpike.feedProbe', () => feedProbe(view)),
    vscode.commands.registerCommand('edpSpike.feedStop', () => { feedCtrl?.abort(); }),
    vscode.commands.registerCommand('edpSpike.diffProbe', () => diffProbe().catch(e => log(`diff failed: ${e}`))),
    vscode.commands.registerCommand('edpSpike.changesProbe', () => changesProbe().catch(e => log(`changes failed: ${e}`))),
    { dispose: () => feedCtrl?.abort() },
  );
}

export function deactivate() { feedCtrl?.abort(); }
