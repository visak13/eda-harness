// @vitest-environment jsdom
// C15 Inbox tab (s-e14d316891): the scope filter over GET /v1/me/decisions, the three write bodies, the
// protocol gate for the Inbox intents, the edp-doc URI, the per-row drafts, and the view (rows, controls,
// refusals, the send chord).
import { describe, expect, it } from 'vitest';
import type { ChatState } from '../src/core/chatProtocol';
import { parseInbound, refusedInbox } from '../src/core/chatProtocol';
import { docPath, parseDocPath } from '../src/core/docUri';
import {
  answerBody, gateKey, gatePath, inboxBadge, questionKey, scopeInbox, signoffKey, verdictBody, writeProblem,
  type DecisionsHome, type InboxGate, type InboxQuestion, type InboxSignoff, type InboxState,
} from '../src/core/inbox';
import { INBOX_DRAFTS_MAX, restoreLocal } from '../src/core/viewState';
import type { TabCtx } from '../webview/tabs';
import { inboxDone, inboxTab, renderInbox } from '../webview/views/inbox';

const EPIC = 'epic-0123456789', STORY = 's-0123456789', TASK = 't-0123456789', OTHER_STORY = 's-abcdefabcd', OTHER_EPIC = 'epic-abcdefabcd';
const M1 = 'm-1111111111', M2 = 'm-2222222222', M3 = 'm-3333333333', C1 = 'c-1111111111', C2 = 'c-2222222222';
const DOC = 'report-aaaaaaaaaa';

const home: DecisionsHome = {
  signoffs: [
    { criterion: { id: C1, text: 'the report says it works', evidence_ref: DOC, evidence_version: null },
      ticket: { id: STORY, title: 'Story one', assignee: 'engineer.s-0123456789' }, doc: { id: DOC, title: 'C1 report', doc_type: 'report', version: 3 }, excerpt: '# r' },
    { criterion: { id: C2, text: 'other epic', evidence_ref: DOC }, ticket: { id: 's-9999999999', title: 'x', assignee: null }, doc: null },
  ],
  gates: [
    { ticket_id: EPIC, gate: 'scope', by: 'architect.epic-0123456789', note: 'raise the cap to 9', opened_at: '2026-09-25T10:00:00Z', epic: EPIC },
    { ticket_id: EPIC, gate: 'design_signoff', by: 'architect.epic-0123456789', note: 'v12 ready', epic: EPIC },
    { ticket_id: OTHER_EPIC, gate: 'acceptance', by: 'qa', epic: OTHER_EPIC },
  ],
  questions: [
    { id: M1, ticket_id: TASK, created_by: 'engineer.t-0123456789', kind: 'question', text: 'which **one**?', why: 'addressed to you (@owner)',
      asker: { type: 'agent', role: 'engineer', seat_state: 'alive', note: 'Its shell is alive; your answer wakes it.' } },
    { id: M2, ticket_id: OTHER_STORY, created_by: 'x', kind: 'question', text: 'not in this story' },
    { id: M3, ticket_id: STORY, created_by: 'y', kind: 'question', text: 'asker closed', asker: { seat_state: 'dead' } },
  ],
};
const storyScope = new Set([STORY, TASK]);
const epicScope = new Set([EPIC, STORY, TASK, OTHER_STORY]);

describe('scopeInbox: only the picked scope, owner m-db09472a68', () => {
  it('a story: its sign-offs and its tasks\' questions; no epic gate, no other story, no closed asker', () => {
    const items = scopeInbox(home, storyScope, new Map([[TASK, 'The task']]));
    expect(items.map(i => i.key)).toEqual([signoffKey(C1), questionKey(M1)]);
    const s = items[0] as InboxSignoff;
    expect(s).toMatchObject({ ticketId: STORY, ticketTitle: 'Story one', version: 3, evidence: { ref: DOC, doc: true, title: 'C1 report', docType: 'report' }, assignee: 'engineer.s-0123456789' });
    const q = items[1] as InboxQuestion;
    expect(q).toMatchObject({ id: M1, ticketTitle: 'The task', by: 'engineer.t-0123456789', byRole: 'engineer', byHuman: false, why: 'addressed to you (@owner)' });
  });
  it('the epic: every ticket of it, sign-offs then gates then questions; another epic\'s gate stays out', () => {
    const items = scopeInbox(home, epicScope);
    expect(items.map(i => i.key)).toEqual([signoffKey(C1), gateKey(EPIC, 'scope'), gateKey(EPIC, 'design_signoff'), questionKey(M1), questionKey(M2)]);
    expect((items[1] as InboxGate).design).toBe(false);
    expect((items[2] as InboxGate).design).toBe(true);
  });
  it('switching scope changes the list; nothing, or garbage, is an empty list', () => {
    expect(scopeInbox(home, new Set([OTHER_STORY])).map(i => i.key)).toEqual([questionKey(M2)]);
    expect(scopeInbox(null, epicScope)).toEqual([]);
    expect(scopeInbox({ signoffs: [null as never], questions: [{ id: 'nope' } as never], gates: [{ ticket_id: EPIC } as never] }, epicScope)).toEqual([]);
  });
  it('evidence that is not a doc keeps the criterion\'s version (the board checks none), else 1', () => {
    const h: DecisionsHome = { signoffs: [
      { criterion: { id: C1, text: 't', evidence_ref: 'art-0123456789', evidence_version: 2 }, ticket: { id: STORY, title: 'S', assignee: null }, doc: null },
      { criterion: { id: C2, text: 't', evidence_ref: 'art-0123456789' }, ticket: { id: STORY, title: 'S', assignee: null }, doc: null },
    ] };
    const [a, b] = scopeInbox(h, storyScope) as InboxSignoff[];
    expect([a.version, a.evidence.doc, b.version]).toEqual([2, false, 1]);
  });
  it('the badge counts the rows', () => {
    const st: InboxState = { scope: STORY, items: scopeInbox(home, storyScope), loading: false, error: null };
    expect(inboxBadge(st)).toEqual({ text: '2', aria: '2 items waiting on you' });
    expect(inboxBadge({ ...st, items: [] })).toBeNull();
    expect(inboxBadge(null)).toBeNull();
  });
});

describe('the writes, built from the host\'s own row', () => {
  const [s, q] = scopeInbox(home, storyScope) as [InboxSignoff, InboxQuestion];
  const g = scopeInbox(home, epicScope).find(i => i.key === gateKey(EPIC, 'scope')) as InboxGate;
  it('a question: an answer to the asker, threaded (reply_to)', () => {
    expect(answerBody(q, 'the first')).toEqual({ ticket_id: TASK, to: 'engineer.t-0123456789', kind: 'answer', text: 'the first', reply_to: M1 });
  });
  it('a sign-off: the verdict for the version the row showed, the note, the ticket for the note', () => {
    expect(verdictBody(s, 'fail', 'redo §2')).toEqual({ criterion_id: C1, verdict: 'fail', note: 'redo §2', ticket_id: STORY, evidence_version: 3 });
  });
  it('a gate: its own route', () => {
    expect(gatePath(g)).toBe(`/v1/gates/${EPIC}/scope/answer`);
  });
  it('a Fail needs a note, an answer and a ruling need text; a Pass note is optional', () => {
    expect(writeProblem('verdict', '', 'fail')).toMatch(/Fail needs a note/);
    expect(writeProblem('verdict', '', 'pass')).toBeNull();
    expect(writeProblem('answer', '  ')).toMatch(/answer/);
    expect(writeProblem('gate', '')).toMatch(/ruling/);
    expect(writeProblem('gate', 'x'.repeat(16_385))).toMatch(/Too long/);
  });
});

describe('parseInbound: the Inbox intents', () => {
  const ok = (m: object) => parseInbound({ v: 1, ...m });
  it('accepts well-formed intents, copying known keys only', () => {
    expect(ok({ type: 'inboxAnswer', key: `q:${M1}`, text: 'yes', to: 'evil' })).toEqual({ v: 1, type: 'inboxAnswer', key: `q:${M1}`, text: 'yes' });
    expect(ok({ type: 'inboxGate', key: `g:${EPIC}:scope`, text: 'approved' })).toEqual({ v: 1, type: 'inboxGate', key: `g:${EPIC}:scope`, text: 'approved' });
    expect(ok({ type: 'inboxVerdict', key: `c:${C1}`, verdict: 'pass', note: '', version: 3 })).toEqual({ v: 1, type: 'inboxVerdict', key: `c:${C1}`, verdict: 'pass', note: '', version: 3 });
    expect(ok({ type: 'inboxOpen', key: `c:${C1}` })).toEqual({ v: 1, type: 'inboxOpen', key: `c:${C1}` });
    expect(ok({ type: 'inboxOpen', key: `g:${EPIC}:design_signoff` })).toEqual({ v: 1, type: 'inboxOpen', key: `g:${EPIC}:design_signoff` });
    expect(ok({ type: 'inboxRefresh' })).toEqual({ v: 1, type: 'inboxRefresh' });
  });
  it('refuses a key of the wrong kind, empty text, a Fail with no note, a bad version, a bad verdict', () => {
    expect(ok({ type: 'inboxAnswer', key: `g:${EPIC}:scope`, text: 'x' })).toBeNull();
    expect(ok({ type: 'inboxGate', key: `q:${M1}`, text: 'x' })).toBeNull();
    expect(ok({ type: 'inboxAnswer', key: `q:${M1}`, text: '  ' })).toBeNull();
    expect(ok({ type: 'inboxVerdict', key: `c:${C1}`, verdict: 'fail', note: ' ', version: 3 })).toBeNull();
    expect(ok({ type: 'inboxVerdict', key: `c:${C1}`, verdict: 'pass', version: 0 })).toBeNull();
    expect(ok({ type: 'inboxVerdict', key: `c:${C1}`, verdict: 'pass', version: 1.5 })).toBeNull();
    expect(ok({ type: 'inboxVerdict', key: `c:${C1}`, verdict: 'pending', version: 3 })).toBeNull();
    expect(ok({ type: 'inboxOpen', key: `q:${M1}` })).toBeNull();
    expect(ok({ type: 'inboxOpen', key: 'c:../../etc' })).toBeNull();
    expect(ok({ type: 'inboxGate', key: `g:${EPIC}:scope`, text: 'x'.repeat(16_385) })).toBeNull();
  });
  it('a refused write is answered by its key, so the row never stays busy', () => {
    expect(refusedInbox({ v: 1, type: 'inboxVerdict', key: `c:${C1}`, verdict: 'fail', note: '' })).toBe(`c:${C1}`);
    expect(refusedInbox({ v: 1, type: 'inboxAnswer', key: 'bogus' })).toBeUndefined();
    expect(refusedInbox({ v: 1, type: 'send', key: `q:${M1}` })).toBeUndefined();
  });
});

describe('edp-doc URIs carry the version (C16 reuses them)', () => {
  it('round-trips, refuses anything else', () => {
    expect(docPath(DOC, 3)).toBe(`/${DOC}/v3.md`);
    expect(parseDocPath(`/${DOC}/v3.md`)).toEqual({ id: DOC, version: 3 });
    expect(parseDocPath('/design-10b21760d9/v12.md')).toEqual({ id: 'design-10b21760d9', version: 12 });
    expect(parseDocPath(`/${DOC}/v0.md`)).toBeNull();
    expect(parseDocPath(`/../${DOC}/v3.md`)).toBeNull();
    expect(() => docPath('../x', 1)).toThrow();
  });
});

describe('drafts survive a reload, by row key', () => {
  it('keeps well-formed keys only', () => {
    const l = restoreLocal({ v: 1, inbox: { [`q:${M1}`]: 'half an answer', 'x:1': 'no', [`c:${C1}`]: 5 } });
    expect(l.inbox).toEqual({ [`q:${M1}`]: 'half an answer' });
    expect(restoreLocal(undefined).inbox).toEqual({});
  });
  it('over the cap, the most recently typed drafts stay (review fix: stale drafts no longer crowd out a new one)', () => {
    const inbox: Record<string, string> = {};
    for (let n = 0; n < INBOX_DRAFTS_MAX + 5; n++) inbox[`q:m-${String(n).padStart(10, '0')}`] = `d${n}`;
    const kept = Object.values(restoreLocal({ v: 1, inbox }).inbox);
    expect(kept).toHaveLength(INBOX_DRAFTS_MAX);
    expect(kept.at(-1)).toBe(`d${INBOX_DRAFTS_MAX + 4}`);
    expect(kept).not.toContain('d0');
  });
});

// -- the view -----------------------------------------------------------------------------------------------
function state(inbox: InboxState | null): ChatState {
  return {
    type: 'state', v: 1, me: null, ticket: { id: EPIC, kind: 'epic', title: 'E', status: 'in_progress' }, epic: { id: EPIC, kind: 'epic', title: 'E', status: 'in_progress' },
    stories: [], commits: [], unlinked: [], uncommitted: null, architect: null, people: [], items: [], hasOlder: false, chip: null, feed: 'live', notice: null, inbox,
  };
}
function mount(inbox: InboxState | null) {
  const posts: any[] = [];
  const s = state(inbox);
  const c: TabCtx = { state: s, local: restoreLocal(undefined), post: m => posts.push(m), persist: () => {}, select: () => {}, chatUnread: 0 };
  const panel = document.createElement('section');
  document.body.replaceChildren(panel);
  renderInbox(panel, c);
  return { panel, posts, c, s };
}
const full = (): InboxState => ({ scope: EPIC, items: scopeInbox(home, epicScope), loading: false, error: null });
const row = (p: HTMLElement, key: string) => p.querySelector<HTMLElement>(`.ib-row[data-key="${key}"]`)!;

describe('the Inbox tab', () => {
  it('is the fourth tab and badges the scope\'s rows', () => {
    const { c } = mount(full());
    expect(inboxTab.badge(c)).toEqual({ text: '5', aria: '5 items waiting on you' });
  });
  it('groups sign-offs, gates and questions; the design gate links out, no ruling box', () => {
    const { panel } = mount(full());
    expect([...panel.querySelectorAll('.ib-group')].map(g => g.id)).toEqual(['inbox-signoffs', 'inbox-gates', 'inbox-questions']);
    expect(row(panel, signoffKey(C1)).querySelector('.ib-pass')!.textContent).toBe('Pass v3');
    expect(row(panel, signoffKey(C1)).querySelector('.ib-ev-what')!.textContent).toBe('C1 report · report v3');
    const design = row(panel, gateKey(EPIC, 'design_signoff'));
    expect(design.querySelector('textarea')).toBeNull();
    expect(design.querySelector('button')!.textContent).toBe('Review design');
    expect(row(panel, gateKey(EPIC, 'scope')).querySelector('textarea')).not.toBeNull();
    // agent text is rendered sanitised markdown, the rest textContent
    expect(row(panel, questionKey(M1)).querySelector('.ib-body strong')!.textContent).toBe('one');
  });
  it('Pass posts the version the row shows; a Fail with no note is stopped in the view', () => {
    const { panel, posts } = mount(full());
    const r = row(panel, signoffKey(C1));
    r.querySelector<HTMLButtonElement>('.ib-fail')!.click();
    expect(posts).toEqual([]);
    expect(r.querySelector('.ib-error')!.textContent).toMatch(/Fail needs a note/);
    r.querySelector<HTMLButtonElement>('.ib-pass')!.click();
    expect(posts).toEqual([{ type: 'inboxVerdict', key: signoffKey(C1), verdict: 'pass', note: '', version: 3 }]);
    expect(row(panel, signoffKey(C1)).querySelector<HTMLButtonElement>('.ib-pass')!.disabled).toBe(true);
  });
  it('Enter is a newline, Ctrl+Enter sends the reply (C14)', () => {
    const { panel, posts } = mount(full());
    const ta = row(panel, questionKey(M1)).querySelector('textarea')!;
    ta.value = 'the first';
    ta.dispatchEvent(new Event('input'));
    ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    expect(posts).toEqual([]);
    ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true, cancelable: true }));
    expect(posts).toEqual([{ type: 'inboxAnswer', key: questionKey(M1), text: 'the first' }]);
  });
  it('a done row leaves the list and its draft goes; a refusal stays on the row with the draft', () => {
    const { panel, c, s } = mount(full());
    const ta = row(panel, gateKey(EPIC, 'scope')).querySelector('textarea')!;
    ta.value = 'approved to 9';
    ta.dispatchEvent(new Event('input'));
    expect(c.local.inbox[gateKey(EPIC, 'scope')]).toBe('approved to 9');
    const stale = 'you are ruling version 3 but the doc is now v4; re-read and pass evidence_version=4, or stale_ok=true to sign the old one';
    inboxDone(s, c.local, { key: signoffKey(C1), ok: false, text: stale });
    inboxDone(s, c.local, { key: gateKey(EPIC, 'scope'), ok: true, text: 'Answered the scope gate.' });
    renderInbox(panel, c);
    expect(row(panel, gateKey(EPIC, 'scope'))).toBeNull();
    expect(c.local.inbox[gateKey(EPIC, 'scope')]).toBeUndefined();
    expect(row(panel, signoffKey(C1)).querySelector('.ib-error')!.textContent).toBe(stale);
    expect(inboxTab.badge(c)!.text).toBe('4');
    expect(panel.querySelector('#inbox-status')!.textContent).toBe('Answered the scope gate.');
  });
  it('loading, empty and a read error are said, not blank', () => {
    expect(mount({ scope: EPIC, items: [], loading: true, error: null }).panel.querySelector('#inbox-summary')!.textContent).toBe('Reading what waits on you…');
    expect(mount({ scope: EPIC, items: [], loading: false, error: null }).panel.querySelector('#inbox-summary')!.textContent).toBe('Nothing in this epic waits on you');
    expect(mount({ scope: EPIC, items: [], loading: false, error: 'Could not read what waits on you: boom' }).panel.querySelector('.ib-list-error')!.textContent).toMatch(/boom/);
  });
});
