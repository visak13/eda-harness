// Commit history for change cards (design-10b21760d9 §4.2; strategyll-86c5b5068f §3). Pure: the host
// runs git (execFile, no shell) with LOG_ARGS and hands the raw bytes here. Trailers are parsed by git
// (`%(trailers:…)`, interpret-trailers rules: last paragraph only); this file only splits on the
// \x1e / \x1f / \x1d / \0 separators. Attribution is trailer > subject id > none (dec-16b44ab99c).
import { TICKET_ID, type CommitCard } from './chatProtocol';

export const LOG_FORMAT =
  '%x1e%H%x1f%P%x1f%at%x1f%s%x1f%(trailers:key=EDP-Ticket,valueonly,separator=%x1d)%x1f%(trailers:key=EDP-Seat,valueonly,separator=%x1d)%x1f';

export type CommitWindow = { count: number; days: number };
export const DEFAULT_WINDOW: CommitWindow = { count: 500, days: 30 };

/** The bounded window, clamped (a setting can hold anything). */
export function commitWindow(raw: unknown): CommitWindow {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const n = (v: unknown, d: number, max: number) => (typeof v === 'number' && Number.isFinite(v) && v >= 1 ? Math.min(Math.floor(v), max) : d);
  return { count: n(r.count, DEFAULT_WINDOW.count, 5000), days: n(r.days, DEFAULT_WINDOW.days, 3650) };
}

/** `git log` argv: `range` is `<old>..HEAD` for an incremental read, else HEAD over the window. */
export function logArgs(w: CommitWindow, range?: string): string[] {
  if (range !== undefined && !/^[0-9a-f]{40}(\.\.HEAD)?$/.test(range)) throw new Error('bad log range');
  return ['-c', 'core.quotepath=false', 'log', '-z', '--no-color', '--raw', '--numstat', '-M', '--diff-merges=first-parent',
    `--format=${LOG_FORMAT}`, '-n', String(w.count), `--since=${w.days}.days`, range ?? 'HEAD', '--'];
}

export type FileStatus = 'A' | 'M' | 'D' | 'R' | 'C' | 'T' | 'U' | 'X';
export type FileChange = {
  /** repo-relative, `/`-separated (git's own spelling) */
  path: string;
  /** the left-side path of a rename/copy */
  oldPath?: string;
  status: FileStatus;
  /** null = binary (numstat `-`) */
  add: number | null;
  del: number | null;
};

export type Commit = {
  sha: string; parents: string[];
  /** author time, ms since the epoch */
  at: number;
  subject: string;
  trailerTickets: string[]; trailerSeats: string[];
  files: FileChange[];
};

const NUMSTAT = /^(\d+|-)\t(\d+|-)\t([\s\S]*)$/;
const RAW = /^:\d{6} \d{6} [0-9a-f]+ [0-9a-f]+ ([A-Z])\d*$/;
const num = (s: string) => (s === '-' ? null : Number(s));
const vals = (s: string) => s.split('\x1d').map(x => x.trim()).filter(Boolean);

/** Parse `git log -z --raw --numstat --format=LOG_FORMAT` output. Unparseable records are skipped. */
export function parseLog(out: string): Commit[] {
  const commits: Commit[] = [];
  for (const rec of out.split('\x1e')) {
    if (!rec) continue;
    const f = rec.split('\x1f');
    if (f.length < 7) continue;
    const [sha, parents, at, subject, tickets, seats] = f;
    if (!/^[0-9a-f]{40,64}$/.test(sha)) continue;
    const rest = f.slice(6).join('\x1f');
    const files = new Map<string, FileChange>();
    const order: string[] = [];
    const toks = rest.split('\0');
    for (let i = 0; i < toks.length; i++) {
      // the diff block starts after the message's NUL with a newline: `\0\n:100644 …`
      const t = toks[i].startsWith('\n') ? toks[i].slice(1) : toks[i];
      if (!t) continue;
      const raw = RAW.exec(t);
      if (raw) {
        const status = raw[1] as FileStatus;
        let path: string, oldPath: string | undefined;
        if (status === 'R' || status === 'C') { oldPath = toks[++i]; path = toks[++i]; }
        else path = toks[++i];
        if (path === undefined) break;
        if (!files.has(path)) order.push(path);
        files.set(path, { path, ...(oldPath !== undefined ? { oldPath } : {}), status, add: null, del: null });
        continue;
      }
      const ns = NUMSTAT.exec(t);
      if (ns) {
        // a rename's numstat is `add\tdel\t\0old\0new`
        const path = ns[3] === '' ? (i += 2, toks[i]) : ns[3];
        const fc = path !== undefined ? files.get(path) : undefined;
        if (fc) { fc.add = num(ns[1]); fc.del = num(ns[2]); }
      }
    }
    commits.push({
      sha, parents: parents ? parents.split(' ').filter(Boolean) : [], at: Number(at) * 1000, subject,
      trailerTickets: vals(tickets), trailerSeats: vals(seats), files: order.map(p => files.get(p)!),
    });
  }
  return commits;
}

export type Attribution = 'trailer' | 'subject' | 'none';
export type Attributed = { tickets: string[]; attribution: Attribution; trailerSeat: string | null };

/** The fallback: ticket ids in the SUBJECT only (bodies cite other tickets; plan note-75098fdfa3). */
export const SUBJECT_ID = /\b(?:epic|s|t)-[0-9a-f]{10}\b/g;

/** trailer (valid EDP-Ticket values) > subject ids > none. A malformed trailer value falls through. */
export function attribute(c: Pick<Commit, 'subject' | 'trailerTickets' | 'trailerSeats'>): Attributed {
  const fromTrailer = [...new Set(c.trailerTickets.filter(t => TICKET_ID.test(t)))];
  if (fromTrailer.length) return { tickets: fromTrailer, attribution: 'trailer', trailerSeat: c.trailerSeats[0] ?? null };
  const fromSubject = [...new Set(c.subject.match(SUBJECT_ID) ?? [])];
  if (fromSubject.length) return { tickets: fromSubject, attribution: 'subject', trailerSeat: null };
  return { tickets: [], attribution: 'none', trailerSeat: null };
}

export type Indexed = Commit & Attributed;
export const index = (cs: Commit[]): Indexed[] => cs.map(c => ({ ...c, ...attribute(c) }));

/** Commits naming any of `ids` (a story thread passes the story + its tasks; an epic thread the epic). */
export const naming = (cs: Indexed[], ids: ReadonlySet<string>) => cs.filter(c => c.tickets.some(t => ids.has(t)));
export const unlinked = (cs: Indexed[]) => cs.filter(c => c.attribution === 'none');

/** Per story: the number of commits naming the story or one of its tasks (each commit counted once). */
export function storyCounts(cs: Indexed[], storyIds: string[], tasksOf: ReadonlyMap<string, string[]>): Map<string, number> {
  const out = new Map<string, number>();
  for (const s of storyIds) out.set(s, naming(cs, new Set([s, ...(tasksOf.get(s) ?? [])])).length);
  return out;
}

/** Merge an incremental read into the index: newest first, deduped by sha, bounded by `count`. */
export function mergeNewer(newer: Indexed[], older: Indexed[], count: number): Indexed[] {
  const seen = new Set<string>();
  const out: Indexed[] = [];
  for (const c of [...newer, ...older]) { if (!seen.has(c.sha)) { seen.add(c.sha); out.push(c); } }
  return out.slice(0, count);
}

/** Files listed on a card; the multi-diff still opens every file. */
export const CARD_FILES = 100;

/** A timeline card. The seat is the EDP-Seat trailer, else (subject attribution) the assignee of the
 *  first named ticket, labelled so; `none` names no seat. */
export function cardOf(c: Indexed, assignee: (ticket: string) => string | null | undefined, local = true): CommitCard {
  let seat: string | null = null, seatVia: CommitCard['seatVia'] = null;
  if (c.attribution === 'trailer' && c.trailerSeat) { seat = c.trailerSeat; seatVia = 'trailer'; }
  else if (c.attribution !== 'none') {
    const a = c.tickets.map(t => assignee(t)).find(Boolean);
    if (a) { seat = a; seatVia = 'assignee'; }
  }
  return {
    type: 'commit', sha: c.sha, at: new Date(c.at).toISOString(), subject: c.subject, tickets: c.tickets,
    attribution: c.attribution, seat, seatVia, local,
    files: c.files.slice(0, CARD_FILES).map(f => ({ path: f.path, ...(f.oldPath !== undefined ? { oldPath: f.oldPath } : {}), status: f.status, add: f.add, del: f.del })),
    more: Math.max(0, c.files.length - CARD_FILES),
  };
}
