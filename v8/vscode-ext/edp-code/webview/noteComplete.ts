// C20 (owner m-5a9111ce12 "quote doesnt allow mentions or hashtags"; architect m-be79dbaa17): the composer's @
// people picker and # path picker on the quote note boxes (the chat message popover, the chip notes, the reader
// popover). One pair of pickers per view, pointed at whichever note field has focus; their lists are placed in
// the field's own container. A key a picker takes (arrows, Enter, Tab, Escape while a list is open) never reaches
// the box's own handlers (Ctrl+Enter adds, Escape cancels).
import type { PathHit, PersonRow } from '../src/core/chatProtocol';
import { PathPicker, type FindPaths } from './pathTags';
import { PeoplePicker, type TextField } from './peoplePicker';

export class NoteCompletion {
  readonly people: PeoplePicker;
  readonly paths: PathPicker;

  /** `prefix` keeps the listbox and option ids apart from the composer's (`people`/`paths`). */
  constructor(rows: () => PersonRow[], find: FindPaths, status: HTMLElement, prefix: string) {
    const dummy = document.createElement('textarea');
    const ids = { people: `${prefix}-people`, paths: `${prefix}-paths` };
    this.people = new PeoplePicker(dummy, rows, status, () => this.changed(), { list: ids.people, opt: `${prefix}-p` });
    this.paths = new PathPicker(dummy, find, status, () => this.changed(), { list: ids.paths, opt: `${prefix}-path`, people: ids.people });
  }

  private field: TextField | null = null;
  private onChange: (() => void) | null = null;

  /** Wire a note field. Call it BEFORE the field's own keydown handler is added, so a key a list takes stops here.
   *  `host`: where the lists are shown (a positioned container, the lists sit above it); `changed`: the text
   *  was changed by a pick (the field's own input handling, e.g. a debounced note post). */
  attach(field: TextField, host: HTMLElement, changed?: () => void): void {
    field.setAttribute('aria-autocomplete', 'list');
    field.setAttribute('aria-controls', this.people.list.id);
    const point = () => {
      if (this.field === field) return;
      this.close();
      this.field = field;
      this.onChange = changed ?? null;
      this.people.field = field;
      this.paths.ta = field;
      host.prepend(this.people.list, this.paths.list);
    };
    field.addEventListener('focus', point);
    field.addEventListener('input', () => { point(); this.update(); });
    field.addEventListener('click', () => { point(); this.update(); });
    const f = field as HTMLElement; // the union of two element types loses the keyboard event typing
    f.addEventListener('keyup', e => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) this.update(); });
    field.addEventListener('blur', () => setTimeout(() => { if (this.field === field && document.activeElement !== field) this.close(); }, 0));
    f.addEventListener('keydown', e => {
      if (e.isComposing || e.keyCode === 229 || this.field !== field) return;
      if (this.paths.onKey(e) || this.people.onKey(e)) e.stopImmediatePropagation();
    });
  }

  /** The host's rows for a findPaths (an answer to another picker's seq is dropped by the picker). */
  onPaths(m: { type: 'paths'; v: 1; seq: number; items: PathHit[]; up?: string | null }): void { this.paths.onPaths(m); }

  get isOpen(): boolean { return this.people.isOpen || this.paths.isOpen; }

  close(): void { this.people.close(); this.paths.close(); }

  private update(): void { this.people.update(); this.paths.update(); }

  private changed(): void { this.onChange?.(); }
}
