// C25: a fresh sign-in (secrets.onDidChange + the edp.signIn command) must not abort itself, empty
// the picker, or leave the seats badge hidden. Keeps the C7 viewer guarantees (c7-review.test.ts).
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  stored: undefined as undefined | { participant: string; token: string; origin: string },
  errors: [] as string[],
  item: { text: '', tooltip: '', shown: false, show() { this.shown = true; }, hide() { this.shown = false; }, dispose() {} } as any,
  qp: undefined as any,
}));
const disp = { dispose() {} };
vi.mock('vscode', () => ({
  window: {
    showErrorMessage: (t: string) => { h.errors.push(t); },
    createStatusBarItem: () => h.item,
    onDidChangeActiveTextEditor: () => disp,
    createQuickPick: () => {
      const on: Record<string, () => void> = {};
      h.qp = { items: [], selectedItems: [], busy: false, disposed: false, on,
        onDidAccept: (f: () => void) => { on.accept = f; }, onDidHide: (f: () => void) => { on.hide = f; },
        show() {}, dispose() { this.disposed = true; } };
      return h.qp;
    },
  },
  workspace: {
    getConfiguration: () => ({ get: (k: string) => (k === 'sharedTreePaths' ? ['C:\\tree'] : undefined) }),
    onDidChangeWorkspaceFolders: () => disp, onDidChangeConfiguration: () => disp,
  },
  StatusBarAlignment: { Left: 1 }, QuickPickItemKind: { Separator: -1 }, ThemeColor: class {},
}));
vi.mock('../src/vscode/auth', () => ({ creds: async () => h.stored, signIn: vi.fn() }));
vi.mock('../src/vscode/repo', () => ({
  gitApi: async () => ({
    repositories: [{ rootUri: { fsPath: 'C:\\tree' }, state: { HEAD: { name: 'main' }, onDidChange: () => disp } }],
    onDidOpenRepository: () => disp, onDidCloseRepository: () => disp,
  }),
}));

import { ViewerRequests } from '../src/core/viewer';
import { BoardError } from '../src/core/api';
import { ChatController } from '../src/vscode/chat';
import { Badge } from '../src/vscode/badge';
import { viewerHooks } from '../src/vscode/extension';

const URL0 = 'http://127.0.0.1:1';
const ok = (value: unknown) => new Response(JSON.stringify({ ok: true, value }), { status: 200 });
const ticket = { id: 'epic-0123456789', kind: 'epic', title: 'Epic', status: 'in_progress', assignee: null };

beforeEach(() => { h.stored = { participant: 'owner', token: 't1', origin: URL0 }; h.errors = []; h.qp = undefined; });
afterEach(() => { vi.useRealTimers(); });

/** A controller with the real restart/clearViewer and the real ViewerRequests behind its board. */
function controller(fetcher: typeof fetch, badge = { clear: vi.fn(), refresh: vi.fn() }) {
  const requests = new ViewerRequests(() => c.clearViewer(), fetcher);
  const hooks = viewerHooks(requests, badge);
  const cancel = vi.fn(hooks.cancel);
  const stub = { clear() {} };
  const c: any = Object.assign(Object.create(ChatController.prototype), {
    ctx: { workspaceState: { get: () => 'epic-0123456789' } }, boardUrl: () => URL0, log() {},
    board: () => requests.board(URL0, async () => h.stored, () => {}),
    cancelViewer: cancel, resumeViewer: hooks.resume, booted: true, viewer: 0, viewerKey: null,
    restarting: Promise.resolve(), chain: Promise.resolve(), opening: 0, opened: 0,
    refs: stub, reader: { reset() {} }, docProvider: { clear() {}, resume() {} }, inbox: stub, docs: stub, decisions: stub, attach: stub,
    quotes: { setIdentity() {} }, unread: new Map(), chips: new Map(), anchors: new Map(), titles: new Map(),
    postState: vi.fn(), startFeed: vi.fn(),
  });
  c.open = vi.fn(async (id: string) => { await c.board().ticket(id); });
  return { c, cancel, badge };
}

it('C25: sign-in firing both secrets.onDidChange and edp.signIn is one effective restart with no aborted request', async () => {
  const signals: AbortSignal[] = [];
  const f = vi.fn(async (_i: unknown, init?: RequestInit) => { signals.push(init!.signal!); await new Promise(r => setTimeout(r, 5)); return ok(ticket); });
  const { c, cancel, badge } = controller(f as typeof fetch);
  // extension.ts: the secret write fires onDidChange, then the command's own restart follows
  const fromSecret = c.restart(), fromCommand = c.restart();
  await expect(Promise.all([fromSecret, fromCommand])).resolves.toBeDefined();
  expect(cancel).toHaveBeenCalledOnce();
  expect(c.open).toHaveBeenCalledOnce();
  expect(c.startFeed).toHaveBeenCalledOnce();
  expect(f).toHaveBeenCalledOnce();
  expect(signals.some(s => s.aborted)).toBe(false);
  expect(c.notice).toBeNull(); // not left on "Sign in to the board"
  expect(badge.refresh).toHaveBeenLastCalledWith(0); // the resumed viewer re-armed its badge
});

it('C25 keeps C7: another identity, a sign-out and a 401 each still clear the viewer', async () => {
  const f = vi.fn(async () => ok(ticket));
  const { c, cancel } = controller(f as typeof fetch);
  await c.restart();
  expect(cancel).toHaveBeenCalledTimes(1);
  h.stored = { participant: 'other', token: 't2', origin: URL0 };
  await c.restart();
  expect(cancel).toHaveBeenCalledTimes(2); // identity change: invalidated
  c.clearViewer(); // what a 401 does (ViewerRequests.onAuth)
  expect(c.viewerKey).toBeNull();
  await c.restart(); // the same creds after a 401 restart for real
  expect(cancel).toHaveBeenCalledTimes(4);
  expect(c.open).toHaveBeenCalledTimes(3);
  h.stored = undefined;
  await c.restart(); // sign-out
  expect(cancel).toHaveBeenCalledTimes(5);
  expect(c).toMatchObject({ feedStatus: 'signed-out', notice: 'Sign in to the board to read and send.', viewerKey: null });
});

it('C25: a viewer_changed abort during pick() is retried against the new viewer, not a silent empty picker', async () => {
  const { c } = controller(vi.fn() as typeof fetch);
  const tickets = vi.fn()
    .mockRejectedValueOnce(new BoardError('viewer_changed', 'The board viewer changed.', 0))
    .mockResolvedValueOnce([ticket]);
  c.board = () => ({ tickets });
  const picked = c.pick();
  await vi.waitFor(() => expect(h.qp?.busy).toBe(false));
  expect(tickets).toHaveBeenCalledTimes(2);
  expect(h.qp.items.map((i: any) => i.id).filter(Boolean)).toEqual(['epic-0123456789']);
  expect(h.qp.disposed).toBe(false);
  h.qp.on.hide();
  await expect(picked).resolves.toBeUndefined();
  expect(h.errors).toEqual([]);
});

it('C25: a pick aborted again after its one retry shows an error', async () => {
  const { c } = controller(vi.fn() as typeof fetch);
  const tickets = vi.fn().mockRejectedValue(new BoardError('viewer_changed', 'The board viewer changed.', 0));
  c.board = () => ({ tickets });
  await expect(c.pick()).resolves.toBeUndefined();
  expect(tickets).toHaveBeenCalledTimes(2);
  expect(h.qp.disposed).toBe(true);
  expect(h.errors).toEqual(['EDP: could not list tickets: The board viewer changed.']);
});

it('C25: resume() re-shows the seats badge that the sign-in viewer switch cleared', async () => {
  vi.useFakeTimers();
  const board = { sessions: async () => [], participants: async () => [] } as any;
  const badge = new Badge({ globalStorageUri: { fsPath: 'C:\\tree\\.data\\code\\user' } } as any, () => board);
  await vi.runOnlyPendingTimersAsync(); // the constructor's first poll
  expect(h.item.shown).toBe(true);
  const hooks = viewerHooks({ invalidate() {}, resume() {} }, badge);
  badge.refresh(0); // edp.signIn / secrets.onDidChange
  hooks.cancel(); // restart -> clearViewer: hides the badge and drops that refresh
  expect(h.item.shown).toBe(false);
  hooks.resume(); // the new viewer is live
  await vi.advanceTimersByTimeAsync(0);
  await vi.waitFor(() => expect(h.item.shown).toBe(true));
  expect(h.item.text).toContain('main');
  badge.dispose();
});
