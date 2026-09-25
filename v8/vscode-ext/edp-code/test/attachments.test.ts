// C12 attachments (s-85dd35a166): the protocol gate for attach/drop/resolve/open and sends with
// attachments, the pure helpers, the board client's upload/content calls, and the thread mapping.
import { describe, expect, it, vi } from 'vitest';
import { boardClient, type Creds } from '../src/core/api';
import { attachmentRefs, attachText, fmtSize, InfoCache, openMode, pickStaged, safeFileName } from '../src/core/attachments';
import { ATTACH_MAX, ATTACH_TRANSPORT_MAX, parseInbound, refusedAttach } from '../src/core/chatProtocol';
import { fromMessageRow, fromThreadRow } from '../src/core/thread';

const T = 's-85dd35a166', A = 'art-0123456789', B = 'art-abcdefabcd';
const TOKEN = 'tok-SECRET-c12';
const creds = async (): Promise<Creds> => ({ participant: 'owner', token: TOKEN });
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('parseInbound: attachments', () => {
  it('attach carries bytes (Uint8Array, ArrayBuffer or a view) with a clean name', () => {
    const bytes = new Uint8Array([1, 2, 3]);
    expect(parseInbound({ v: 1, type: 'attach', ticketId: T, name: 'shot.png', bytes })).toEqual({ v: 1, type: 'attach', ticketId: T, name: 'shot.png', bytes });
    expect(parseInbound({ v: 1, type: 'attach', ticketId: T, name: 'a', bytes: bytes.buffer })).toMatchObject({ bytes: new Uint8Array([1, 2, 3]) });
    expect(parseInbound({ v: 1, type: 'attach', ticketId: T, name: 'a', bytes: new DataView(bytes.buffer, 1) })).toMatchObject({ bytes: new Uint8Array([2, 3]) });
  });
  it('attach refuses empty, oversize, non-bytes, bad names and bad tickets', () => {
    const ok = { v: 1, type: 'attach', ticketId: T, name: 'a.txt', bytes: new Uint8Array([1]) };
    expect(parseInbound({ ...ok, bytes: new Uint8Array(0) })).toBeNull();
    expect(parseInbound({ ...ok, bytes: { byteLength: ATTACH_TRANSPORT_MAX + 1 } })).toBeNull();
    expect(parseInbound({ ...ok, bytes: [1, 2, 3] })).toBeNull();
    expect(parseInbound({ ...ok, bytes: 'AAAA' })).toBeNull();
    expect(parseInbound({ ...ok, name: '' })).toBeNull();
    expect(parseInbound({ ...ok, name: 'a\nb' })).toBeNull();
    expect(parseInbound({ ...ok, name: 'x'.repeat(256) })).toBeNull();
    expect(parseInbound({ ...ok, ticketId: 'x' })).toBeNull();
  });
  it('a refused attach is still answered with its ticket and a printable name', () => {
    expect(refusedAttach({ v: 1, type: 'attach', ticketId: T, name: 'a\u0007b', bytes: null })).toEqual({ ticketId: T, name: 'a_b' });
    expect(refusedAttach({ v: 1, type: 'attach', ticketId: 'nope' })).toBeUndefined();
    expect(refusedAttach({ v: 1, type: 'send', ticketId: T })).toBeUndefined();
  });
  it('dropAttachment, resolveArtifacts, openArtifact validate ids', () => {
    expect(parseInbound({ v: 1, type: 'dropAttachment', ticketId: T, id: A })).toEqual({ v: 1, type: 'dropAttachment', ticketId: T, id: A });
    expect(parseInbound({ v: 1, type: 'dropAttachment', ticketId: T, id: 'art-x' })).toBeNull();
    expect(parseInbound({ v: 1, type: 'resolveArtifacts', ids: [A, B, A] })).toEqual({ v: 1, type: 'resolveArtifacts', ids: [A, B] });
    expect(parseInbound({ v: 1, type: 'resolveArtifacts', ids: [] })).toBeNull();
    expect(parseInbound({ v: 1, type: 'resolveArtifacts', ids: Array(ATTACH_MAX + 1).fill(A) })).toBeNull();
    expect(parseInbound({ v: 1, type: 'resolveArtifacts', ids: ['../x'] })).toBeNull();
    expect(parseInbound({ v: 1, type: 'openArtifact', messageId: 'm-0123456789', id: A })).toEqual({ v: 1, type: 'openArtifact', messageId: 'm-0123456789', id: A });
    expect(parseInbound({ v: 1, type: 'openArtifact', messageId: 'm-0123456789', id: 'C:/x' })).toBeNull();
  });
  it('send: attachmentIds are well-formed ids; with some, the text may be empty', () => {
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: '', kind: 'note', attachmentIds: [A] }))
      .toEqual({ v: 1, type: 'send', ticketId: T, text: '', kind: 'note', attachmentIds: [A] });
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: '  ', kind: 'note', attachmentIds: [] })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: 'hi', kind: 'note', attachmentIds: ['nope'] })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: 'hi', kind: 'note', attachmentIds: A })).toBeNull();
    expect(parseInbound({ v: 1, type: 'send', ticketId: T, text: 'hi', kind: 'note' })).toEqual({ v: 1, type: 'send', ticketId: T, text: 'hi', kind: 'note' });
  });
});

describe('pure helpers', () => {
  it('fmtSize', () => {
    expect(fmtSize(12)).toBe('12 B');
    expect(fmtSize(2048)).toBe('2 KB');
    expect(fmtSize(1.5 * 1024 * 1024)).toBe('1.5 MB');
    expect(fmtSize(26 * 1024 * 1024)).toBe('26 MB');
    expect(fmtSize(null)).toBe('');
  });
  it('attachText names the files of an attachments-only send; a note is kept as is', () => {
    expect(attachText('', ['a.png', 'b`c.txt'])).toBe("Attached: `a.png`, `b'c.txt`");
    expect(attachText('look', ['a.png'])).toBe('look');
  });
  it('openMode: images preview, text opens, the rest saves', () => {
    expect(openMode('image/png')).toBe('preview');
    expect(openMode('text/markdown')).toBe('text');
    expect(openMode('application/json')).toBe('text');
    expect(openMode('image/svg+xml')).toBe('text'); // never rendered
    expect(openMode('application/pdf')).toBe('save');
    expect(openMode('application/zip')).toBe('save');
  });
  it('safeFileName: a Windows-safe basename with the sniffed extension', () => {
    expect(safeFileName('../../etc/passwd', A, 'text/plain')).toBe('passwd.txt');
    expect(safeFileName('a:b?.png', A, 'image/png')).toBe('a_b_.png');
    expect(safeFileName('CON', A, 'text/plain')).toBe('_CON.txt');
    expect(safeFileName('', A, 'application/pdf')).toBe(`${A}.pdf`);
    expect(safeFileName('notes. ', A, 'text/plain')).toBe('notes.txt');
    expect(safeFileName('x'.repeat(300) + '.json', A, 'application/json')).toHaveLength(100);
  });
  it('safeFileName: every Windows device name is prefixed; a cut name loses a trailing dot/space', () => {
    for (const d of ['COM¹.png', 'LPT²', 'CONIN$', 'conout$.txt', 'com9', 'aux.md']) expect(safeFileName(d, A, 'text/plain').startsWith('_')).toBe(true);
    expect(safeFileName('comet.txt', A, 'text/plain')).toBe('comet.txt');
    const cut = safeFileName('a'.repeat(99) + ' tail-without-extension', A, 'application/octet-stream');
    expect(cut).toBe('a'.repeat(99));
  });
  it('safeFileName: the extension agrees with the sniffed type, so the tab opens it right', () => {
    expect(safeFileName('notes.txt', A, 'image/png')).toBe('notes.txt.png'); // a PNG named .txt: image preview, not garbage text
    expect(safeFileName('x.png', A, 'text/plain')).toBe('x.png.txt');       // text named .png: a text tab, not a broken image
    expect(safeFileName('shot.jpeg', A, 'image/jpeg')).toBe('shot.jpeg');
    expect(safeFileName('build.log', A, 'text/plain')).toBe('build.log');   // a text name stays
    expect(safeFileName('icon.svg', A, 'image/svg+xml')).toBe('icon.svg');
  });
  it('pickStaged: every id must be held for the thread', () => {
    const held = [{ id: A, name: 'a', size: 1, contentType: 'text/plain' }];
    expect(pickStaged(held, [A])).toEqual({ ok: held });
    expect(pickStaged(held, [A, B])).toHaveProperty('error');
    expect(pickStaged(held, [])).toEqual({ ok: [] });
  });
  it('InfoCache: LRU by thumbnail bytes, a hit refreshes', () => {
    const c = new InfoCache(350);
    const info = (id: string, n: number) => ({ id, size: 1, thumb: 'x'.repeat(n), state: 'thumb' as const });
    c.set(info('a', 100)); c.set(info('b', 100));
    c.get('a');
    c.set(info("c", 100)); // 3 x 164 > 350: the least recent (b) goes
    expect(c.get('b')).toBeUndefined();
    expect(c.get('a')).toBeDefined();
    expect(c.get('c')).toBeDefined();
  });
});

describe('thread mapping', () => {
  it('thread rows carry attachments as refs; bad ids are dropped; images flagged by type', () => {
    const row = { id: 'm-0123456789', seq: 3, by: 'owner', to: null, kind: 'note', text: 'x', at: '2026-09-25T00:00:00+00:00', reply_to: null, code_context: null,
      attachments: [{ id: A, form: 'image', filename: 'shot.png', content_type: 'image/png', note: '' }, { id: B, form: 'file', filename: '', content_type: 'application/pdf' }, { id: '../x', form: 'file' }] };
    expect(fromThreadRow(T, row).attachments).toEqual([
      { id: A, name: 'shot.png', contentType: 'image/png', image: true }, { id: B, name: B, contentType: 'application/pdf', image: false }]);
    expect(fromThreadRow(T, { ...row, attachments: [] })).not.toHaveProperty('attachments');
  });
  it('a recorded (non-upload) artifact is named by its uri', () => {
    expect(attachmentRefs([{ id: A, form: 'url', uri: 'https://x.example/r', content_type: '' }])[0].name).toBe('https://x.example/r');
    expect(attachmentRefs([{ id: A, form: 'image', uri: `/v1/artifacts/${A}/content`, content_type: 'image/png' }])[0].name).toBe(A);
  });
  it('live rows take the refs the host resolved', () => {
    const m = { id: 'm-0123456789', ticket_id: T, created_at: 'x', created_by: 'o', to: null, kind: 'note', text: 't', reply_to: null, artifacts: [A] };
    expect(fromMessageRow(m, 1, [{ id: A, name: 'a', contentType: '', image: false }]).attachments).toHaveLength(1);
    expect(fromMessageRow(m, 1)).not.toHaveProperty('attachments');
  });
});

describe('boardClient: upload and content', () => {
  it('upload posts multipart (file + ticket_id) with the creds, no JSON content-type', async () => {
    const f = vi.fn(async (_u: unknown, _i?: RequestInit) => json(200, { ok: true, value: { id: A, form: 'image', uri: '', staged: true, content_type: 'image/png', filename: 'shot.png' } }));
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    const art = await c.upload(T, 'shot.png', new Uint8Array([137, 80, 78, 71]));
    expect(art.id).toBe(A);
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toBe('http://127.0.0.1:9400/v1/artifacts/upload');
    expect(init!.method).toBe('POST');
    const h = init!.headers as Record<string, string>;
    expect(h['X-Token']).toBe(TOKEN);
    expect(h['Content-Type']).toBeUndefined(); // fetch sets the multipart boundary
    const form = init!.body as FormData;
    expect(form.get('ticket_id')).toBe(T);
    const file = form.get('file') as File;
    expect(file.name).toBe('shot.png');
    expect([...new Uint8Array(await file.arrayBuffer())]).toEqual([137, 80, 78, 71]);
    expect(init!.redirect).toBe('manual');
  });
  it("a 413/415 refusal is the board's own message", async () => {
    const f = async () => json(413, { ok: false, error: { code: 'too_large', message: 'the file is over the 25 MB upload limit' } });
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    await expect(c.upload(T, 'big.bin', new Uint8Array([1]))).rejects.toMatchObject({ code: 'too_large', message: 'the file is over the 25 MB upload limit', status: 413 });
    const g = async () => json(415, { ok: false, error: { code: 'unsupported_type', message: 'that file type is not accepted; allowed: images, pdf, text, markdown, json, log, zip, svg' } });
    await expect(boardClient('http://127.0.0.1:9400', creds, g as unknown as typeof fetch).upload(T, 'a.exe', new Uint8Array([0x4d, 0x5a, 0]))).rejects.toMatchObject({ code: 'unsupported_type', status: 415 });
  });
  it('content returns bytes and type; a probe reads only the length and cancels the body', async () => {
    const body = new Uint8Array([1, 2, 3, 4, 5]);
    const f = vi.fn(async () => new Response(body, { status: 200, headers: { 'content-type': 'application/pdf', 'content-length': '5' } }));
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    expect(await c.content(A)).toEqual({ bytes: body, type: 'application/pdf', size: 5 });
    expect(await c.content(A, true)).toEqual({ bytes: null, type: 'application/pdf', size: 5 });
    expect(String((f.mock.calls[0] as unknown as [URL])[0])).toBe(`http://127.0.0.1:9400/v1/artifacts/${A}/content`);
  });
  it('content: a board refusal is a BoardError; the token never appears in the message', async () => {
    const f = async () => json(404, { ok: false, error: { code: 'not_found', message: `artifact ${A} has no stored content` } });
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    const e = await c.content(A).catch(x => x);
    expect(e).toMatchObject({ code: 'not_found', status: 404 });
    expect(String(e.message)).not.toContain(TOKEN);
  });
});
