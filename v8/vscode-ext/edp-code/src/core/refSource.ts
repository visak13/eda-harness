// C24 (s-5d1b171d57): the $ picker's rows, read in the host from existing board routes (no server change):
// the open epic's tree (its tickets, its docs, its live decisions) first, then the board's open items (open epics
// + `/v1/find` hits). The scope is read once per epic and kept for a minute; a failed read is an empty list, never
// an error in the picker (a seat that may not read an epic's decisions still gets its tickets and docs).
import type { FindHit, Ticket } from './api';
import type { BoardDecisionList } from './decisions';
import { boardRows, rankRefs, scopeRows, type RefRow } from './boardRefs';

export type RefBoard = {
  ticket(id: string): Promise<Ticket>;
  tickets(q: Record<string, string>): Promise<Ticket[]>;
  docsOf(scope: string): Promise<{ id: string; title: string; doc_type?: string }[]>;
  scopeDecisions(scope: string): Promise<BoardDecisionList>;
  find(q: string, types: string, k?: number): Promise<FindHit[]>;
  epics(): Promise<{ id: string; title: string; status: string }[]>;
};

const TTL_MS = 60_000;
const none = <T>(p: Promise<T[]>): Promise<T[]> => p.catch(() => [] as T[]);

export class RefSource {
  private gen = 0;
  private scope = new Map<string, { at: number; rows: Promise<RefRow[]> }>();
  private epicRows: { at: number; rows: Promise<RefRow[]> } | null = null;

  constructor(private board: () => RefBoard, private now: () => number = Date.now) {}

  /** Forget what was read (sign-in, sign-out, board change). */
  clear(): void { ++this.gen; this.scope.clear(); this.epicRows = null; }

  private scopeRows(epic: string): Promise<RefRow[]> {
    const hit = this.scope.get(epic);
    if (hit && this.now() - hit.at < TTL_MS) return hit.rows;
    const rows = Promise.all([
      this.board().ticket(epic).then(t => [t], () => [] as Ticket[]),
      none(this.board().tickets({ epic_id: epic })),
      none(this.board().docsOf(epic)),
      this.board().scopeDecisions(epic).then(l => (Array.isArray(l?.decisions) ? l.decisions : []), () => []),
    ]).then(([self, tickets, docs, decisions]) =>
      scopeRows([...self, ...tickets.filter(t => t.id !== epic)], docs, decisions));
    this.scope.set(epic, { at: this.now(), rows });
    return rows;
  }

  private openEpics(): Promise<RefRow[]> {
    if (this.epicRows && this.now() - this.epicRows.at < TTL_MS) return this.epicRows.rows;
    const rows = none(this.board().epics()).then(e => boardRows([], e));
    this.epicRows = { at: this.now(), rows };
    return rows;
  }

  /** The ranked rows for `q` with `epic` (the open scope's epic, or null) first. */
  async rows(epic: string | null, q: string): Promise<RefRow[]> {
    const gen = this.gen;
    const [scope, epics, hits] = await Promise.all([
      epic ? this.scopeRows(epic) : Promise.resolve([] as RefRow[]),
      this.openEpics(),
      q.length >= 2 ? none(this.board().find(q, 'ticket,doc,decision')) : Promise.resolve([] as FindHit[]),
    ]);
    if (gen !== this.gen) return [];
    return rankRefs(q, scope, [...epics, ...boardRows(hits)]);
  }
}
