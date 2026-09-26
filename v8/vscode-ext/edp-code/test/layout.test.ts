// t-93da8bf09d: the reader's full screen toggles back, shows its way out, and Reset layout leaves Zen.
import { describe, expect, it } from 'vitest';
import { FULL_SCREEN_HINT, Layout, RESET_VIEWS, ZEN_EXIT, ZEN_TOGGLE, freshStamp } from '../src/core/layout';
import { parseReaderInbound } from '../src/core/reader';

const fixture = () => {
  const ran: string[] = [];
  const seen: boolean[] = [];
  const layout = new Layout(async c => { ran.push(c); });
  layout.onChange(on => seen.push(on));
  return { ran, seen, layout };
};

describe('Layout', () => {
  it('full screen enters Zen and the way back leaves it (never a second toggle)', async () => {
    const { ran, seen, layout } = fixture();
    await layout.enterFullScreen();
    expect(layout.fullScreen).toBe(true);
    await layout.exitFullScreen();
    expect(layout.fullScreen).toBe(false);
    expect(ran).toEqual([ZEN_TOGGLE, ZEN_EXIT]);
    expect(seen).toEqual([true, false]);
  });

  it('a stale leave (Zen already left through Ctrl+K Z) is harmless: exitZenMode, not a toggle back in', async () => {
    const { ran, layout } = fixture();
    await layout.exitFullScreen();
    expect(ran).toEqual([ZEN_EXIT]);
  });

  it('Reset layout leaves Zen and puts the views back', async () => {
    const { ran, seen, layout } = fixture();
    await layout.enterFullScreen();
    await layout.reset();
    expect(ran).toEqual([ZEN_TOGGLE, ZEN_EXIT, RESET_VIEWS]);
    expect(seen).toEqual([true, false]);
    expect(layout.fullScreen).toBe(false);
  });

  it('the hint names both ways out', () => {
    expect(FULL_SCREEN_HINT).toContain('Ctrl+K Z');
    expect(FULL_SCREEN_HINT).toContain('⛶');
  });

  it('the reader may ask to leave full screen', () => {
    expect(parseReaderInbound({ v: 1, type: 'exitFullScreen', x: 1 })).toEqual({ v: 1, type: 'exitFullScreen' });
  });
});

describe('freshStamp', () => {
  it('acts on a stamp written after the watch began, once', () => {
    expect(freshStamp(2000, 0, 1000)).toBe(true);
    expect(freshStamp(2000, 2000, 1000)).toBe(false);
  });
  it('ignores a stamp left from before this window, and a removed one', () => {
    expect(freshStamp(500, 0, 1000)).toBe(false);
    expect(freshStamp(0, 2000, 1000)).toBe(false);
  });
});
