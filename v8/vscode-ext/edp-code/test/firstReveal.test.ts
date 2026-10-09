import { describe, expect, it } from 'vitest';
import { FIRST_REVEAL_KEY, revealOnFirstStart } from '../src/core/firstReveal';

const store = () => { const m = new Map<string, unknown>(); return { m, get: <T>(k: string) => m.get(k) as T | undefined, update: async (k: string, v: unknown) => { m.set(k, v); } }; };

describe('revealOnFirstStart', () => {
  it('reveals once on a fresh profile and remembers it', async () => {
    const s = store(); let n = 0;
    expect(await revealOnFirstStart(s, async () => { n++; })).toBe(true);
    expect(await revealOnFirstStart(s, async () => { n++; })).toBe(false);
    expect(n).toBe(1);
    expect(s.m.get(FIRST_REVEAL_KEY)).toBe(true);
  });
  it('tries again next start when the reveal failed', async () => {
    const s = store();
    expect(await revealOnFirstStart(s, async () => { throw new Error('no workbench yet'); })).toBe(false);
    expect(s.m.has(FIRST_REVEAL_KEY)).toBe(false);
    expect(await revealOnFirstStart(s, async () => {})).toBe(true);
  });
});
