// Who is live, and what they are on (strategyll-ab18531441 §4, architect ruling m-fbc05fb321 option a).
// The count rule lives ONLY in liveSeats, so a later per-repo session field is a one-line swap.
import type { Participant, Session, Ticket } from './api';
import { normDrive, samePath } from './anchor';

export type Seat = { participant_id: string; handle: string; role: string; ticket_id: string | null; stale: boolean };

/** Every alive agent session on this board, humans excluded, one row per participant (their newest
 *  alive session). A session whose presence was not refreshed is still counted, marked stale. */
export function liveSeats(sessions: Session[], participants: Participant[]): Seat[] {
  const byId = new Map(participants.map(p => [p.id, p]));
  const newest = new Map<string, Session>();
  for (const s of sessions) {
    if (s.state !== 'alive') continue;
    const p = byId.get(s.participant_id);
    if (p?.type === 'human') continue;
    const cur = newest.get(s.participant_id);
    if (!cur || (s.created_at ?? '') > (cur.created_at ?? '')) newest.set(s.participant_id, s);
  }
  return [...newest.values()]
    .map(s => {
      const p = byId.get(s.participant_id);
      return { participant_id: s.participant_id, handle: p?.handle ?? s.participant_id, role: p?.role ?? 'agent',
        ticket_id: s.ticket_id, stale: !!s.presence_stale_since };
    })
    .sort((a, b) => a.handle.localeCompare(b.handle));
}

/** The person picker: humans (marked) first, then live agent seats. Dead/idle agents are not offered. */
export function people(participants: Participant[], seats: Seat[]): Array<Participant & { live: boolean }> {
  const live = new Set(seats.map(s => s.participant_id));
  const humans = participants.filter(p => p.type === 'human').map(p => ({ ...p, live: false }));
  const agents = participants.filter(p => p.type === 'agent' && live.has(p.id)).map(p => ({ ...p, live: true }));
  const by = (a: Participant, b: Participant) => a.handle.localeCompare(b.handle);
  return [...humans.sort(by), ...agents.sort(by)];
}

const CLOSED = new Set(['done', 'dropped', 'partial']);
export const isOpen = (t: Ticket) => !CLOSED.has(t.status);

/** The ticket picker: the person's open tickets first, then every other open ticket. For an agent
 *  seat, the ticket its live session is on counts as theirs too. */
export function ticketChoices(all: Ticket[], personId: string, seats: Seat[] = []): { theirs: Ticket[]; others: Ticket[] } {
  const open = all.filter(isOpen);
  const seatTickets = new Set(seats.filter(s => s.participant_id === personId && s.ticket_id).map(s => s.ticket_id));
  const mine = (t: Ticket) => t.assignee === personId || seatTickets.has(t.id);
  const recent = (a: Ticket, b: Ticket) => b.id.localeCompare(a.id);
  return { theirs: open.filter(mine).sort(recent), others: open.filter(t => !mine(t)).sort(recent) };
}

/** Is `folder` one of the shared-tree paths? */
export function inSharedTree(folder: string, sharedTreePaths: string[]): boolean {
  return sharedTreePaths.some(p => samePath(normDrive(p), normDrive(folder)));
}

/** The default shared tree when `edp.sharedTreePaths` is empty: the v8 root the service was started
 *  for. The code service keeps its user-data under `<v8>/.data/code/user` (S2), and the extension's
 *  global storage lives inside it, so the v8 root is the prefix before `.data/code/`. */
export function defaultSharedTree(globalStoragePath: string): string | undefined {
  const m = /^(.*?)[\\/]\.data[\\/]code[\\/]/i.exec(globalStoragePath);
  return m ? normDrive(m[1]) : undefined;
}

/** The branch label: the name, `(detached) sha7` on a detached HEAD, `(no commits)` on an unborn one. */
export function branchLabel(head: { name?: string; commit?: string } | undefined): string {
  if (head?.name) return head.name;
  if (head?.commit) return `(detached) ${head.commit.slice(0, 7)}`;
  return '(no commits)';
}

export type BadgeView = { text: string; tooltip: string; warn: boolean };

/** The status-bar badge. A failed board call shows `seats ?` with the reason: never a stale count
 *  shown as current, and never silence (which would read as "0 seats"). */
export function badgeView(branch: string, r: { seats: Seat[] } | { error: string }): BadgeView {
  if ('error' in r) return { text: `$(git-branch) ${branch} · seats ?`, tooltip: `EDP: live seats unknown (${r.error})`, warn: false };
  const n = r.seats.length;
  const tooltip = n
    ? `${n} live agent seat${n === 1 ? '' : 's'} on this board:\n${r.seats.map(s => `${s.handle} — ${s.ticket_id ?? 'no ticket'}${s.stale ? ' (presence not refreshed)' : ''}`).join('\n')}`
    : 'No live agent seats on this board';
  return { text: `$(git-branch) ${branch} · ${n} seats live`, tooltip, warn: n > 0 };
}
