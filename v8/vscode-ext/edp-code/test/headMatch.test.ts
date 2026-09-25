import { describe, expect, it } from 'vitest';
import { dirtyAgainstHead, sameAsHead } from '../src/core/headMatch';

// s-17c13096e5 (qa m-7beeffa077): dirty is judged on the lines captured for the anchor
const HEAD = 'a\r\nb\r\n';
const show = (text: string) => async () => text;

describe('sameAsHead', () => {
  it('equals the blob line for line, CRLF or LF, trailing newline included', () => {
    expect(sameAsHead(HEAD, ['a', 'b', ''])).toBe(true);
    expect(sameAsHead('a\nb', ['a', 'b'])).toBe(true);
    expect(sameAsHead(HEAD, ['a', 'b'])).toBe(false);
    expect(sameAsHead(HEAD, ['a', 'B', ''])).toBe(false);
  });
});

describe('dirtyAgainstHead', () => {
  it('status clean at capture but the captured lines differ from HEAD: dirty', async () => {
    expect(await dirtyAgainstHead({ lines: ['a', 'CHANGED', ''], isDirty: false }, false, 'c1', show(HEAD))).toBe(true);
  });
  it('captured lines equal HEAD: clean, whatever the buffer holds by the time git answers', async () => {
    const buffer = { lines: ['a', 'b', ''] };
    const late = async () => { buffer.lines = ['edited', 'after', 'capture']; return HEAD; };
    const snap = { lines: [...buffer.lines], isDirty: false };
    expect(await dirtyAgainstHead(snap, false, 'c1', late)).toBe(false);
  });
  it('unsaved at capture or listed by git status: dirty without reading the blob', async () => {
    const never = async (): Promise<string> => { throw new Error('not read'); };
    expect(await dirtyAgainstHead({ lines: ['a', 'b', ''], isDirty: true }, false, 'c1', never)).toBe(true);
    expect(await dirtyAgainstHead({ lines: ['a', 'b', ''], isDirty: false }, true, 'c1', never)).toBe(true);
  });
  it('a missing blob is never clean; no HEAD leaves it to status', async () => {
    const missing = async (): Promise<string> => { throw new Error('path not in commit'); };
    expect(await dirtyAgainstHead({ lines: ['a'], isDirty: false }, false, 'c1', missing)).toBe(true);
    expect(await dirtyAgainstHead({ lines: ['a'], isDirty: false }, false, null, missing)).toBe(false);
  });
});
