// The @-list (strategyll-5e3ecdb625 §2; owner ask m-686626bbd3: "when I tag in chat I dont know which
// architect is linked to which ticket"). Rows are labelled here, in the host, from GET /v1/me/people
// + ticket titles, and posted to the view as plain data. Pure.
import type { PersonRow } from './chatProtocol';

/** A GET /v1/me/people row (views._roster). */
export type Reachable = {
  id: string; handle: string; type: 'human' | 'agent'; role: string;
  seat_ticket: string | null; seat_state: string | null;
};

export type OpenThread = { ticket: string | null; epic: string | null; stories: string[] };

/** 0 = seat on the open ticket, 1 = seat on the open epic or one of its stories, 2 = human, 3 = other seat. */
export function rankOf(p: Reachable, open: OpenThread): number {
  if (p.type === 'human') return 2;
  const t = p.seat_ticket;
  if (t && t === open.ticket) return 0;
  if (t && (t === open.epic || open.stories.includes(t))) return 1;
  return 3;
}

export function personRows(people: Reachable[], titles: ReadonlyMap<string, string>, open: OpenThread): PersonRow[] {
  return people.map(p => {
    const title = p.seat_ticket ? titles.get(p.seat_ticket) ?? null : null;
    const detail = p.type === 'human' ? 'human'
      : [p.role, p.seat_ticket ?? 'no ticket', title ?? '', p.seat_state === 'parked' ? '(parked)' : ''].filter(Boolean).join(' · ');
    return { id: p.id, handle: p.handle, type: p.type, role: p.role, seat_ticket: p.seat_ticket, seat_title: title,
      seat_state: p.seat_state, rank: rankOf(p, open), detail };
  }).sort(byRank);
}

function byRank(a: PersonRow, b: PersonRow): number {
  return a.rank - b.rank || (a.handle < b.handle ? -1 : a.handle > b.handle ? 1 : 0);
}

/** Matches a case-insensitive prefix on handle or a substring on role (strategyll-86c5b5068f §1);
 *  sorted by rank (the open ticket's seats first), then handle-prefix before role matches.
 *  `@architect` therefore lists every architect with its ticket, this epic's first. An empty query
 *  lists everyone in rank order. */
export function filterPeople(rows: PersonRow[], query: string, limit = 50): PersonRow[] {
  const q = query.toLowerCase();
  if (!q) return rows.slice().sort(byRank).slice(0, limit);
  const scored: [number, PersonRow][] = [];
  for (const r of rows) {
    const h = r.handle.toLowerCase();
    const cls = h.startsWith(q) ? 0 : r.role.toLowerCase().includes(q) ? 1 : -1;
    if (cls >= 0) scored.push([cls, r]);
  }
  return scored.sort((a, b) => a[1].rank - b[1].rank || a[0] - b[0] || byRank(a[1], b[1])).map(x => x[1]).slice(0, limit);
}

/** The open epic's architect handle: the live architect seat whose ticket is the epic. */
export function epicArchitect(people: Reachable[], epicId: string | null): string | null {
  if (!epicId) return null;
  const hit = people.find(p => p.type === 'agent' && p.role === 'architect' && p.seat_ticket === epicId);
  return hit?.handle ?? null;
}

/** The option's accessible name: the same disambiguation a sighted user reads. */
export const accessibleName = (r: PersonRow) => `${r.handle}, ${r.detail}`;
