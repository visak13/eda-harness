// C14 (s-8cc2cc80b3, owner m-db09472a68): the composer sends on Ctrl+Enter (Cmd+Enter on macOS), as the
// board UI's Composer does; a plain Enter (or Shift/Alt+Enter) is a newline.
import { describe, expect, it } from 'vitest';
import { isSendKey, sendChord } from '../src/core/composerKeys';

const k = (key: string, mods: Partial<{ ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean }> = {}) =>
  ({ key, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...mods });

describe('isSendKey', () => {
  it('Ctrl+Enter and Cmd+Enter send', () => {
    expect(isSendKey(k('Enter', { ctrlKey: true }))).toBe(true);
    expect(isSendKey(k('Enter', { metaKey: true }))).toBe(true);
  });
  it('a plain, Shift or Alt Enter is a newline, never a send', () => {
    expect(isSendKey(k('Enter'))).toBe(false);
    expect(isSendKey(k('Enter', { shiftKey: true }))).toBe(false);
    expect(isSendKey(k('Enter', { altKey: true }))).toBe(false);
  });
  it('Ctrl with another key is not a send', () => expect(isSendKey(k('a', { ctrlKey: true }))).toBe(false));
});

describe('sendChord: the hint names the platform chord', () => {
  it('Ctrl+Enter on Windows/Linux, Cmd+Enter on macOS', () => {
    expect(sendChord('Win32')).toBe('Ctrl+Enter');
    expect(sendChord('Linux x86_64')).toBe('Ctrl+Enter');
    expect(sendChord('MacIntel')).toBe('Cmd+Enter');
  });
});
