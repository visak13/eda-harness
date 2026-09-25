// #-tags in the view (C11 s-35ccc6d35f; design-10b21760d9 §13): the `#` picker in the composer and the
// path links in rendered messages. The view never reads the workspace: the host answers `findPaths`
// with rows and `checkPaths` with kinds. The picker mirrors the @ popup's WAI-ARIA listbox keys
// (strategyll-86c5b5068f §1) and navigates like shell completion (C13, owner m-28122bc446): Tab or →
// on a folder opens it, ← or Backspace at a `/` goes up, Enter inserts. Everything is set with textContent.
import type { HostToView, PathHit, PathKind, ViewToHost } from '../src/core/chatProtocol';
import { CHECK_PATHS_MAX } from '../src/core/chatProtocol';
import { activeHashTag, descendQuery, pathCandidate, pathToken } from '../src/core/paths';

type Intent = ViewToHost extends infer T ? (T extends unknown ? Omit<T, 'v'> : never) : never;
type Post = (m: Intent) => void;

/** The composer's # picker. main.ts routes input, caret moves, keys and host answers here. */
export class PathPicker {
  readonly list: HTMLUListElement;
  private items: PathHit[] = [];
  private active = 0;
  private range: { start: number; end: number } | null = null;
  private seq = 0;
  private asked: { seq: number; q: string } | null = null;
  /** The seq of the last answer shown; while it trails `asked`, the rows (and `up`) belong to the old query. */
  private answered = 0;
  /** the host's query for one level up from the rows shown (null: the git root, or a fuzzy answer) */
  private up: string | null = null;

  constructor(private ta: HTMLTextAreaElement, private post: Post, private status: HTMLElement,
    private onAccept: () => void) {
    const l = document.createElement('ul');
    l.className = 'people paths';
    l.id = 'paths';
    l.setAttribute('role', 'listbox');
    l.setAttribute('aria-label', 'Files and folders');
    l.hidden = true;
    this.list = l;
  }

  get isOpen(): boolean { return !this.list.hidden && this.items.length > 0; }

  close(): void {
    const was = !this.list.hidden;
    this.list.hidden = true;
    this.items = [];
    this.range = null;
    this.asked = null;
    this.up = null;
    if (was) { this.ta.removeAttribute('aria-activedescendant'); this.ta.setAttribute('aria-controls', 'people'); }
  }

  /** The caret moved or the text changed: ask the host for the rows of the # under the caret. */
  update(): void {
    const caret = this.ta.selectionStart ?? this.ta.value.length;
    const t = this.ta.selectionStart === this.ta.selectionEnd ? activeHashTag(this.ta.value, caret) : undefined;
    if (!t) return this.close();
    this.range = { start: t.start, end: caret };
    if (this.asked?.q === t.query) return;
    this.asked = { seq: ++this.seq, q: t.query };
    this.post({ type: 'findPaths', q: t.query, seq: this.seq });
  }

  /** The host's rows; an answer to an older query is dropped. */
  onPaths(m: Extract<HostToView, { type: 'paths' }>): void {
    if (!this.asked || m.seq !== this.asked.seq || !this.range) return;
    const wasOpen = !this.list.hidden;
    this.answered = m.seq;
    this.items = m.items;
    this.up = m.up ?? null;
    if (!this.items.length) {
      this.list.hidden = true;
      this.ta.removeAttribute('aria-activedescendant');
      this.status.textContent = 'No matching files or folders';
      return;
    }
    if (!wasOpen || this.active >= this.items.length) this.active = 0;
    this.list.hidden = false;
    this.ta.setAttribute('aria-controls', 'paths');
    this.render();
    this.status.textContent = `${this.items.length} ${this.items.length === 1 ? 'file or folder' : 'files and folders'}`;
  }

  private render(): void {
    this.list.replaceChildren(...this.items.map((h, i) => {
      const li = document.createElement('li');
      li.className = `opt path-opt${i === this.active ? ' active' : ''}`;
      li.id = `path-${i}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(i === this.active));
      li.setAttribute('aria-label', `${h.kind} ${h.path}${h.kind === 'folder' ? '/' : ''}`);
      li.dataset.path = h.path;
      li.dataset.kind = h.kind;
      const slash = h.path.lastIndexOf('/');
      const name = document.createElement('span');
      name.className = 'h';
      name.textContent = `${h.kind === 'folder' ? '▸ ' : ''}${h.path.slice(slash + 1)}${h.kind === 'folder' ? '/' : ''}`;
      const where = document.createElement('span');
      where.className = 'd';
      where.textContent = slash > 0 ? h.path.slice(0, slash + 1) : '';
      li.append(name, where);
      li.addEventListener('mousedown', e => { e.preventDefault(); this.active = i; this.accept(); });
      return li;
    }));
    this.ta.setAttribute('aria-activedescendant', `path-${this.active}`);
    this.list.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
  }

  /** Replace `#query` with the token. */
  private accept(): void {
    const h = this.items[this.active];
    const r = this.range;
    if (!h || !r) return this.close();
    const ins = pathToken(h);
    const v = this.ta.value;
    this.ta.value = v.slice(0, r.start) + ins + v.slice(r.end);
    const c = r.start + ins.length;
    this.ta.setSelectionRange(c, c);
    this.close();
    this.status.textContent = `Tagged ${h.kind} ${h.path}`;
    this.ta.focus();
    this.onAccept();
  }

  /** The live `#` query (the text between `#` and the caret). */
  private get query(): string | null {
    return this.range ? this.ta.value.slice(this.range.start + 1, this.range.end) : null;
  }

  /** Replace the `#query` with `#q` (caret after it) and list that level. */
  private setQuery(q: string): void {
    const r = this.range;
    if (!r) return;
    const v = this.ta.value;
    this.ta.value = `${v.slice(0, r.start)}#${q}${v.slice(r.end)}`;
    const c = r.start + 1 + q.length;
    this.ta.setSelectionRange(c, c);
    this.active = 0;
    this.status.textContent = q ? `In ${q}` : 'Top level';
    this.onAccept();
    this.update();
  }

  /** The @ popup's keys plus shell completion; true = handled (Enter never sends while the list is open). */
  onKey(e: KeyboardEvent): boolean {
    const q = this.query;
    // a pick or a level move before the host answered the last query would act on the old level's rows
    // (Tab Tab descending into a sibling): drop the key until the answer lands; typing is never held
    if (this.asked && this.asked.seq !== this.answered && (this.isOpen || this.up !== null)
      && (['Tab', 'ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'Enter'].includes(e.key) || (e.key === 'Backspace' && q?.endsWith('/')))) {
      e.preventDefault();
      return true;
    }
    // ← in a listed level, Backspace right after a `/` (`v8/web/`, `../`): one level up, as the host said;
    // at the git root there is no up and the key does what it always does
    if (q !== null && this.up !== null && this.asked?.q === q && !e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey
      && ((e.key === 'ArrowLeft' && this.isOpen) || (e.key === 'Backspace' && q.endsWith('/')))) {
      e.preventDefault();
      this.setQuery(this.up);
      return true;
    }
    if (!this.isOpen) {
      // the list is empty (no match) but a # query is live: Escape still dismisses it
      if (e.key === 'Escape' && this.range) { e.preventDefault(); e.stopPropagation(); this.close(); return true; }
      return false;
    }
    const n = this.items.length;
    const h = this.items[this.active];
    if (e.key === 'ArrowDown') { e.preventDefault(); this.active = (this.active + 1) % n; this.render(); return true; }
    if (e.key === 'ArrowUp') { e.preventDefault(); this.active = (this.active - 1 + n) % n; this.render(); return true; }
    // Tab or → on a folder descends into it; Tab on a file inserts it, → on a file moves the caret as usual
    if ((e.key === 'Tab' || e.key === 'ArrowRight') && h?.kind === 'folder' && !e.shiftKey) { e.preventDefault(); this.setQuery(descendQuery(h)); return true; }
    if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) { e.preventDefault(); this.accept(); return true; }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(); return true; }
    return false;
  }

  /** The toolbar's # button: a `#` at the caret (after a space if it would follow a word), then the picker. */
  insertHash(): void {
    const v = this.ta.value;
    const s = this.ta.selectionStart ?? v.length, e = this.ta.selectionEnd ?? v.length;
    const ins = s > 0 && /\w/.test(v[s - 1]) ? ' #' : '#';
    this.ta.value = v.slice(0, s) + ins + v.slice(e);
    const c = s + ins.length;
    this.ta.focus();
    this.ta.setSelectionRange(c, c);
    this.onAccept();
    this.update();
  }
}

// -- path links in rendered messages -----------------------------------------------------------------
/** Per view document: what the host said each path is (null = not in this workspace). */
const known = new Map<string, PathKind | null>();
const pending = new Set<string>();
let flush: ReturnType<typeof setTimeout> | undefined;

/** Mark the inline code spans (not code blocks) of a rendered body that look like paths, and ask the
 *  host about the ones it has not answered yet. Unanswered or missing ones stay plain code. */
export function markPaths(body: ParentNode, post: Post): void {
  for (const code of body.querySelectorAll<HTMLElement>('code')) {
    if (code.closest('pre, a')) continue;
    const c = pathCandidate(code.textContent ?? '');
    if (!c) continue;
    code.dataset.path = c.path;
    if (c.folder) code.dataset.folder = 'true';
    if (known.has(c.path)) link(code, known.get(c.path)!);
    else pending.add(c.path);
  }
  if (pending.size && flush === undefined) flush = setTimeout(() => {
    flush = undefined;
    const all = [...pending];
    pending.clear();
    for (let i = 0; i < all.length; i += CHECK_PATHS_MAX) post({ type: 'checkPaths', paths: all.slice(i, i + CHECK_PATHS_MAX) });
  }, 0);
}

/** The host's answer: link every marked span it names. */
export function applyKinds(root: ParentNode, m: Extract<HostToView, { type: 'pathKinds' }>): void {
  for (const [p, k] of Object.entries(m.kinds)) known.set(p, k);
  for (const p of m.missing) known.set(p, null);
  for (const code of root.querySelectorAll<HTMLElement>('code[data-path]')) {
    const k = known.get(code.dataset.path!);
    if (k !== undefined) link(code, k);
  }
}

/** A new document state may follow file creates: forget the misses so they are asked again. */
export function forgetMisses(): void {
  for (const [p, k] of known) if (k === null) known.delete(p);
}

/** Turn a marked code span into a link (a file opens, a folder reveals); a miss stays plain text. */
function link(code: HTMLElement, kind: PathKind | null): void {
  if (!kind || code.parentElement?.classList.contains('path-link')) return;
  // a `name/` span names a folder: a file of that name is not what the author tagged
  if (code.dataset.folder && kind !== 'folder') return;
  const p = code.dataset.path!;
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `path-link ${kind}`;
  b.dataset.path = p;
  b.dataset.kind = kind;
  b.title = kind === 'file' ? `Open ${p}` : `Reveal ${p}/ in the Explorer`;
  code.replaceWith(b);
  b.append(code);
}

/** One delegated click handler for every path link in the timeline. */
export function onPathClick(root: HTMLElement, post: Post): void {
  root.addEventListener('click', e => {
    const b = (e.target as HTMLElement).closest<HTMLElement>('button.path-link');
    if (!b?.dataset.path) return;
    e.preventDefault();
    post({ type: 'openPath', path: b.dataset.path });
  });
}
