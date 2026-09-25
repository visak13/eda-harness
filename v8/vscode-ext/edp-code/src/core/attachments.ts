// Chat attachments, the pure half (C12 s-85dd35a166; design §13 row C12). The board's upload rules (25 MB
// cap, sniffed type allowlist) are NOT repeated here: the host uploads and shows the board's refusal. No
// `vscode` import.
import { ATTACH_MAX, ARTIFACT_ID, type ArtifactInfo, type AttachmentRef, type PendingAttachment } from './chatProtocol';

/** The four types the board serves inline (uploads.py `_INLINE_IMAGE_TYPES`); an SVG is a file. */
export const INLINE_IMAGES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp']);

/** A thread row's `attachments` entry (views.py `_attachments`). */
export type BoardAttachment = { id: string; form: string; filename?: string; content_type?: string; note?: string };
/** `GET /v1/artifacts/{id}` (the live path: a message row carries only artifact ids). */
export type BoardArtifact = { id: string; form: string; uri: string; filename?: string; content_type?: string; note?: string; staged?: boolean; has_content?: boolean };

export const attachmentRef = (a: BoardAttachment | BoardArtifact): AttachmentRef => {
  const ct = a.content_type ?? '';
  // an upload's uri is its own content route; a recorded artifact (url, repo_ref, file path) is named by its uri
  const uri = 'uri' in a && typeof a.uri === 'string' && !a.uri.startsWith('/v1/artifacts/') ? a.uri : '';
  return { id: a.id, name: a.filename || uri || a.id, contentType: ct, image: INLINE_IMAGES.has(ct) };
};

/** Board attachment rows → refs: well-formed ids only, at most ATTACH_MAX. */
export function attachmentRefs(rows: unknown): AttachmentRef[] {
  if (!Array.isArray(rows)) return [];
  return rows.filter((r): r is BoardAttachment => !!r && typeof r === 'object' && typeof r.id === 'string' && ARTIFACT_ID.test(r.id))
    .slice(0, ATTACH_MAX).map(attachmentRef);
}

/** `1.2 MB`, `830 KB`, `12 B`. */
export function fmtSize(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n) || n < 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

/** An attachments-only send still says what it carries, for agents that read text only. */
export const attachText = (text: string, names: string[]) =>
  text.trim() ? text : `Attached: ${names.map(n => `\`${n.replace(/`/g, "'")}\``).join(', ')}`;

/** How a full-size open works: an image in VS Code's image preview, text in an editor tab, anything else
 *  (pdf, zip) is saved where the user picks (a download). */
export function openMode(contentType: string): 'preview' | 'text' | 'save' {
  if (INLINE_IMAGES.has(contentType)) return 'preview';
  if (contentType.startsWith('text/') || contentType === 'application/json' || contentType === 'image/svg+xml') return 'text';
  return 'save';
}

const EXT: Record<string, string> = {
  'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp', 'image/svg+xml': 'svg',
  'application/pdf': 'pdf', 'application/zip': 'zip', 'application/json': 'json', 'text/markdown': 'md', 'text/plain': 'txt',
};

/** A file name that is safe on Windows and POSIX: a basename, no reserved or control characters, no
 *  trailing dot/space, ≤100 chars, never a device name; the sniffed type's extension when it has none. */
export function safeFileName(name: string, id: string, contentType: string): string {
  let n = (name || '').replace(/\\/g, '/').split('/').pop() ?? '';
  n = n.replace(/[\u0000-\u001f\u007f<>:"|?*]/g, '_').replace(/[. ]+$/, '').trim();
  if (/^(con|prn|aux|nul|com\d|lpt\d)(\.|$)/i.test(n)) n = `_${n}`;
  if (!n || n === '.' || n === '..') n = id;
  if (n.length > 100) { const dot = n.lastIndexOf('.'); const ext = dot > 0 && n.length - dot <= 10 ? n.slice(dot) : ''; n = n.slice(0, 100 - ext.length) + ext; }
  const ext = EXT[contentType];
  return ext && !/\.[A-Za-z0-9]{1,8}$/.test(n) ? `${n}.${ext}` : n;
}

/** The staged uploads a send may carry: every id must be one the host holds for that thread. */
export function pickStaged(held: readonly PendingAttachment[], ids: readonly string[]): { ok: PendingAttachment[] } | { error: string } {
  const out: PendingAttachment[] = [];
  for (const id of ids) {
    const p = held.find(x => x.id === id);
    if (!p) return { error: 'Not sent: an attachment is no longer staged here; attach it again.' };
    out.push(p);
  }
  return { ok: out };
}

/** Artifact infos, bounded by the bytes of their thumbnails: a session cache keyed by artifact id, least
 *  recently used out first (a re-rendered thread never decodes again while its infos fit). */
export class InfoCache {
  private map = new Map<string, ArtifactInfo>();
  private bytes = 0;
  constructor(private maxBytes = 48 * 1024 * 1024) {}
  private cost = (i: ArtifactInfo) => (i.thumb?.length ?? 0) + 64;
  get(id: string): ArtifactInfo | undefined {
    const i = this.map.get(id);
    if (i) { this.map.delete(id); this.map.set(id, i); }
    return i;
  }
  set(i: ArtifactInfo): void {
    const old = this.map.get(i.id);
    if (old) { this.bytes -= this.cost(old); this.map.delete(i.id); }
    this.map.set(i.id, i);
    this.bytes += this.cost(i);
    for (const [k, v] of this.map) {
      if (this.bytes <= this.maxBytes || k === i.id) break;
      this.map.delete(k); this.bytes -= this.cost(v);
    }
  }
  get size(): number { return this.map.size; }
  get used(): number { return this.bytes; }
}
