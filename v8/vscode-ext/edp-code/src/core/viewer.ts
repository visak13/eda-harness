import { boardClient, BoardError, type Board, type Creds } from './api';

/** A board handle belongs to one viewer generation, including delayed bodies and chained writes. */
export class ViewerRequests {
  private controller = new AbortController();
  private blocked = false;
  constructor(private onAuth: () => void, private fetcher: typeof fetch = fetch) {}
  invalidate(): void { this.controller.abort(); this.controller = new AbortController(); this.blocked = true; }
  resume(): void { this.controller.abort(); this.controller = new AbortController(); this.blocked = false; }
  board(url: string, creds: () => Promise<Creds | undefined>, log: (line: string) => void): Board {
    const signal = this.controller.signal;
    const current = () => { if (signal.aborted || this.blocked) throw new BoardError('viewer_changed', 'The board viewer changed.', 0); };
    const scoped: typeof fetch = async (input, init) => {
      current();
      const res = await this.fetcher(input, { ...init, signal: AbortSignal.any([signal, ...(init?.signal ? [init.signal] : [])]) });
      current();
      if (res.status === 401 || res.status === 403) {
        this.onAuth();
        throw new BoardError('viewer_changed', 'Sign in to the board again.', 0);
      }
      return res;
    };
    const b = boardClient(url, creds, scoped, log);
    return new Proxy(b, { get: (target, key: keyof Board) => {
      // A candidate sign-in is checked independently of the current viewer.
      if (key === 'whoami') return boardClient(url, creds, this.fetcher, log).whoami;
      const fn = target[key] as (...args: unknown[]) => Promise<unknown>;
      return async (...args: unknown[]) => { current(); try { return await fn(...args); } finally { current(); } };
    } });
  }
}
