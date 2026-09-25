import { describe, expect, it } from 'vitest';
import { cursorMark, sseParser, type Frame } from '../src/core/sse';

const run = (...chunks: string[]) => { const out: Frame[] = []; const p = sseParser(f => out.push(f)); chunks.forEach(p); return out; };

describe('sseParser', () => {
  it('LF, CRLF and CR line ends', () => {
    expect(run('data: {"a":1}\n\n')).toEqual([{ data: '{"a":1}' }]);
    expect(run('data: {"a":1}\r\n\r\n')).toEqual([{ data: '{"a":1}' }]);
    expect(run('data: {"a":1}\r\r')).toEqual([{ data: '{"a":1}' }]);
  });

  it('a frame split across two chunks, including a CRLF split between chunks', () => {
    expect(run('data: {"se', 'q":5}\n', '\n')).toEqual([{ data: '{"seq":5}' }]);
    expect(run('data: x\r', '\n\r\n')).toEqual([{ data: 'x' }]);
  });

  it('comment frames: ready, resync, ping', () => {
    expect(run(': ready 12\n\n: resync 40\n\n: ping\n\n')).toEqual([{ comment: 'ready 12' }, { comment: 'resync 40' }, { comment: 'ping' }]);
    expect(cursorMark('ready 12')).toEqual({ mark: 'ready', cursor: 12 });
    expect(cursorMark('resync 40')).toEqual({ mark: 'resync', cursor: 40 });
    expect(cursorMark('ping')).toBeUndefined();
  });

  it('multi-line data and data without a space', () => {
    expect(run('data: a\ndata: b\n\n')).toEqual([{ data: 'a\nb' }]);
    expect(run('data:x\n\n')).toEqual([{ data: 'x' }]);
  });

  it('keeps an incomplete frame until its blank line', () => {
    expect(run('data: a\n')).toEqual([]);
  });
});
