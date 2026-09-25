// The board REST client (strategyll-51e4dae0bc §7). No `vscode` import: creds, fetch and the log
// sink are injected, so tests stub them. The log sink receives `method path -> status (ms)` only:
// never headers, bodies or the Creds object (design §9, a token in the extension leaks).
import type { Anchor } from './anchor';

export type Creds = { participant: string; token: string };
export type Envelope<T> = { ok: true; value: T; hint?: string } | { ok: false; error: { code: string; message: string }; hint?: string };

export type Participant = { id: string; type: 'human' | 'agent'; role: string; handle: string };
export type Session = {
  id: string; participant_id: string; ticket_id: string | null; state: 'alive' | 'stalled' | 'dead' | 'parked';
  created_at?: string; last_output_at?: string | null; presence_stale_since?: string | null;
};
export type Ticket = { id: string; kind: string; title: string; status: string; assignee: string | null; epic_id?: string | null };
export type MessageKind = 'question' | 'steer' | 'finding' | 'note';
export type MessageIn = { ticket_id: string; to: string; kind: MessageKind; text: string; code_context: Anchor };
export type Message = { id: string; ticket_id: string; to: string | null; kind: string; text: string };

export class BoardError extends Error {
  constructor(public code: string, msg: string, public status: number) { super(msg); }
}

export const TIMEOUT_MS = 10_000;

/** Creds cross the wire only to a loopback board or over https. Returns the refusal, or undefined. */
export function unsafeBoardUrl(baseUrl: string): string | undefined {
  let u: URL;
  try { u = new URL(baseUrl); } catch { return `edp.boardUrl is not a URL: ${baseUrl}`; }
  if (u.protocol === 'https:') return undefined;
  if (u.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname)) return undefined;
  return `edp.boardUrl must be loopback (127.0.0.1/localhost) or https; refusing to send a token to ${u.origin}`;
}

export type Board = ReturnType<typeof boardClient>;

export function boardClient(baseUrl: string, creds: () => Promise<Creds | undefined>, f: typeof fetch = fetch,
  log: (line: string) => void = () => {}, timeoutMs = TIMEOUT_MS) {
  async function call<T>(method: 'GET' | 'POST', path: string, body?: unknown, override?: Creds): Promise<T> {
    const refused = unsafeBoardUrl(baseUrl);
    if (refused) throw new BoardError('unsafe_board_url', refused, 0);
    const c = override ?? await creds();
    if (!c) throw new BoardError('not_signed_in', 'Run "EDP: Sign in to board" first.', 0);
    const t0 = Date.now();
    let res: Response;
    try {
      res = await f(new URL(path, baseUrl), {
        // manual: a redirect must never carry X-Token to another origin (fetch strips only Authorization)
        method, signal: AbortSignal.timeout(timeoutMs), redirect: 'manual',
        headers: { 'X-Participant': c.participant, 'X-Token': c.token, ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      const name = (e as Error)?.name;
      const timedOut = name === 'TimeoutError' || name === 'AbortError';
      log(`${method} ${path} -> ${timedOut ? 'timeout' : 'unreachable'} (${Date.now() - t0} ms)`);
      throw new BoardError(timedOut ? 'timeout' : 'unreachable',
        timedOut ? `board did not answer within ${timeoutMs / 1000} s (${method} ${path})` : `board unreachable at ${new URL(baseUrl).origin}`, 0);
    }
    log(`${method} ${path} -> ${res.status} (${Date.now() - t0} ms)`);
    const env = (await res.json().catch(() => null)) as Envelope<T> | null;
    if (!env || typeof env !== 'object' || !('ok' in env)) throw new BoardError('bad_response', `HTTP ${res.status} from ${method} ${path}`, res.status);
    if (!env.ok) throw new BoardError(env.error?.code ?? 'error', env.error?.message ?? `HTTP ${res.status}`, res.status);
    return env.value;
  }
  return {
    participants: () => call<Participant[]>('GET', '/v1/participants'),
    /** Sign-in check: the new creds must read their own participant before they are stored. */
    whoami: (c: Creds) => call<Participant>('GET', `/v1/participants/${encodeURIComponent(c.participant)}`, undefined, c),
    sessions: () => call<Session[]>('GET', '/v1/sessions'),
    tickets: (q: Record<string, string> = {}) => call<Ticket[]>('GET', `/v1/tickets${Object.keys(q).length ? `?${new URLSearchParams(q)}` : ''}`),
    sendMessage: (m: MessageIn) => call<Message>('POST', '/v1/messages', m),
  };
}
