// The board REST client (strategyll-51e4dae0bc §7). No `vscode` import: creds, fetch and the log
// sink are injected, so tests stub them. The log sink receives `method path -> status (ms)` only:
// never headers, bodies or the Creds object (design §9, a token in the extension leaks).
import type { Anchor } from './anchor';
import type { BoardArtifact } from './attachments';
import { gatePath, type DecisionsHome, type InboxGate, type verdictBody } from './inbox';
import type { Reachable } from './people';
import type { DocMeta } from './docs';
import type { decideBody } from './reader';
import type { MessageRow, ThreadPage } from './thread';

export type Creds = { participant: string; token: string; origin?: string };
export type Envelope<T> = { ok: true; value: T; hint?: string } | { ok: false; error: { code: string; message: string }; hint?: string };

export type Participant = { id: string; type: 'human' | 'agent'; role: string; handle: string };
export type Session = {
  id: string; participant_id: string; ticket_id: string | null; state: 'alive' | 'stalled' | 'dead' | 'parked';
  created_at?: string; last_output_at?: string | null; presence_stale_since?: string | null;
};
export type Ticket = { id: string; kind: string; title: string; status: string; assignee: string | null; epic_id?: string | null; parent_id?: string | null; design_ref?: string | null };
export type MessageKind = 'question' | 'steer' | 'finding' | 'note';
export type MessageIn = { ticket_id: string; to: string; kind: MessageKind; text: string; code_context: Anchor };
export type Message = { id: string; ticket_id: string; to: string | null; kind: string; text: string };
/** A chat send (C3): `to` empty = a thread note, mentions do the waking; a composer code chip adds
 *  `code_context` (C4), always the host's own anchor. */
export type ChatSend = { ticket_id: string; to: string | null; kind: string; text: string; reply_to: string | null; code_context?: Anchor;
  /** C12: staged upload ids; the board finalises them with the message, all-or-nothing */
  artifacts?: string[] };
/** C12: `POST /v1/artifacts/upload` answers the staged artifact. */
export type Staged = BoardArtifact & { staged: true; content_type: string };
/** C12: an artifact's bytes (`GET /v1/artifacts/{id}/content`); `bytes` is null for a size-only probe. */
export type Content = { bytes: Uint8Array | null; type: string; size: number | null };

/** A board doc (`GET /v1/docs/{id}[?version=N]`): the body at that version, the doc's current fields, every version. */
export type BoardDoc = DocMeta & { body_md: string; resolution?: string | null; versions?: number[] };
/** `GET /v1/docs/{id}/context`: the design review this viewer may do from `source` on that version. */
export type DocContext = { ticket_id: string; source_title: string; design_ref: string; reviewed_version: number; current_version: number;
  gate_event_id: string | null; can_approve: boolean; can_review: boolean };

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
    const res = await request(method, path, body, override);
    const env = (await res.json().catch(() => null)) as Envelope<T> | null;
    if (!env || typeof env !== 'object' || !('ok' in env)) throw new BoardError('bad_response', `HTTP ${res.status} from ${method} ${path}`, res.status);
    if (!env.ok) throw new BoardError(env.error?.code ?? 'error', env.error?.message ?? `HTTP ${res.status}`, res.status);
    return env.value;
  }
  /** One board request: the creds headers, the timeout, no redirects. A FormData body goes as multipart
   *  (fetch sets the boundary); anything else as JSON. */
  async function request(method: 'GET' | 'POST', path: string, body?: unknown, override?: Creds, signal?: AbortSignal): Promise<Response> {
    const refused = unsafeBoardUrl(baseUrl);
    if (refused) throw new BoardError('unsafe_board_url', refused, 0);
    const c = override ?? await creds();
    if (!c) throw new BoardError('not_signed_in', 'Run "EDP: Sign in to board" first.', 0);
    if (c.origin && c.origin !== new URL(baseUrl).origin) {
      throw new BoardError('not_signed_in', 'Board address changed. Run "EDP: Sign in to board" again.', 0);
    }
    const t0 = Date.now();
    let res: Response;
    try {
      res = await f(new URL(path, baseUrl), {
        // manual: a redirect must never carry X-Token to another origin (fetch strips only Authorization)
        method, signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs), redirect: 'manual',
        headers: { 'X-Participant': c.participant, 'X-Token': c.token, ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}) },
        body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      const name = (e as Error)?.name;
      const timedOut = name === 'TimeoutError' || name === 'AbortError';
      log(`${method} ${path} -> ${timedOut ? 'timeout' : 'unreachable'} (${Date.now() - t0} ms)`);
      throw new BoardError(timedOut ? 'timeout' : 'unreachable',
        timedOut ? `board did not answer within ${timeoutMs / 1000} s (${method} ${path})` : `board unreachable at ${new URL(baseUrl).origin}`, 0);
    }
    log(`${method} ${path} -> ${res.status} (${Date.now() - t0} ms)`);
    return res;
  }
  /** An artifact's bytes, or (`probe`) only its type and Content-Length with the body cancelled. A refusal
   *  is the board's envelope, surfaced like any other call. */
  async function content(id: string, probe = false): Promise<Content> {
    const path = `/v1/artifacts/${encodeURIComponent(id)}/content`;
    const ctl = new AbortController();
    const res = await request('GET', path, undefined, undefined, ctl.signal);
    if (res.status !== 200) {
      const env = (await res.json().catch(() => null)) as Envelope<unknown> | null;
      if (env && typeof env === 'object' && 'ok' in env && !env.ok) throw new BoardError(env.error?.code ?? 'error', env.error?.message ?? `HTTP ${res.status}`, res.status);
      throw new BoardError('bad_response', `HTTP ${res.status} from GET ${path}`, res.status);
    }
    const len = Number(res.headers.get('content-length'));
    const type = (res.headers.get('content-type') ?? '').split(';')[0].trim();
    if (probe) { ctl.abort(); await res.body?.cancel().catch(() => {}); return { bytes: null, type, size: Number.isFinite(len) && len >= 0 ? len : null }; }
    const bytes = new Uint8Array(await res.arrayBuffer());
    return { bytes, type, size: bytes.byteLength };
  }
  return {
    participants: () => call<Participant[]>('GET', '/v1/participants'),
    /** Sign-in check: the new creds must read their own participant before they are stored. */
    whoami: (c: Creds) => call<Participant>('GET', `/v1/participants/${encodeURIComponent(c.participant)}`, undefined, c),
    sessions: () => call<Session[]>('GET', '/v1/sessions'),
    tickets: (q: Record<string, string> = {}) => call<Ticket[]>('GET', `/v1/tickets${Object.keys(q).length ? `?${new URLSearchParams(q)}` : ''}`),
    sendMessage: (m: MessageIn) => call<Message>('POST', '/v1/messages', m),
    // chat (C3, design-10b21760d9 §4.1)
    me: () => creds().then(c => (c ? call<Participant>('GET', `/v1/participants/${encodeURIComponent(c.participant)}`) : undefined)),
    ticket: (id: string) => call<Ticket>('GET', `/v1/tickets/${encodeURIComponent(id)}`),
    thread: (id: string, before?: number | null) =>
      call<ThreadPage>('GET', `/v1/tickets/${encodeURIComponent(id)}/thread${before ? `?before=${before}` : ''}`),
    message: (id: string) => call<MessageRow>('GET', `/v1/messages/${encodeURIComponent(id)}`),
    people: () => call<Reachable[]>('GET', '/v1/me/people'),
    send: (m: ChatSend) => call<MessageRow & { unresolved_mentions?: string[] }>('POST', '/v1/messages', m),
    // attachments (C12): the board sniffs the type and enforces the cap; a refusal is its own message
    upload: (ticketId: string, name: string, bytes: Uint8Array) => {
      const form = new FormData();
      form.append('file', new Blob([bytes as Uint8Array<ArrayBuffer>]), name);
      form.append('ticket_id', ticketId);
      return call<Staged>('POST', '/v1/artifacts/upload', form);
    },
    artifact: (id: string) => call<BoardArtifact>('GET', `/v1/artifacts/${encodeURIComponent(id)}`),
    content,
    // the Inbox (C15): what waits on the viewer, and the three writes that answer it
    decisions: () => call<DecisionsHome>('GET', '/v1/me/decisions'),
    verdict: (b: ReturnType<typeof verdictBody>) => call<{ criterion: unknown; message: string | null }>('POST', '/v1/me/verdict', b),
    gateAnswer: (g: InboxGate, answer: string) => call<unknown>('POST', gatePath(g), { answer }),
    doc: (id: string, version: number) =>
      call<BoardDoc>('GET', `/v1/docs/${encodeURIComponent(id)}?version=${version}`),
    // the Docs tab and the reader (C16): what a scope links, the doc's review context and its writes
    latestDoc: (id: string) => call<BoardDoc>('GET', `/v1/docs/${encodeURIComponent(id)}`),
    docsOf: (scope: string) => call<DocMeta[]>('GET', `/v1/docs?scope=${encodeURIComponent(scope)}`),
    links: (fromId: string) => call<{ to_id: string; relation: string }[]>('GET', `/v1/links?from_id=${encodeURIComponent(fromId)}`),
    criteria: (ticketId: string) => call<{ id: string; evidence_ref?: string | null }[]>('GET', `/v1/criteria?ticket_id=${encodeURIComponent(ticketId)}`),
    docContext: (id: string, source: string, version: number) =>
      call<DocContext>('GET', `/v1/docs/${encodeURIComponent(id)}/context?${new URLSearchParams({ source, version: String(version) })}`),
    decide: (b: ReturnType<typeof decideBody>) => call<{ decision: string; event_id?: string; message_id?: string }>('POST', '/v1/gates/decide', b),
    docResolve: (id: string, approve: boolean) =>
      call<{ doc: BoardDoc; target: BoardDoc | null }>('POST', `/v1/docs/${encodeURIComponent(id)}/${approve ? 'approve' : 'reject'}`),
    docDiff: (id: string) => call<{ base_id: string | null; base_version: number | null; diff: string }>('GET', `/v1/docs/${encodeURIComponent(id)}/diff`),
    docComments: (id: string, version: number) => call<unknown[]>('GET', `/v1/docs/${encodeURIComponent(id)}/comments?version=${version}`),
  };
}
