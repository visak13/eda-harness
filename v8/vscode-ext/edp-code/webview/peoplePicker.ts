// The @ people picker (WAI-ARIA listbox half; strategyll-86c5b5068f §1), shared by the composer and the C20 quote
// note boxes (owner m-5a9111ce12: "quote doesnt allow mentions or hashtags"). Rows are the host's labelled people
// list; the view filters them (filterPeople). Everything is set with textContent.
import type { PersonRow } from '../src/core/chatProtocol';
import { activeMention } from '../src/core/mentions';
import { accessibleName, filterPeople } from '../src/core/people';

export type TextField = HTMLTextAreaElement | HTMLInputElement;

export class PeoplePicker {
  readonly list: HTMLUListElement;
  private items: PersonRow[] = [];
  private active = 0;
  private range: { start: number; end: number } | null = null;

  /** `ids.list` is the listbox id, `ids.opt` the option id prefix (the composer keeps `people` / `p`). */
  constructor(public field: TextField, private people: () => PersonRow[], private status: HTMLElement,
    private onAccept: () => void, private ids: { list: string; opt: string } = { list: 'people', opt: 'p' }) {
    const l = document.createElement('ul');
    l.className = 'people';
    l.id = ids.list;
    l.setAttribute('role', 'listbox');
    l.setAttribute('aria-label', 'People');
    l.hidden = true;
    this.list = l;
  }

  get isOpen(): boolean { return !this.list.hidden && this.items.length > 0; }

  close(): void {
    this.list.hidden = true;
    this.field.removeAttribute('aria-activedescendant');
    this.items = [];
    this.range = null;
  }

  /** The caret moved or the text changed: list the people matching the @ under the caret. */
  update(): void {
    const f = this.field;
    const caret = f.selectionStart ?? f.value.length;
    const m = f.selectionStart === f.selectionEnd ? activeMention(f.value, caret) : undefined;
    if (!m) return this.close();
    const items = filterPeople(this.people(), m.query);
    if (!items.length) return this.close();
    const wasOpen = !this.list.hidden;
    this.items = items;
    this.range = { start: m.start, end: caret };
    if (!wasOpen || this.active >= items.length) this.active = 0;
    this.list.hidden = false;
    this.render();
    this.status.textContent = `${items.length} ${items.length === 1 ? 'person' : 'people'}`;
  }

  private render(): void {
    this.list.replaceChildren(...this.items.map((p, i) => {
      const li = document.createElement('li');
      li.className = `opt${i === this.active ? ' active' : ''}`;
      li.id = `${this.ids.opt}-${i}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(i === this.active));
      li.setAttribute('aria-label', accessibleName(p));
      li.dataset.handle = p.handle;
      const h = document.createElement('span');
      h.className = 'h';
      h.textContent = `@${p.handle}`;
      const d = document.createElement('span');
      d.className = `d ${p.type}`;
      d.textContent = p.detail;
      li.append(h, d);
      li.addEventListener('mousedown', e => { e.preventDefault(); this.active = i; this.accept(); });
      return li;
    }));
    this.field.setAttribute('aria-activedescendant', `${this.ids.opt}-${this.active}`);
    this.list.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
  }

  private accept(): void {
    const p = this.items[this.active];
    const r = this.range;
    if (!p || !r) return this.close();
    const ins = `@${p.handle} `;
    const v = this.field.value;
    this.field.value = v.slice(0, r.start) + ins + v.slice(r.end);
    const c = r.start + ins.length;
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
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(); return true; }
    return false;
  }
}
