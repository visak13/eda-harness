// @vitest-environment jsdom
// C12 webview attachments (s-85dd35a166): clip / drop / paste post the file's bytes to the host (never a
// fetch), staged chips and their removal, a refusal keeps the draft, thumbnails render from data: URIs.
import { beforeEach, describe, expect, it } from 'vitest';
import { cleanName, initAttach, pastedName } from '../webview/attach';
import type { ChatMessage } from '../src/core/chatProtocol';

const T = 's-85dd35a166', A = 'art-0123456789';

function setup() {
  document.body.replaceChildren();
  const box = document.createElement('div'), slot = document.createElement('span'), ta = document.createElement('textarea');
  const err = document.createElement('div'), status = document.createElement('div');
  box.append(slot, ta);
  document.body.append(box, err, status);
  const posts: Record<string, unknown>[] = [];
  let changes = 0;
  const ui = initAttach({ box, slot, ta, err, status, ticket: () => T, post: m => posts.push(m as Record<string, unknown>), onChange: () => changes++ });
  return { ui, box, slot, ta, err, status, posts, changes: () => changes };
}
const file = (name: string, bytes: number[], type = 'application/octet-stream') => new File([new Uint8Array(bytes)], name, { type });
const flush = () => new Promise(r => setTimeout(r, 0));

function drop(target: HTMLElement, files: File[]) {
  const ev = new Event('drop', { bubbles: true, cancelable: true }) as Event & { dataTransfer: unknown };
  Object.defineProperty(ev, 'dataTransfer', { value: { files, types: ['Files'] } });
  target.dispatchEvent(ev);
  return ev;
}

describe('names', () => {
  it('a pasted screenshot gets a timestamped name; a real name is kept', () => {
    const at = new Date(2026, 8, 25, 13, 5, 9);
    expect(pastedName({ name: 'image.png', type: 'image/png' }, at)).toBe('pasted-20260925-130509.png');
    expect(pastedName({ name: '', type: 'image/jpeg' }, at)).toBe('pasted-20260925-130509.jpg');
    expect(pastedName({ name: 'diagram.png', type: 'image/png' }, at)).toBe('diagram.png');
  });
  it('cleanName strips control characters and bounds the length', () => {
    expect(cleanName('a\u0000b\n.txt')).toBe('a_b_.txt');
    expect(cleanName('  ')).toBe('file');
    expect(cleanName('x'.repeat(300) + '.png')).toHaveLength(255);
  });
});

describe('the composer', () => {
  let s: ReturnType<typeof setup>;
  beforeEach(() => { s = setup(); });

  it('puts a clip button in the tool slot', () => {
    const clip = s.slot.querySelector<HTMLButtonElement>('#attach')!;
    expect(clip.getAttribute('aria-label')).toBe('Attach files');
    expect(s.slot.querySelector<HTMLInputElement>('#attach-input')!.type).toBe('file');
  });

  it('a drop posts `attach` with the bytes, shows the upload, and a pending answer turns it into a chip', async () => {
    const ev = drop(s.box, [file('notes.md', [35, 32, 104, 105])]);
    expect(ev.defaultPrevented).toBe(true);
    await flush(); await flush();
    expect(s.posts).toEqual([{ type: 'attach', ticketId: T, name: 'notes.md', bytes: new Uint8Array([35, 32, 104, 105]) }]);
    expect(s.ui.busy()).toBe(true);
    expect(s.box.querySelector('.pend.uploading')!.textContent).toBe('Uploading 1…');
    s.ui.setPending(T, [{ id: A, name: 'notes.md', size: 4, contentType: 'text/markdown' }]);
    expect(s.ui.busy()).toBe(false);
    expect(s.ui.ids()).toEqual([A]);
    expect(s.box.querySelector('.pend-name')!.textContent).toBe('notes.md');
    expect(s.box.querySelector('.pend-size')!.textContent).toBe('4 B');
  });

  it('a pasted screenshot uploads under a timestamped name; a text paste is left alone', async () => {
    const png = file('image.png', [137, 80, 78, 71], 'image/png');
    const ev = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(ev, 'clipboardData', { value: { files: [png] } });
    s.ta.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    await flush(); await flush();
    expect(s.posts[0]).toMatchObject({ type: 'attach', ticketId: T, bytes: new Uint8Array([137, 80, 78, 71]) });
    expect(String(s.posts[0].name)).toMatch(/^pasted-\d{8}-\d{6}\.png$/);
    const text = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(text, 'clipboardData', { value: { files: [] } });
    s.ta.dispatchEvent(text);
    expect(text.defaultPrevented).toBe(false);
  });

  it('a refusal shows the board\'s message and leaves the draft untouched', async () => {
    s.ta.value = 'my draft';
    drop(s.box, [file('big.zip', [80, 75, 3, 4])]);
    await flush(); await flush();
    s.ui.failed(T, 'Not attached: big.zip: the file is over the 25 MB upload limit');
    expect(s.err.textContent).toBe('Not attached: big.zip: the file is over the 25 MB upload limit');
    expect(s.ta.value).toBe('my draft');
    expect(s.ui.busy()).toBe(false);
    expect(s.ui.ids()).toEqual([]);
  });

  it('an empty file is refused locally, nothing is posted', async () => {
    drop(s.box, [file('empty.txt', [])]);
    await flush(); await flush();
    expect(s.posts).toEqual([]);
    expect(s.err.textContent).toBe('Not attached: empty.txt is empty.');
  });

  it('× removes a staged chip and tells the host', () => {
    s.ui.setPending(T, [{ id: A, name: 'a.txt', size: 2, contentType: 'text/plain' }]);
    s.box.querySelector<HTMLButtonElement>('.pend-remove')!.click();
    expect(s.posts).toEqual([{ type: 'dropAttachment', ticketId: T, id: A }]);
    expect(s.ui.ids()).toEqual([]);
  });

  it('an answer for another thread is ignored', () => {
    s.ui.setPending('s-0000000000', [{ id: A, name: 'a', size: 1, contentType: '' }]);
    expect(s.ui.ids()).toEqual([]);
  });
});

describe('a message\'s attachments', () => {
  const msg = (atts: ChatMessage['attachments']): ChatMessage => ({ type: 'message', seq: 1, id: 'm-0123456789', ticket_id: T, created_at: '', created_by: 'o',
    to: null, kind: 'note', text: '', reply_to: null, code_context: null, attachments: atts });

  it('an image shows a data: thumbnail once the host answers; a file shows name + size; clicks open', () => {
    const s = setup();
    const B = 'art-abcdefabcd';
    const row = s.ui.render(msg([{ id: A, name: 'shot.png', contentType: 'image/png', image: true }, { id: B, name: 'r.pdf', contentType: 'application/pdf', image: false }]))!;
    document.body.append(row);
    expect(row.querySelectorAll('.att')).toHaveLength(2);
    expect(row.querySelector('img')).toBeNull(); // nothing until the host answers
    const thumb = 'data:image/png;base64,iVBORw0KGgo=';
    s.ui.infos([{ id: A, size: 2048, thumb, state: 'thumb' }, { id: B, size: 5 * 1024 * 1024, thumb: null, state: 'file' }]);
    const img = row.querySelector<HTMLImageElement>('img.att-thumb')!;
    expect(img.getAttribute('src')).toBe(thumb);
    expect(img.alt).toBe('shot.png');
    const f = row.querySelector<HTMLElement>(`[data-artifact="${B}"]`)!;
    expect(f.querySelector('.att-name')!.textContent).toBe('r.pdf');
    expect(f.querySelector('.att-size')!.textContent).toBe('5.0 MB');
    f.click();
    expect(s.posts.at(-1)).toEqual({ type: 'openArtifact', messageId: 'm-0123456789', id: B });
  });

  it('an image over the caps is a file row that says why and still opens', () => {
    const s = setup();
    const row = s.ui.render(msg([{ id: A, name: 'huge.png', contentType: 'image/png', image: true }]))!;
    document.body.append(row);
    s.ui.infos([{ id: A, size: 20e6, thumb: null, state: 'file', note: 'over the 8 MB thumbnail cap' }]);
    expect(row.querySelector('img')).toBeNull();
    expect(row.querySelector('.att-note')!.textContent).toBe('over the 8 MB thumbnail cap');
    expect(row.querySelector('.att')!.getAttribute('aria-label')).toContain('open full size');
  });

  it('a message without attachments renders nothing', () => {
    expect(setup().ui.render(msg(undefined))).toBeNull();
  });
});

describe('lazy resolve', () => {
  it('ids not yet known are asked for in one batch (no IntersectionObserver: at once)', async () => {
    const s = setup();
    const m: ChatMessage = { type: 'message', seq: 1, id: 'm-0123456789', ticket_id: T, created_at: '', created_by: 'o', to: null, kind: 'note', text: '',
      reply_to: null, code_context: null, attachments: [{ id: A, name: 'a.png', contentType: 'image/png', image: true }, { id: 'art-abcdefabcd', name: 'b', contentType: '', image: false }] };
    s.ui.render(m);
    await new Promise(r => setTimeout(r, 80));
    expect(s.posts).toEqual([{ type: 'resolveArtifacts', ids: [A, 'art-abcdefabcd'] }]);
    s.ui.infos([{ id: A, size: 1, thumb: null, state: 'file' }]);
    s.posts.length = 0;
    s.ui.render(m);
    await new Promise(r => setTimeout(r, 80));
    expect(s.posts).toEqual([{ type: 'resolveArtifacts', ids: ['art-abcdefabcd'] }]); // a known one is never asked again
  });

  it('a passing failure (retry) shows now and is asked for again on the next render', async () => {
    const s = setup();
    const m: ChatMessage = { type: 'message', seq: 1, id: 'm-0123456789', ticket_id: T, created_at: '', created_by: 'o', to: null, kind: 'note', text: '',
      reply_to: null, code_context: null, attachments: [{ id: A, name: 'a.png', contentType: 'image/png', image: true }] };
    const row = s.ui.render(m)!;
    document.body.append(row);
    s.ui.infos([{ id: A, size: null, thumb: null, state: 'error', note: 'board unreachable', retry: true }]);
    expect(row.querySelector('.att-note')!.textContent).toBe('unavailable: board unreachable');
    await new Promise(r => setTimeout(r, 80));
    s.posts.length = 0;
    s.ui.render(m);
    await new Promise(r => setTimeout(r, 80));
    expect(s.posts).toEqual([{ type: 'resolveArtifacts', ids: [A] }]);
  });
});
