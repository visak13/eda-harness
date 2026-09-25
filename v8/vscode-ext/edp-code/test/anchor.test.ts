import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { buildAnchor, lineSpan, normDrive, relPath, samePath, truncateUtf8, type Sel } from '../src/core/anchor';
import { at, render } from '../src/core/render';

const sel = (startLine: number, startChar: number, endLine: number, endChar: number): Sel =>
  ({ startLine, startChar, endLine, endChar, isEmpty: startLine === endLine && startChar === endChar });
const sha = (s: string) => createHash('sha256').update(s, 'utf8').digest('hex');

describe('lineSpan (0-based selection -> 1-based inclusive lines)', () => {
  it('empty selection anchors the cursor line', () => expect(lineSpan(sel(9, 4, 9, 4))).toEqual([10, 10]));
  it('single-line selection', () => expect(lineSpan(sel(9, 2, 9, 8))).toEqual([10, 10]));
  it('reversed drag arrives ordered (editor.selection.start/end) and spans the same lines', () =>
    expect(lineSpan(sel(9, 0, 19, 5))).toEqual([10, 20]));
  it('drag ending at column 0 of the next line does not include that line', () =>
    expect(lineSpan(sel(9, 0, 20, 0))).toEqual([10, 20]));
  it('drag ending mid-line includes that line', () => expect(lineSpan(sel(9, 0, 19, 3))).toEqual([10, 20]));
  it('a col-0 end on the SAME line (a caret) is not shortened below the start', () =>
    expect(lineSpan({ startLine: 4, startChar: 0, endLine: 4, endChar: 0, isEmpty: true })).toEqual([5, 5]));
});

describe('relPath / normDrive', () => {
  it('nested path -> forward slashes', () => expect(relPath('C:\\repo', 'C:\\repo\\src\\a\\b.py')).toBe('src/a/b.py'));
  it('c:\\ -> C:\\', () => expect(normDrive('c:\\Projects\\x')).toBe('C:\\Projects\\x'));
  it('drive case does not matter to the relative path', () => expect(relPath('C:\\repo', normDrive('c:\\repo\\x.ts'))).toBe('x.ts'));
  it('a file outside the root throws', () => expect(() => relPath('C:\\repo', 'C:\\other\\x.ts')).toThrow(/outside/));
  it('a sibling dir sharing the prefix is outside', () => expect(() => relPath('C:\\repo', 'C:\\repo2\\x.ts')).toThrow(/outside/));
  it('another drive is outside', () => expect(() => relPath('C:\\repo', 'D:\\repo\\x.ts')).toThrow(/outside/));
  it('the root itself throws', () => expect(() => relPath('C:\\repo', 'C:\\repo')).toThrow(/outside/));
  it('a file named "..foo" inside the root is inside', () => expect(relPath('C:\\repo', 'C:\\repo\\..foo')).toBe('..foo'));
  it('POSIX roots work too', () => expect(relPath('/srv/repo', '/srv/repo/a/b.ts')).toBe('a/b.ts'));
  it('samePath is case-insensitive on Windows paths and ignores a trailing slash', () =>
    expect(samePath('c:\\Projects\\V8\\', 'C:\\projects\\v8')).toBe(true));
});

describe('truncateUtf8 (4096 B cap on a code-point boundary)', () => {
  it('ASCII at exactly 4096 B is kept whole', () => {
    const s = 'a'.repeat(4096);
    expect(truncateUtf8(s)).toEqual({ text: s, truncated: false });
  });
  it('4097 B ASCII is cut to 4096', () => {
    const r = truncateUtf8('a'.repeat(4097));
    expect(Buffer.byteLength(r.text)).toBe(4096);
    expect(r.truncated).toBe(true);
  });
  it('a 4-byte emoji straddling the cut is dropped whole', () => {
    const s = 'a'.repeat(4094) + '😀' + 'b';
    const r = truncateUtf8(s);
    expect(r.text).toBe('a'.repeat(4094));
    expect(r.text).not.toContain('\uFFFD');
  });
  it('CJK text is cut on a character boundary', () => {
    const s = '漢'.repeat(2000); // 3 B each = 6000 B
    const r = truncateUtf8(s);
    expect(Buffer.byteLength(r.text)).toBeLessThanOrEqual(4096);
    expect(r.text).toBe('漢'.repeat(1365));
  });
});

describe('buildAnchor', () => {
  const lines = Array.from({ length: 25 }, (_, i) => `line ${i + 1}`);
  it('CRLF source lines (lineAt text carries no EOL) give an LF snippet', () => {
    const { anchor } = buildAnchor({ repoRoot: 'c:\\repo', fsPath: 'c:\\repo\\src\\sample.py', lines, sel: sel(9, 0, 19, 7), commit: 'a'.repeat(40), dirty: false });
    expect(anchor.snippet).toBe(lines.slice(9, 20).join('\n'));
    expect(anchor.snippet).not.toContain('\r');
    expect(anchor).toMatchObject({ repo_root: 'C:\\repo', path: 'src/sample.py', line_start: 10, line_end: 20 });
  });
  it('snippet_sha is sha256 of exactly the sent snippet (also after truncation)', () => {
    const big = ['x'.repeat(5000)];
    const { anchor, truncated } = buildAnchor({ repoRoot: 'C:\\r', fsPath: 'C:\\r\\a', lines: big, sel: sel(0, 0, 0, 3), commit: null, dirty: false });
    expect(truncated).toBe(true);
    expect(anchor.snippet_sha).toBe(sha(anchor.snippet));
  });
  it('commit null passes through (not a git folder)', () => {
    const { anchor } = buildAnchor({ repoRoot: 'C:\\r', fsPath: 'C:\\r\\a', lines, sel: sel(0, 0, 0, 0), commit: null, dirty: true });
    expect(anchor.commit).toBeNull();
    expect(anchor.dirty).toBe(true);
  });
});

describe('render (steer m-1607603a0c: note + one anchor line, no snippet)', () => {
  const a = { repo_root: 'C:\\r', path: 'src/sample.py', line_start: 10, line_end: 20, commit: '0123456789abcdef0123456789abcdef01234567', dirty: false, snippet: 'print("```")', snippet_sha: '' };
  it('clean: path:Lx-y @sha7', () => expect(render(a, 'why?', false)).toBe('why?\n\n`src/sample.py:L10-20 @0123456`'));
  it('[dirty]', () => expect(at({ ...a, dirty: true })).toBe('src/sample.py:L10-20 @0123456[dirty]'));
  it('@no-git', () => expect(at({ ...a, commit: null })).toBe('src/sample.py:L10-20 @no-git'));
  it('the snippet (even one containing ```) never enters the text', () => {
    const t = render(a, 'look', false);
    expect(t).not.toContain('print(');
    expect(t).not.toContain('```');
  });
  it('truncation is stated in the text', () => expect(render(a, 'n', true)).toContain('(snippet truncated to 4096 B)'));
});
