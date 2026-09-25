// C24 (s-5d1b171d57, owner m-0f727b0c57): the $ picker — board objects (tickets, epics, docs, decisions) beside the
// @ people and # path pickers, with the same WAI-ARIA listbox keys (strategyll-86c5b5068f §1): ↑/↓ move, Enter or
// Tab picks, Escape closes and keeps the text. The view never reads the board: it posts `findRefs` and the host
// answers `refs` (this epic's tree first, then the board's open items). Everything is set with textContent.
import type { HostToView, ViewToHost } from '../src/core/chatProtocol';
import { activeRef, cleanRows, kindLabel, refToken, type RefRow } from '../src/core/boardRefs';

type Field = HTMLTextAreaElement | HTMLInputElement;
export type FindRefs = (m: Extract<ViewToHost, { type: 'findRefs' }> extends infer T ? Omit<T, 'v'> : never) => void;
/** one seq counter for every $ picker in this view, so an answer reaches only the picker that asked */
let lastSeq = 0;

export class RefPicker {
  readonly list: HTMLUListElement;
  private items: RefRow[] = [];
  private active = 0;
  private range: { start: number; end: number } | null = null;
  private asked: { seq: number; q: string } | null = null;
  /** the token Escape closed: it stays closed until the text or caret moves off it */
  private dismissed: string | null = null;

  constructor(public field: Field, private post: FindRefs, private status: HTMLElement,
    private onAccept: () => void, private ids: { list: string; opt: string; people?: string } = { list: 'refs', opt: 'ref', people: 'people' }) {
    const l = document.createElement('ul');
    l.className = 'people refs';
    l.id = ids.list;
    l.setAttribute('role', 'listbox');
    l.setAttribute('aria-label', 'Board objects');
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
    if (was) this.release();
  }

  /** Drop the field's listbox links only while they point at this list: the @ or # picker may own them now
   *  (second opinion 20260925T194748Z-c11490bb: `$s @o` lost the people list's active option). */
  private release(): void {
    const f = this.field;
    if (f.getAttribute('aria-activedescendant')?.startsWith(`${this.ids.opt}-`)) f.removeAttribute('aria-activedescendant');
    if (f.getAttribute('aria-controls') === this.ids.list) {
      if (this.ids.people) f.setAttribute('aria-controls', this.ids.people); else f.removeAttribute('aria-controls');
    }
  }

  /** The caret moved or the text changed: ask the host for the rows of the $ word under the caret. */
  update(): void {
    const f = this.field;
    const caret = f.selectionStart ?? f.value.length;
    const t = f.selectionStart === f.selectionEnd ? activeRef(f.value, caret) : null;
    if (!t) { this.dismissed = null; return this.close(); }
    const key = `${t.start}:${t.query}`;
    if (this.dismissed === key) return;
    this.dismissed = null;
    this.range = { start: t.start, end: caret };
    if (this.asked?.q === t.query) return;
    // the shown rows answer the old query: never pickable once the query moved (second opinion 20260925T194748Z-c11490bb)
    if (!this.list.hidden) { this.list.hidden = true; this.items = []; this.release(); }
    this.asked = { seq: ++lastSeq, q: t.query };
    this.post({ type: 'findRefs', q: t.query, seq: lastSeq });
  }

  /** The host's rows; an answer to another query is dropped. */
  onRefs(m: Extract<HostToView, { type: 'refs' }>): void {
    if (!this.asked || m.seq !== this.asked.seq || !this.range) return;
    const wasOpen = !this.list.hidden;
    this.items = cleanRows(m.items);
    if (!this.items.length) {
      this.list.hidden = true;
      this.release();
      this.status.textContent = 'No matching board objects';
      return;
    }
    if (!wasOpen || this.active >= this.items.length) this.active = 0;
    this.list.hidden = false;
    this.render();
    this.status.textContent = `${this.items.length} board ${this.items.length === 1 ? 'object' : 'objects'}`;
  }

  private render(): void {
    this.list.replaceChildren(...this.items.map((r, i) => {
      const li = document.createElement('li');
      li.className = `opt${i === this.active ? ' active' : ''}${r.group === 'board' ? ' other' : ''}`;
      li.id = `${this.ids.opt}-${i}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(i === this.active));
      li.setAttribute('aria-label', `${kindLabel(r.kind)} ${r.id} ${r.title}${r.group === 'board' ? ' (other work)' : ''}`);
      li.dataset.ref = r.id;
      li.dataset.group = r.group;
      const h = document.createElement('span');
      h.className = 'h';
      h.textContent = `${kindLabel(r.kind)} $${r.id}`;
      const d = document.createElement('span');
      d.className = 'd';
      d.textContent = r.title;
      li.append(h, d);
      li.addEventListener('mousedown', e => { e.preventDefault(); this.active = i; this.accept(); });
      return li;
    }));
    this.field.setAttribute('aria-controls', this.ids.list);
    this.field.setAttribute('aria-activedescendant', `${this.ids.opt}-${this.active}`);
    this.list.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
  }

  private accept(): void {
    const r = this.items[this.active];
    const at = this.range;
    if (!r || !at) return this.close();
    const ins = refToken(r);
    const v = this.field.value;
    this.field.value = v.slice(0, at.start) + ins + v.slice(at.end);
    const c = at.start + ins.length;
    this.field.setSelectionRange(c, c);
    this.close();
    this.onAccept();
    this.field.focus();
  }

  /** The listbox keys while the list is open; true = handled (Enter and Tab pick, never send). */
  onKey(e: KeyboardEvent): boolean {
    if (!this.isOpen) return false;
    const n = this.items.length;
    if (e.key === 'ArrowDown') { e.preventDefault(); this.active = (this.active + 1) % n; this.render(); return true; }
    if (e.key === 'ArrowUp') { e.preventDefault(); this.active = (this.active - 1 + n) % n; this.render(); return true; }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); this.accept(); return true; }
    if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      if (this.range) this.dismissed = `${this.range.start}:${this.asked?.q ?? ''}`;
      this.close();
      return true;
    }
    return false;
  }
}

/** C24: a click on a `$<id>` chip anywhere under `root` asks the host to open it. */
export function onRefClick(root: HTMLElement, post: (m: { type: 'openRef'; id: string }) => void): void {
  root.addEventListener('click', e => {
    const b = (e.target as HTMLElement | null)?.closest?.('.ref-chip') as HTMLElement | null;
    if (!b?.dataset.ref || !root.contains(b)) return;
    e.preventDefault();
    e.stopPropagation();
    post({ type: 'openRef', id: b.dataset.ref });
  });
}
