// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import { bodyFragment } from '../webview/render';
import { applyKinds, forgetMisses, markPaths, onPathClick, PathPicker } from '../webview/pathTags';

type Sent = { type: string; [k: string]: unknown };
Element.prototype.scrollIntoView ??= function () {}; // jsdom has no layout
const tick = () => new Promise(r => setTimeout(r, 0));

describe('path links in rendered messages', () => {
  let sent: Sent[];
  const post = (m: Sent) => { sent.push(m); };
  const body = (text: string) => {
    const d = document.createElement('div');
    d.append(bodyFragment(document, text, new Set()));
    markPaths(d, post as never);
    return d;
  };
  beforeEach(() => { sent = []; forgetMisses(); });

  it('asks the host about inline path spans only (not code blocks, not plain words)', async () => {
    body('see `v8/a.ts` and `v8/web/` but not `npm test` or\n\n```\nv8/b.ts\n```');
    await tick();
    expect(sent).toEqual([{ type: 'checkPaths', paths: ['v8/a.ts', 'v8/web'] }]);
  });

  it('links a file and a folder that exist; a missing path stays plain code', async () => {
    const d = body('`v8/a.ts` `v8/web/` `v8/gone.ts`');
    await tick();
    applyKinds(d, { type: 'pathKinds', v: 1, kinds: { 'v8/a.ts': 'file', 'v8/web': 'folder' }, missing: ['v8/gone.ts'] });
    const links = [...d.querySelectorAll<HTMLButtonElement>('button.path-link')];
    expect(links.map(b => [b.dataset.path, b.dataset.kind, b.textContent])).toEqual([['v8/a.ts', 'file', 'v8/a.ts'], ['v8/web', 'folder', 'v8/web/']]);
    expect(links[1].title).toBe('Reveal v8/web/ in the Explorer');
    const gone = [...d.querySelectorAll('code')].find(c => c.textContent === 'v8/gone.ts')!;
    expect(gone.closest('button')).toBeNull();
  });

  it('a `name/` span is a folder tag: a file of that name does not link', async () => {
    const d = body('`v8/Makefile/`');
    await tick();
    applyKinds(d, { type: 'pathKinds', v: 1, kinds: { 'v8/Makefile': 'file' }, missing: [] });
    expect(d.querySelector('.path-link')).toBeNull();
  });

  it('answers are cached: a later message links at once, with no second ask', async () => {
    const d1 = body('`x/y.ts`');
    await tick();
    applyKinds(d1, { type: 'pathKinds', v: 1, kinds: { 'x/y.ts': 'file' }, missing: [] });
    sent = [];
    const d2 = body('again `x/y.ts`');
    await tick();
    expect(sent).toEqual([]);
    expect(d2.querySelector('.path-link')?.getAttribute('data-path')).toBe('x/y.ts');
  });

  it('a click posts openPath', async () => {
    const d = body('`q/r.ts`');
    await tick();
    applyKinds(d, { type: 'pathKinds', v: 1, kinds: { 'q/r.ts': 'file' }, missing: [] });
    onPathClick(d, post as never);
    sent = [];
    d.querySelector<HTMLElement>('.path-link code')!.click();
    expect(sent).toEqual([{ type: 'openPath', path: 'q/r.ts' }]);
  });

  it('agent text cannot inject a link: the button is ours, the path text is textContent', async () => {
    const d = body('`a/<img src=x onerror=alert(1)>.ts`');
    await tick();
    expect(d.querySelector('img')).toBeNull();
  });
});

describe('PathPicker: the # list in the composer', () => {
  let ta: HTMLTextAreaElement;
  let sent: Sent[];
  let picker: PathPicker;
  let status: HTMLElement;
  const type = (v: string) => { ta.value = v; ta.setSelectionRange(v.length, v.length); picker.update(); };
  const key = (k: string) => { const e = new KeyboardEvent('keydown', { key: k, cancelable: true }); return { handled: picker.onKey(e), prevented: e.defaultPrevented }; };
  const lastSeq = () => sent[sent.length - 1].seq as number;
  beforeEach(() => {
    document.body.replaceChildren();
    ta = document.createElement('textarea');
    status = document.createElement('div');
    sent = [];
    picker = new PathPicker(ta, m => sent.push(m as Sent), status, () => {});
    document.body.append(picker.list, ta);
  });

  it('# opens it: asks the host with the query, renders the answer as a listbox', () => {
    type('see #v8/vs');
    expect(sent).toEqual([{ type: 'findPaths', q: 'v8/vs', seq: 1 }]);
    picker.onPaths({ type: 'paths', v: 1, seq: 1, items: [{ path: 'v8/vscode-ext', kind: 'folder' }, { path: 'v8/vscode-ext/README.md', kind: 'file' }] });
    expect(picker.isOpen).toBe(true);
    expect(picker.list.getAttribute('role')).toBe('listbox');
    expect([...picker.list.querySelectorAll('[role=option]')].map(o => o.getAttribute('aria-label'))).toEqual(['folder v8/vscode-ext/', 'file v8/vscode-ext/README.md']);
    expect(ta.getAttribute('aria-activedescendant')).toBe('path-0');
    expect(ta.getAttribute('aria-controls')).toBe('paths');
  });

  it('Down then Enter inserts the backticked path; a folder ends with /; Enter is consumed (never sends)', () => {
    type('look at #edp');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/edp8', kind: 'folder' }, { path: 'v8/edp8/board.py', kind: 'file' }] });
    expect(key('ArrowDown')).toEqual({ handled: true, prevented: true });
    expect(ta.getAttribute('aria-activedescendant')).toBe('path-1');
    expect(key('Enter')).toEqual({ handled: true, prevented: true });
    expect(ta.value).toBe('look at `v8/edp8/board.py` ');
    expect(picker.isOpen).toBe(false);
    type(ta.value + '#edp');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/edp8', kind: 'folder' }] });
    expect(key('Enter').handled).toBe(true);
    expect(ta.value).toBe('look at `v8/edp8/board.py` `v8/edp8/` ');
  });

  // C13 (owner m-28122bc446, criterion c-6b8ea6657b): shell completion
  it('Tab or → on a folder descends: the query becomes `folder/` and that level is asked for', () => {
    type('see #');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/edp8', kind: 'folder' }, { path: 'v8/web', kind: 'folder' }] });
    expect(key('Tab')).toEqual({ handled: true, prevented: true });
    expect(ta.value).toBe('see #v8/edp8/');
    expect(sent[sent.length - 1]).toMatchObject({ type: 'findPaths', q: 'v8/edp8/' });
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/edp8/api', kind: 'folder' }, { path: 'v8/edp8/board.py', kind: 'file' }] });
    expect(key('ArrowRight')).toEqual({ handled: true, prevented: true });
    expect(ta.value).toBe('see #v8/edp8/api/');
    expect(ta.selectionStart).toBe(ta.value.length);
  });
  it('keys before the host answers are held, never applied to the old level (Tab Tab, Tab Enter, Backspace twice)', () => {
    type('see #');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/.claude', kind: 'folder' }, { path: 'v8/web', kind: 'folder' }], up: '../' });
    key('ArrowDown');
    key('Tab');
    expect(ta.value).toBe('see #v8/web/');
    const asked = sent.length;
    expect(key('Tab')).toEqual({ handled: true, prevented: true });   // not #v8/.claude/
    expect(key('Enter')).toEqual({ handled: true, prevented: true }); // no insert of an old row
    expect(key('Backspace')).toEqual({ handled: true, prevented: true });
    expect(ta.value).toBe('see #v8/web/');
    expect(sent.length).toBe(asked);
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/web/src', kind: 'folder' }], up: '' });
    key('Tab');
    expect(ta.value).toBe('see #v8/web/src/');
  });

  it("Tab on a file inserts it; → on a file is the caret's own key", () => {
    type('#v8/edp8/');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/edp8/board.py', kind: 'file' }] });
    expect(key('ArrowRight').handled).toBe(false);
    expect(key('Tab').handled).toBe(true);
    expect(ta.value).toBe('`v8/edp8/board.py` ');
  });
  it('Backspace right after a `/` and ← go up one level; Backspace mid-name deletes as usual', () => {
    type('x #v8/edp8/');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/edp8/board.py', kind: 'file' }], up: 'v8/' });
    expect(key('Backspace')).toEqual({ handled: true, prevented: true });
    expect(ta.value).toBe('x #v8/');
    expect(sent[sent.length - 1]).toMatchObject({ q: 'v8/' });
    type('x #v8/we');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/web', kind: 'folder' }], up: '' });
    expect(key('Backspace').handled).toBe(false); // mid-name: a plain Backspace
    expect(key('ArrowLeft').handled).toBe(true);
    expect(ta.value).toBe('x #');
    // home (v8) in a bigger repo: ← climbs to the git root as `../`
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'v8/web', kind: 'folder' }], up: '../' });
    expect(key('ArrowLeft').handled).toBe(true);
    expect(ta.value).toBe('x #../');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'edp-pool', kind: 'folder' }], up: null });
    expect(key('ArrowLeft').handled).toBe(false); // the git root is the top: ← moves the caret
    expect(key('Backspace').handled).toBe(false);
  });

  it('Up wraps, Escape closes, keys pass through when closed', () => {
    type('#a');
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'a', kind: 'folder' }, { path: 'a.ts', kind: 'file' }] });
    key('ArrowUp');
    expect(ta.getAttribute('aria-activedescendant')).toBe('path-1');
    expect(key('Escape').handled).toBe(true);
    expect(picker.isOpen).toBe(false);
    expect(key('Enter').handled).toBe(false);
  });

  it('drops a stale answer (an older query)', () => {
    type('#a');
    const first = lastSeq();
    type('#ab');
    picker.onPaths({ type: 'paths', v: 1, seq: first, items: [{ path: 'a', kind: 'folder' }] });
    expect(picker.isOpen).toBe(false);
    picker.onPaths({ type: 'paths', v: 1, seq: lastSeq(), items: [{ path: 'ab.ts', kind: 'file' }] });
    expect(picker.isOpen).toBe(true);
  });

  it('no picker after a word character or inside a code span', () => {
    type('C#');
    type('issue#12');
    type('`x #');
    expect(sent).toEqual([]);
  });

  it('the # button inserts # at the caret (spaced after a word) and asks', () => {
    ta.value = 'see';
    ta.setSelectionRange(3, 3);
    picker.insertHash();
    expect(ta.value).toBe('see #');
    expect(sent).toEqual([{ type: 'findPaths', q: '', seq: expect.any(Number) }]);
  });
});
