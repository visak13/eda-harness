// Chat attachments in the webview (C12 s-85dd35a166; design §13 row C12). No network: a file the user
// clips, drops or pastes is read here and posted to the host, which uploads it with the seat's creds; an
// attachment on a message renders from what the host posts back (a `data:` thumbnail, a size). The board's
// cap and type allowlist decide; this file only refuses what is too big to post (ATTACH_TRANSPORT_MAX).
import type { ArtifactInfo, AttachmentRef, ChatMessage, PendingAttachment, ViewToHost } from '../src/core/chatProtocol';
import { ATTACH_MAX, ATTACH_TRANSPORT_MAX, isAttachName } from '../src/core/chatProtocol';
import { fmtSize } from '../src/core/attachments';

type Intent = ViewToHost extends infer T ? (T extends unknown ? Omit<T, 'v'> : never) : never;
type Post = (m: Intent) => void;

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

/** A pasted screenshot arrives as `image.png`: give it a name that says when. */
export function pastedName(f: { name: string; type: string }, now = new Date()): string {
  const generic = !f.name || /^image\.(png|jpe?g|gif|webp)$/i.test(f.name);
  if (!generic) return f.name;
  const p = (n: number) => String(n).padStart(2, '0');
  const ext = (f.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
  return `pasted-${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}.${ext}`;
}

/** A name the host accepts: control characters out, at most 255 chars (the extension kept). */
export function cleanName(n: string): string {
  let s = n.replace(/[\u0000-\u001f\u007f]/g, '_').trim() || 'file';
  if (s.length > 255) { const dot = s.lastIndexOf('.'); const ext = dot > 0 && s.length - dot <= 10 ? s.slice(dot) : ''; s = s.slice(0, 255 - ext.length) + ext; }
  return isAttachName(s) ? s : 'file';
}

export type AttachUi = {
  /** the staged uploads a send carries */
  ids(): string[];
  /** uploads still in flight: a send waits for them */
  busy(): boolean;
  setPending(ticketId: string | null, p: PendingAttachment[]): void;
  failed(ticketId: string, text: string): void;
  /** the thread changed or the view was re-sent: forget in-flight counts, re-seed known infos */
  reset(ticketId: string | null, pending: PendingAttachment[], infos: ArtifactInfo[]): void;
  infos(items: ArtifactInfo[]): void;
  /** a message's attachments row (images as thumbnails, files as name + size), or null */
  render(m: ChatMessage): HTMLElement | null;
};

export function initAttach(o: {
  box: HTMLElement; slot: HTMLElement; ta: HTMLTextAreaElement; err: HTMLElement; status: HTMLElement;
  ticket: () => string | null; post: Post; onChange: () => void;
}): AttachUi {
  let ticket: string | null = null;
  let pending: PendingAttachment[] = [];
  let uploading = 0;
  const known = new Map<string, ArtifactInfo>();
  /** a known info that will not change; a `retry` one (board unreachable, worker timeout) is asked for again on the next render */
  const settled = (id: string) => { const i = known.get(id); return !!i && !i.retry; };

  // -- the composer: a clip button in #composer-tools, drop onto the box, paste into the text ---------------
  const input = el('input');
  input.type = 'file';
  input.multiple = true;
  input.id = 'attach-input';
  input.hidden = true;
  input.tabIndex = -1;
  const clip = el('button', 'tool attach', '📎');
  clip.type = 'button';
  clip.id = 'attach';
  clip.title = 'Attach files (or hold Shift and drop them here, or paste a screenshot)';
  clip.setAttribute('aria-label', 'Attach files');
  clip.addEventListener('click', () => input.click());
  input.addEventListener('change', () => { if (input.files?.length) void ingest([...input.files]); input.value = ''; });
  o.slot.append(clip, input);

  const list = el('ul', 'pending');
  list.id = 'attachments';
  list.setAttribute('aria-label', 'Attachments, sent with this message');
  list.hidden = true;
  o.box.prepend(list);

  const veil = el('div', 'drop-veil', 'Drop to attach');
  veil.hidden = true;
  o.box.append(veil);
  const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes('Files');
  o.box.addEventListener('dragover', e => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer!.dropEffect = 'copy'; veil.hidden = false; });
  o.box.addEventListener('dragleave', e => { if (!o.box.contains(e.relatedTarget as Node | null)) veil.hidden = true; });
  o.box.addEventListener('drop', e => {
    veil.hidden = true;
    if (!e.dataTransfer?.files.length) return;
    e.preventDefault();
    void ingest([...e.dataTransfer.files]);
  });
  o.ta.addEventListener('paste', e => {
    const files = [...(e.clipboardData?.files ?? [])];
    if (!files.length) return; // plain text pastes as text
    e.preventDefault();
    void ingest(files.map(f => ({ file: f, name: pastedName(f) })));
  });

  async function ingest(files: (File | { file: File; name: string })[]) {
    const t = o.ticket();
    if (!t) return;
    o.err.textContent = '';
    for (const x of files) {
      const f = x instanceof File ? x : x.file;
      const name = cleanName(x instanceof File ? f.name : x.name);
      if (pending.length + uploading >= ATTACH_MAX) { o.err.textContent = `Not attached: ${name}: at most ${ATTACH_MAX} attachments per message.`; continue; }
      if (f.size === 0) { o.err.textContent = `Not attached: ${name} is empty.`; continue; }
      // a transport guard, not the upload rule: the board's own cap refuses far below this
      if (f.size > ATTACH_TRANSPORT_MAX) { o.err.textContent = `Not attached: ${name} (${fmtSize(f.size)}) is too large to send through the chat panel.`; continue; }
      let bytes: Uint8Array;
      try { bytes = new Uint8Array(await f.arrayBuffer()); }
      catch { o.err.textContent = `Not attached: ${name} could not be read.`; continue; }
      if (o.ticket() !== t) return; // the thread changed while reading: nothing is sent to the new one
      uploading++;
      draw();
      o.post({ type: 'attach', ticketId: t, name, bytes });
    }
  }

  function draw() {
    list.replaceChildren(...pending.map(p => {
      const li = el('li', 'pend');
      li.dataset.artifact = p.id;
      const x = el('button', 'pend-remove', '×');
      x.type = 'button';
      x.title = `Remove ${p.name}`;
      x.setAttribute('aria-label', `Remove the attachment ${p.name}`);
      x.addEventListener('click', () => {
        const t = o.ticket();
        if (!t) return;
        pending = pending.filter(q => q.id !== p.id);
        o.post({ type: 'dropAttachment', ticketId: t, id: p.id });
        o.status.textContent = `Removed ${p.name}`;
        draw();
        o.ta.focus();
      });
      li.append(el('span', 'pend-icon', p.contentType.startsWith('image/') ? '🖼' : '📄'), el('span', 'pend-name', p.name),
        el('span', 'pend-size', fmtSize(p.size)), x);
      li.title = `${p.name} · ${fmtSize(p.size)}`;
      return li;
    }));
    if (uploading) {
      const li = el('li', 'pend uploading', `Uploading ${uploading}…`);
      li.setAttribute('role', 'status');
      list.append(li);
    }
    list.hidden = !pending.length && !uploading;
    o.onChange();
  }

  // -- a message's attachments: thumbnails and file rows, resolved lazily as they scroll into view ------------
  const wanted = new Set<string>();
  let flush: ReturnType<typeof setTimeout> | undefined;
  /** batch the ids that came into view; one request per ATTACH_MAX ids */
  const want = (id: string) => {
    if (settled(id)) return;
    wanted.add(id);
    flush ??= setTimeout(function send() {
      const ids = [...wanted].slice(0, ATTACH_MAX);
      ids.forEach(i => wanted.delete(i));
      if (ids.length) o.post({ type: 'resolveArtifacts', ids });
      flush = wanted.size ? setTimeout(send, 60) : undefined;
    }, 60);
  };
  const io = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      io!.unobserve(e.target);
      want((e.target as HTMLElement).dataset.artifact!);
    }
  }, { rootMargin: '200px 0px' }) : null;

  function fill(node: HTMLElement, a: AttachmentRef) {
    const i = known.get(a.id);
    node.replaceChildren();
    const size = i?.size != null ? fmtSize(i.size) : '';
    if (a.image && i?.state === 'thumb' && i.thumb) {
      const img = el('img', 'att-thumb');
      img.src = i.thumb; // a data: URI the host made; CSP img-src data:
      img.alt = a.name;
      node.className = 'att att-image';
      node.append(img);
      node.title = `${a.name}${size ? ` · ${size}` : ''}: open full size`;
      node.setAttribute('aria-label', `Image ${a.name}${size ? `, ${size}` : ''}: open full size`);
      return;
    }
    node.className = `att att-file${i?.state === 'error' ? ' att-error' : ''}${a.image && !i ? ' att-loading' : ''}`;
    node.append(el('span', 'att-icon', a.image ? '🖼' : '📄'), el('span', 'att-name', a.name));
    if (size) node.append(el('span', 'att-size', size));
    if (i?.note) node.append(el('span', 'att-note', i.state === 'error' ? `unavailable: ${i.note}` : i.note));
    const verb = a.image ? 'open full size' : 'open';
    node.title = `${a.name}${size ? ` · ${size}` : ''}: ${verb}`;
    node.setAttribute('aria-label', `${a.image ? 'Image' : 'File'} ${a.name}${size ? `, ${size}` : ''}: ${verb}`);
  }

  function render(m: ChatMessage): HTMLElement | null {
    if (!m.attachments?.length) return null;
    const row = el('div', 'atts');
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', `${m.attachments.length} ${m.attachments.length === 1 ? 'attachment' : 'attachments'}`);
    for (const a of m.attachments) {
      const b = el('button', 'att');
      b.type = 'button';
      b.dataset.artifact = a.id;
      b.addEventListener('click', () => o.post({ type: 'openArtifact', messageId: m.id, id: a.id }));
      fill(b, a);
      (b as HTMLElement & { _ref?: AttachmentRef })._ref = a;
      if (!settled(a.id)) { if (io) io.observe(b); else want(a.id); } // lazy: only rows that scroll into view
      row.append(b);
    }
    return row;
  }

  return {
    ids: () => pending.map(p => p.id),
    busy: () => uploading > 0,
    setPending(t, p) {
      if (t !== o.ticket()) return;
      if (uploading > 0 && p.length > pending.length) uploading--;
      pending = p;
      if (p.length) o.status.textContent = `${p.length} ${p.length === 1 ? 'attachment' : 'attachments'} ready to send`;
      draw();
    },
    failed(t, text) {
      if (t !== o.ticket()) return;
      if (uploading > 0) uploading--;
      o.err.textContent = text; // the draft is untouched
      draw();
    },
    reset(t, p, infos) {
      if (t !== ticket) uploading = 0;
      ticket = t;
      pending = p;
      for (const i of infos) known.set(i.id, i);
      draw();
    },
    infos(items) {
      for (const i of items) {
        known.set(i.id, i);
        document.querySelectorAll<HTMLElement>(`.att[data-artifact="${i.id}"]`).forEach(n => {
          const ref = (n as HTMLElement & { _ref?: AttachmentRef })._ref;
          if (ref) fill(n, ref);
        });
      }
    },
    render,
  };
}
