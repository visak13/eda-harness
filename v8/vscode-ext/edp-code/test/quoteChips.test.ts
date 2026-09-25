// @vitest-environment jsdom
// C20: the composer's quote chips. A note typed in one thread and not yet posted (300 ms debounce) goes to THAT
// thread when the view switches threads (C20 second opinion: it was re-addressed to the new thread and lost).
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { QuoteChip } from '../src/core/chatProtocol';
import { QuoteChips } from '../webview/quotes';

const A = 's-aaaaaaaaaa', B = 's-bbbbbbbbbb', K = 'q-0123456789ab';
const chip = (key: string): QuoteChip => ({ key, source: 'code', label: 'src/a.ts:L1-2', passage: 'x', note: '' });

afterEach(() => vi.useRealTimers());

describe('QuoteChips', () => {
  it('a pending note is posted to the thread it was typed in, before another thread renders', () => {
    vi.useFakeTimers();
    const posts: unknown[] = [];
    const c = new QuoteChips(m => posts.push(m), document.createElement('div'));
    document.body.append(c.box);
    c.render(A, [chip(K)]);
    const inp = c.box.querySelector<HTMLInputElement>('.qchip-note')!;
    inp.focus();
    inp.value = 'typed in A';
    inp.dispatchEvent(new Event('input'));
    c.render(B, [chip('q-bbbbbbbbbbbb')]);
    vi.advanceTimersByTime(1000);
    expect(posts).toEqual([{ type: 'quoteNote', ticketId: A, key: K, note: 'typed in A' }]);
  });

  it('move and remove post the key with the open thread; the arrows are disabled at the ends', () => {
    const posts: unknown[] = [];
    const c = new QuoteChips(m => posts.push(m), document.createElement('div'));
    c.render(A, [chip(K), chip('q-bbbbbbbbbbbb')]);
    const li = c.box.querySelectorAll('li');
    expect((li[0].querySelector('.qchip-up') as HTMLButtonElement).disabled).toBe(true);
    expect((li[1].querySelector('.qchip-down') as HTMLButtonElement).disabled).toBe(true);
    (li[1].querySelector('.qchip-up') as HTMLButtonElement).click();
    (li[0].querySelector('.qchip-remove') as HTMLButtonElement).click();
    expect(posts).toEqual([{ type: 'quoteMove', key: 'q-bbbbbbbbbbbb', by: -1, ticketId: A }, { type: 'quoteDrop', key: K, ticketId: A }]);
    expect(c.keys).toEqual([K, 'q-bbbbbbbbbbbb']);
  });
});
