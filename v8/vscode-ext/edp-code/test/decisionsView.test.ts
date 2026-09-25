// @vitest-environment jsdom
// C17 s-5e83f9d0af: the Decisions tab view. Rows in the host's order, binding and withdrawn marked; Withdraw and
// Binding on/off only for a viewer the board lets manage, and never on a withdrawn row; each button posts only a
// decision id (and the flag); the source link opens the source; a refusal shows on its row.
import { describe, expect, it } from 'vitest';
import type { ChatState } from '../src/core/chatProtocol';
import { decisionRows, type BoardDecision, type DecisionsState } from '../src/core/decisions';
import { restoreLocal } from '../src/core/viewState';
import type { TabCtx } from '../webview/tabs';
import { decisionsTab, renderDecisions } from '../webview/views/decisions';

const EPIC = 'epic-0123456789', STORY = 's-0123456789';
const D1 = 'dec-1111111111', D2 = 'dec-2222222222', D3 = 'dec-3333333333', M1 = 'm-aaaaaaaaaa';
const dec = (id: string, o: Partial<BoardDecision> = {}): BoardDecision => ({ id, scope: EPIC, text: `rule ${id}`, decided_by: 'owner',
  decided_at: '2026-09-25T10:00:00Z', binding: false, status: 'live', replaces: [], ...o });
const decisions = (canManage: boolean, o: Partial<DecisionsState> = {}): DecisionsState => ({
  scope: EPIC, canManage, loading: false, error: null,
  rows: decisionRows({ scope: EPIC, epic: EPIC, decisions: [
    dec(D1, { binding: true, source: M1, source_kind: 'message', source_ticket: STORY, scope: STORY, detail: 'the why' }),
    dec(D2, { replaces: [D3] }),
    dec(D3, { status: 'withdrawn', withdrawn_reason: 'mistaken' }),
  ] }), ...o,
});
function ctx(d: DecisionsState | null) {
  const s: ChatState = {
    type: 'state', v: 1, me: null, ticket: { id: EPIC, kind: 'epic', title: 'E', status: 'in_progress' }, epic: { id: EPIC, kind: 'epic', title: 'E', status: 'in_progress' },
    stories: [{ id: STORY, kind: 'story', title: 'C17 decisions', status: 'in_progress', unread: 0 }], commits: [], unlinked: [], uncommitted: null,
    architect: null, people: [], items: [], hasOlder: false, chip: null, feed: 'live', notice: null, decisions: d,
  };
  const posts: unknown[] = [];
  const c: TabCtx = { state: s, local: restoreLocal(undefined), post: m => posts.push(m), persist: () => {}, select: () => {}, chatUnread: 0 };
  const panel = document.createElement('section');
  renderDecisions(panel, c);
  return { panel, posts, c };
}
const ids = (panel: HTMLElement) => [...panel.querySelectorAll<HTMLElement>('.de-row')].map(r => r.dataset.id);
const btn = (panel: HTMLElement, id: string) => panel.querySelector<HTMLButtonElement>(`#${id}`);

describe('the Decisions view', () => {
  it('lists rows in the host order with their flags, detail, scope, replaces and withdrawn reason', () => {
    const { panel } = ctx(decisions(false));
    expect(ids(panel)).toEqual([D1, D2, D3]);
    expect(panel.querySelector('#decisions-summary')!.textContent).toBe('2 live, 1 withdrawn in this epic');
    const r1 = panel.querySelector(`#de-${D1}`)!;
    expect(r1.querySelector('.de-flag-binding')).not.toBeNull();
    expect(r1.querySelector('.de-detail')!.textContent).toBe('the why');
    expect(r1.querySelector('.de-scope')!.textContent).toBe('on C17 decisions');
    expect(panel.querySelector(`#de-${D2} .de-replaces`)!.textContent).toBe(`replaces ${D3}`);
    expect(panel.querySelector(`#de-${D3}`)!.classList.contains('de-withdrawn')).toBe(true);
    expect(panel.querySelector(`#de-${D3} .de-reason`)!.textContent).toBe('Withdrawn: mistaken');
  });
  it('Withdraw and Binding are hidden for a viewer who may not manage; the source link stays', () => {
    const { panel } = ctx(decisions(false));
    expect(panel.querySelectorAll('[id^=de-withdraw-], [id^=de-binding-]')).toHaveLength(0);
    expect(btn(panel, `de-open-${D1}`)).not.toBeNull();
  });
  it('for the owner/architect: on live rows only, each posting only the id (and the flag)', () => {
    const { panel, posts } = ctx(decisions(true));
    expect(btn(panel, `de-withdraw-${D3}`)).toBeNull();
    expect(btn(panel, `de-binding-${D3}`)).toBeNull();
    expect(btn(panel, `de-binding-${D1}`)!.textContent).toBe('Unbind');
    expect(btn(panel, `de-binding-${D2}`)!.textContent).toBe('Make binding');
    btn(panel, `de-binding-${D1}`)!.click();
    btn(panel, `de-binding-${D2}`)!.click();
    btn(panel, `de-withdraw-${D2}`)!.click();
    btn(panel, `de-open-${D1}`)!.click();
    expect(posts).toEqual([
      { type: 'decisionBinding', id: D1, binding: false }, { type: 'decisionBinding', id: D2, binding: true },
      { type: 'decisionWithdraw', id: D2 }, { type: 'decisionOpen', id: D1 },
    ]);
  });
  it('a write in flight disables the write buttons; a refusal shows on its row as an alert', () => {
    const { panel } = ctx(decisions(true, { busy: D2, notice: null }));
    expect(btn(panel, `de-withdraw-${D1}`)!.disabled).toBe(true);
    expect(panel.querySelector(`#de-${D2}`)!.getAttribute('aria-busy')).toBe('true');
    const r = ctx(decisions(true, { notice: { id: D1, ok: false, text: 'engineer may not change a decision binding flag' } })).panel;
    const n = r.querySelector(`#de-notice-${D1}`)!;
    expect(n.getAttribute('role')).toBe('alert');
    expect(n.textContent).toBe('engineer may not change a decision binding flag');
  });
  it('loading, empty, and a list error', () => {
    expect(ctx(null).panel.querySelector('#decisions-summary')!.textContent).toBe('Reading the decisions…');
    expect(ctx(decisions(false, { rows: [] })).panel.querySelector('#decisions-summary')!.textContent).toBe('No decisions recorded in this epic');
    const e = ctx(decisions(false, { rows: [], error: "You cannot read this epic's decisions: x" })).panel.querySelector('#decisions-error')!;
    expect(e.getAttribute('role')).toBe('alert');
  });
  it('the badge is the live count', () => {
    expect(decisionsTab.badge(ctx(decisions(false)).c)).toEqual({ text: '2', aria: '2 live decisions' });
  });
});
