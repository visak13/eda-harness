import { describe, expect, it, vi } from 'vitest';
import { BoardError, boardClient, unsafeBoardUrl, type Creds } from '../src/core/api';

const TOKEN = 'tok-SECRET-5f1e9c';
const creds = async (): Promise<Creds> => ({ participant: 'owner', token: TOKEN });
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('boardClient', () => {
  it('sends X-Participant / X-Token and returns value', async () => {
    const f = vi.fn(async (_u: unknown, _i?: RequestInit) => json(200, { ok: true, value: [{ id: 'owner' }] }));
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    expect(await c.participants()).toEqual([{ id: 'owner' }]);
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toBe('http://127.0.0.1:9400/v1/participants');
    expect((init!.headers as Record<string, string>)['X-Participant']).toBe('owner');
    expect((init!.headers as Record<string, string>)['X-Token']).toBe(TOKEN);
    expect(init!.signal).toBeInstanceOf(AbortSignal);
    expect(init!.redirect).toBe('manual'); // the token never follows a redirect
  });
  it('a redirect answer is bad_response, not followed', async () => {
    const f = async () => new Response(null, { status: 302, headers: { location: 'http://evil.example/' } });
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    await expect(c.participants()).rejects.toMatchObject({ code: 'bad_response', status: 302 });
  });
  it('POSTs the message body as JSON', async () => {
    const f = vi.fn(async () => json(200, { ok: true, value: { id: 'm-1' } }));
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    const cc = { repo_root: 'C:\\r', path: 'a', line_start: 1, line_end: 1, commit: null, dirty: false, snippet: 'x', snippet_sha: 'y' };
    await c.sendMessage({ ticket_id: 's-1', to: 'owner', kind: 'question', text: 't', code_context: cc });
    const init = (f.mock.calls[0] as unknown as [URL, RequestInit])[1];
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toMatchObject({ ticket_id: 's-1', to: 'owner', code_context: cc });
  });
  it('ok:false -> BoardError(code, message) carrying the board text', async () => {
    const f = async () => json(400, { ok: false, error: { code: 'invalid', message: 'code_context.line_end: must be >= line_start' } });
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    await expect(c.participants()).rejects.toMatchObject({ code: 'invalid', message: 'code_context.line_end: must be >= line_start', status: 400 });
  });
  it('non-JSON 502 -> bad_response', async () => {
    const f = async () => new Response('<html>bad gateway</html>', { status: 502 });
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    await expect(c.sessions()).rejects.toMatchObject({ code: 'bad_response', status: 502 });
  });
  it('no creds -> not_signed_in without calling fetch', async () => {
    const f = vi.fn();
    const c = boardClient('http://127.0.0.1:9400', async () => undefined, f as unknown as typeof fetch);
    await expect(c.participants()).rejects.toMatchObject({ code: 'not_signed_in' });
    expect(f).not.toHaveBeenCalled();
  });
  it('a hung board times out (the signal aborts)', async () => {
    const f = (_u: unknown, init: RequestInit) => new Promise<Response>((_, rej) =>
      init.signal!.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), { name: 'TimeoutError' }))));
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch, () => {}, 50);
    await expect(c.participants()).rejects.toMatchObject({ code: 'timeout' });
  });
  it('an unreachable board is a BoardError, not a raw fetch failure', async () => {
    const f = async () => { throw new TypeError('fetch failed'); };
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    await expect(c.participants()).rejects.toBeInstanceOf(BoardError);
  });
  it('whoami uses the creds being tried, not the stored ones', async () => {
    const f = vi.fn(async (_u: unknown, _i?: RequestInit) => json(200, { ok: true, value: { id: 'x', handle: 'x' } }));
    const c = boardClient('http://127.0.0.1:9400', async () => undefined, f as unknown as typeof fetch);
    await c.whoami({ participant: 'new one', token: 'n' });
    expect(String(f.mock.calls[0][0])).toBe('http://127.0.0.1:9400/v1/participants/new%20one');
  });
});

describe('creds only to a loopback or https board', () => {
  it.each(['http://127.0.0.1:9400', 'http://localhost:9400', 'https://board.example.com'])('%s is allowed', u => expect(unsafeBoardUrl(u)).toBeUndefined());
  it.each(['http://192.168.1.5:9400', 'http://board.example.com', 'ftp://127.0.0.1'])('%s is refused', u => expect(unsafeBoardUrl(u)).toMatch(/loopback|https/));
  it('a refused URL never calls fetch', async () => {
    const f = vi.fn();
    const c = boardClient('http://10.0.0.2:9400', creds, f as unknown as typeof fetch);
    await expect(c.participants()).rejects.toMatchObject({ code: 'unsafe_board_url' });
    expect(f).not.toHaveBeenCalled();
  });
});

describe('the token never reaches the output channel or an error message', () => {
  it('log lines and errors across success, 401, 400, 502, timeout and unreachable carry no token', async () => {
    const lines: string[] = [];
    const errors: string[] = [];
    const replies = [
      async () => json(200, { ok: true, value: [] }),
      async () => json(401, { ok: false, error: { code: 'auth', message: 'bad token for owner' } }),
      async () => json(400, { ok: false, error: { code: 'invalid', message: 'code_context.path: must use forward slashes' } }),
      async () => new Response('nope', { status: 502 }),
      async () => { throw Object.assign(new Error('t'), { name: 'TimeoutError' }); },
      async () => { throw new TypeError('fetch failed'); },
    ];
    for (const r of replies) {
      const c = boardClient('http://127.0.0.1:9400', creds, r as unknown as typeof fetch, l => lines.push(l));
      await c.participants().catch((e: Error) => errors.push(`${e.message} ${JSON.stringify(e)}`));
    }
    expect(lines.length).toBe(6);
    for (const l of lines) expect(l).toMatch(/^GET \/v1\/participants -> \S+ \(\d+ ms\)$/);
    expect([...lines, ...errors].join('\n')).not.toContain(TOKEN);
  });
});
