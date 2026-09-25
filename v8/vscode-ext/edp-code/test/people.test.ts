import { describe, expect, it } from 'vitest';
import { accessibleName, epicArchitect, filterPeople, personRows, type Reachable } from '../src/core/people';

const P: Reachable[] = [
  { id: 'owner', handle: 'owner', type: 'human', role: 'owner', seat_ticket: null, seat_state: null },
  { id: 'ravi', handle: 'ravi', type: 'human', role: 'owner', seat_ticket: null, seat_state: null },
  { id: 'architect.epic-91fcd3b370', handle: 'architect.epic-91fcd3b370', type: 'agent', role: 'architect', seat_ticket: 'epic-91fcd3b370', seat_state: 'alive' },
  { id: 'architect.epic-52edacd059', handle: 'architect.epic-52edacd059', type: 'agent', role: 'architect', seat_ticket: 'epic-52edacd059', seat_state: 'alive' },
  { id: 'engineer.s-ab8e69650e', handle: 'engineer.s-ab8e69650e', type: 'agent', role: 'engineer', seat_ticket: 's-ab8e69650e', seat_state: 'parked' },
  { id: 'engineer.s-b00dbbcdea', handle: 'engineer.s-b00dbbcdea', type: 'agent', role: 'engineer', seat_ticket: 's-b00dbbcdea', seat_state: 'alive' },
  { id: 'engineer.s-4741ac0557', handle: 'engineer.s-4741ac0557', type: 'agent', role: 'engineer', seat_ticket: 's-4741ac0557', seat_state: 'alive' },
];
const titles = new Map([['epic-52edacd059', 'EDP chat in VS Code'], ['epic-91fcd3b370', 'Code tab'], ['s-b00dbbcdea', 'C3 Chat panel'],
  ['s-ab8e69650e', 'C5 Change cards'], ['s-4741ac0557', 'S5 extension']]);
const open = { ticket: 's-b00dbbcdea', epic: 'epic-52edacd059', stories: ['s-b00dbbcdea', 's-ab8e69650e'] };

describe('personRows', () => {
  const rows = personRows(P, titles, open);

  it('every agent row shows role · ticket id · ticket title; humans are marked human', () => {
    const a = rows.find(r => r.id === 'architect.epic-52edacd059')!;
    expect(a.detail).toBe('architect · epic-52edacd059 · EDP chat in VS Code');
    expect(rows.find(r => r.id === 'engineer.s-ab8e69650e')!.detail).toBe('engineer · s-ab8e69650e · C5 Change cards · (parked)');
    expect(rows.find(r => r.id === 'owner')!.detail).toBe('human');
    expect(accessibleName(a)).toBe('architect.epic-52edacd059, architect · epic-52edacd059 · EDP chat in VS Code');
  });

  it('ranks the open ticket\'s seat first, then the epic and its stories, then humans, then other seats', () => {
    expect(rows.map(r => r.id)).toEqual([
      'engineer.s-b00dbbcdea',
      'architect.epic-52edacd059', 'engineer.s-ab8e69650e',
      'owner', 'ravi',
      'architect.epic-91fcd3b370', 'engineer.s-4741ac0557',
    ]);
  });

  it('"@architect" lists the architects with their epics, this epic\'s first', () => {
    const hits = filterPeople(rows, 'architect');
    expect(hits.map(r => r.id)).toEqual(['architect.epic-52edacd059', 'architect.epic-91fcd3b370']);
    expect(hits[1].detail).toBe('architect · epic-91fcd3b370 · Code tab');
  });

  it('"@engineer" lists engineer seats, the open ticket\'s and this epic\'s first', () => {
    expect(filterPeople(rows, 'engineer').map(r => r.id)).toEqual(['engineer.s-b00dbbcdea', 'engineer.s-ab8e69650e', 'engineer.s-4741ac0557']);
  });

  it('prefix on handle, case-insensitive; an empty query is everyone in rank order', () => {
    expect(filterPeople(rows, 'RAV').map(r => r.id)).toEqual(['ravi']);
    expect(filterPeople(rows, 'OW').map(r => r.id)).toEqual(['owner', 'ravi']); // ravi by role
    expect(filterPeople(rows, '').length).toBe(P.length);
  });
});

describe('epicArchitect', () => {
  it('is the live architect seat whose ticket is the epic', () => {
    expect(epicArchitect(P, 'epic-52edacd059')).toBe('architect.epic-52edacd059');
    expect(epicArchitect(P, 'epic-0000000000')).toBeNull();
    expect(epicArchitect(P, null)).toBeNull();
  });
});
