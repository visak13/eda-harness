import { describe, expect, it } from 'vitest';
import type { Participant, Session, Ticket } from '../src/core/api';
import { badgeView, branchLabel, defaultSharedTree, inSharedTree, liveSeats, people, ticketChoices } from '../src/core/seats';

const P: Participant[] = [
  { id: 'owner', type: 'human', role: 'owner', handle: 'owner' },
  { id: 'engineer.s-1', type: 'agent', role: 'engineer', handle: 'engineer.s-1' },
  { id: 'architect.e-1', type: 'agent', role: 'architect', handle: 'architect.e-1' },
  { id: 'qa.e-1', type: 'agent', role: 'qa', handle: 'qa.e-1' },
];
const S = (id: string, participant_id: string, state: Session['state'], extra: Partial<Session> = {}): Session =>
  ({ id, participant_id, ticket_id: `t-${participant_id}`, state, created_at: `2026-09-25T0${id.length}:00:00Z`, ...extra });

describe('liveSeats (m-fbc05fb321 option a)', () => {
  it('counts alive sessions, not closed/dead/parked/stalled ones', () => {
    const seats = liveSeats([S('a', 'engineer.s-1', 'alive'), S('b', 'architect.e-1', 'dead'), S('c', 'qa.e-1', 'parked'), S('d', 'qa.e-1', 'stalled')], P);
    expect(seats.map(s => s.participant_id)).toEqual(['engineer.s-1']);
  });
  it('excludes humans even with an alive session', () => {
    expect(liveSeats([S('a', 'owner', 'alive')], P)).toEqual([]);
  });
  it('one row per participant, from the newest alive session', () => {
    const seats = liveSeats([S('a', 'engineer.s-1', 'alive', { ticket_id: 'old', created_at: '2026-09-24T00:00:00Z' }),
      S('b', 'engineer.s-1', 'alive', { ticket_id: 'new', created_at: '2026-09-25T00:00:00Z' })], P);
    expect(seats).toHaveLength(1);
    expect(seats[0].ticket_id).toBe('new');
  });
  it('stale presence is still counted and shown as stale', () => {
    const seats = liveSeats([S('a', 'engineer.s-1', 'alive', { presence_stale_since: '2026-09-25T01:00:00Z' })], P);
    expect(seats[0].stale).toBe(true);
    expect(badgeView('main', { seats }).tooltip).toContain('presence not refreshed');
  });
  it('an unknown participant (no row) still counts as an agent seat', () => {
    expect(liveSeats([S('a', 'ghost', 'alive')], P)[0]).toMatchObject({ handle: 'ghost', role: 'agent' });
  });
});

describe('badgeView', () => {
  const seats = liveSeats([S('a', 'engineer.s-1', 'alive'), S('b', 'architect.e-1', 'alive')], P);
  it('`⎇ branch · N seats live` with a warning background while seats are live', () =>
    expect(badgeView('main', { seats })).toMatchObject({ text: '$(git-branch) main · 2 seats live', warn: true }));
  it('zero seats: no warning', () => expect(badgeView('main', { seats: [] })).toMatchObject({ text: '$(git-branch) main · 0 seats live', warn: false }));
  it('a board error shows `seats ?` with the reason, never a count', () => {
    const v = badgeView('main', { error: 'board unreachable at http://127.0.0.1:9400' });
    expect(v.text).toBe('$(git-branch) main · seats ?');
    expect(v.tooltip).toContain('board unreachable');
  });
  it('tooltip lists seat and ticket', () => expect(badgeView('main', { seats }).tooltip).toContain('engineer.s-1 — t-engineer.s-1'));
  it('branch label: name, detached sha7, unborn', () => {
    expect(branchLabel({ name: 'main', commit: 'abc' })).toBe('main');
    expect(branchLabel({ commit: '0123456789abcdef' })).toBe('(detached) 0123456');
    expect(branchLabel(undefined)).toBe('(no commits)');
  });
});

describe('shared tree', () => {
  it('matches case-insensitively with normalised drives', () =>
    expect(inSharedTree('c:\\Projects\\Learning\\eda-base3\\v8', ['C:\\projects\\learning\\eda-base3\\v8\\'])).toBe(true));
  it('a repo nested below the shared tree is not it', () => expect(inSharedTree('C:\\v8\\web', ['C:\\v8'])).toBe(false));
  it('the repo that contains the shared tree is it (v8 inside the eda-base3 repo)', () =>
    expect(inSharedTree('c:\\Projects\\Learning\\eda-base3', ['C:\\Projects\\Learning\\eda-base3\\v8'])).toBe(true));
  it('an unrelated or sibling repo is not it', () => {
    expect(inSharedTree('C:\\Projects\\other', ['C:\\Projects\\Learning\\eda-base3\\v8'])).toBe(false);
    expect(inSharedTree('C:\\Projects\\Learning\\eda-base', ['C:\\Projects\\Learning\\eda-base3\\v8'])).toBe(false);
  });
  it('default = the v8 root the service keeps its user-data under', () =>
    expect(defaultSharedTree('c:\\Projects\\Learning\\eda-base3\\v8\\.data\\code\\user\\User\\globalStorage\\edp.edp-code')).toBe('C:\\Projects\\Learning\\eda-base3\\v8'));
  it('no default outside the code service (e2e temp dirs)', () => expect(defaultSharedTree('C:\\Temp\\ud\\User\\globalStorage\\edp.edp-code')).toBeUndefined());
});

describe('pickers', () => {
  const seats = liveSeats([S('a', 'engineer.s-1', 'alive', { ticket_id: 's-9' })], P);
  it('people: humans first (marked), then live agent seats only', () => {
    const ps = people(P, seats);
    expect(ps.map(p => [p.id, p.live])).toEqual([['owner', false], ['engineer.s-1', true]]);
  });
  const T = (id: string, status: string, assignee: string | null = null): Ticket => ({ id, kind: 'story', title: id, status, assignee });
  it("tickets: the person's open tickets first, then any open ticket; closed ones never", () => {
    const all = [T('s-1', 'in_progress', 'owner'), T('s-2', 'done', 'owner'), T('s-3', 'ready'), T('s-4', 'dropped'), T('s-5', 'partial')];
    const r = ticketChoices(all, 'owner');
    expect(r.theirs.map(t => t.id)).toEqual(['s-1']);
    expect(r.others.map(t => t.id)).toEqual(['s-3']);
  });
  it("a seat's live session ticket counts as theirs", () => {
    const r = ticketChoices([T('s-9', 'in_progress', 'someone-else'), T('s-8', 'ready')], 'engineer.s-1', seats);
    expect(r.theirs.map(t => t.id)).toEqual(['s-9']);
  });
});
