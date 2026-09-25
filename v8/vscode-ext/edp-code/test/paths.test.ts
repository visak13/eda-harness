import { describe, expect, it } from 'vitest';
import {
  activeHashTag, excluder, foldersOf, globToRegExp, indexRows, matchPaths, parseLsFilesZ, pathCandidate, pathToken, type PathHit,
} from '../src/core/paths';

describe('activeHashTag: when # opens the picker', () => {
  it('at the start, after a space or punctuation, with the query typed so far', () => {
    expect(activeHashTag('#', 1)).toEqual({ start: 0, query: '' });
    expect(activeHashTag('see #v8/vs', 10)).toEqual({ start: 4, query: 'v8/vs' });
    expect(activeHashTag('(#web', 5)).toEqual({ start: 1, query: 'web' });
    expect(activeHashTag('line\n#src', 9)).toEqual({ start: 5, query: 'src' });
  });

  it('several tags per message: the one under the caret', () => {
    const t = 'compare `a.ts` and #b';
    expect(activeHashTag(t, t.length)).toEqual({ start: 19, query: 'b' });
    const u = '`x/` then #chat.ts ';
    expect(activeHashTag(u, u.length)).toBeUndefined(); // a space ends the query
    expect(activeHashTag(u, u.length - 1)).toEqual({ start: 10, query: 'chat.ts' });
  });

  it('not after a word character (C#, issue#12, a#b)', () => {
    expect(activeHashTag('C#', 2)).toBeUndefined();
    expect(activeHashTag('issue#12', 8)).toBeUndefined();
    expect(activeHashTag('a_#b', 4)).toBeUndefined();
  });

  it('not inside a code span or fence: closed, still open, or closing after the caret', () => {
    expect(activeHashTag('`#x`', 2)).toBeUndefined();             // inside a closed span
    expect(activeHashTag('try `#', 6)).toBeUndefined();            // an open span being typed
    expect(activeHashTag('```\n#', 5)).toBeUndefined();            // an open fence
    expect(activeHashTag('```\n#x\n```', 6)).toBeUndefined();      // inside a closed fence
    expect(activeHashTag('`a` #b', 6)).toEqual({ start: 4, query: 'b' }); // after a closed span: yes
    expect(activeHashTag('```\ncode\n```\n#b', 15)).toEqual({ start: 13, query: 'b' });
  });

  it('a second # or a backtick ends the query', () => {
    expect(activeHashTag('##', 2)).toBeUndefined();
    expect(activeHashTag('#a`', 3)).toBeUndefined();
  });
});

describe('tokens and the index', () => {
  it('a file token is the backticked path, a folder token ends with /', () => {
    expect(pathToken({ path: 'v8/README.md', kind: 'file' })).toBe('`v8/README.md` ');
    expect(pathToken({ path: 'v8/vscode-ext', kind: 'folder' })).toBe('`v8/vscode-ext/` ');
  });

  it('parses ls-files -z, deduplicated', () => {
    expect(parseLsFilesZ('a.ts\0b/c.ts\0b/c.ts\0')).toEqual(['a.ts', 'b/c.ts']);
    expect(parseLsFilesZ('')).toEqual([]);
  });

  it('derives every ancestor folder', () => {
    expect(foldersOf(['a/b/c.ts', 'a/d.ts', 'e.ts'])).toEqual(['a', 'a/b']);
  });

  it('indexRows drops paths a token cannot carry (backtick, newline)', () => {
    const rows = indexRows(['ok/x.ts', 'bad`name.ts', 'nl\nx.ts']);
    expect(rows).toEqual([{ path: 'ok', kind: 'folder' }, { path: 'ok/x.ts', kind: 'file' }]);
  });
});

describe('files.exclude globs', () => {
  it.each([
    ['**/.git', '.git', true], ['**/.git', 'a/.git', true], ['**/.git', 'a/.github', false],
    ['**/*.js', 'x.js', true], ['**/*.js', 'a/b/x.js', true], ['**/*.js', 'a/x.jsx', false],
    ['node_modules', 'node_modules', true], ['node_modules', 'a/node_modules', false],
    ['**/{dist,out}', 'a/dist', true], ['**/{dist,out}', 'a/out', true], ['**/{dist,out}', 'a/outx', false],
    ['*.log', 'x.log', true], ['*.log', 'a/x.log', false], ['?.md', 'a.md', true], ['?.md', 'ab.md', false],
    ['**/[Tt]humbs.db', 'x/Thumbs.db', true], ['a/**', 'a/b/c', true],
  ])('%s vs %s = %s', (g, p, want) => expect(globToRegExp(g).test(p)).toBe(want));

  it('a path is excluded when it or a folder above it matches a true pattern; when-clauses and false do not exclude', () => {
    const ex = excluder({ '**/node_modules': true, '**/*.map': true, '**/*.js': { when: '$(basename).ts' }, 'dist': false });
    expect(ex('web/node_modules/x/index.js')).toBe(true);
    expect(ex('a/b.js.map')).toBe(true);
    expect(ex('a/b.js')).toBe(false);
    expect(ex('dist/x')).toBe(false);
    expect(excluder(undefined)('anything')).toBe(false);
  });

  it('ignoreCase for Windows', () => expect(excluder({ '**/THUMBS.db': true }, true)('a/thumbs.db')).toBe(true));
});

describe('matchPaths: fuzzy, capped', () => {
  const rows: PathHit[] = indexRows([
    'v8/vscode-ext/edp-code/src/vscode/chat.ts', 'v8/vscode-ext/edp-code/webview/chat.css', 'v8/web/src/chatter.tsx',
    'v8/README.md', 'README.md', 'v8/edp8/board.py', 'v8/tests/fixtures/mention_cases.json',
  ]);

  it('basename prefix, then basename substring, then path substring, then subsequence', () => {
    const got = matchPaths(rows, 'chat').map(h => h.path);
    expect(got.slice(0, 3)).toEqual(['v8/web/src/chatter.tsx', 'v8/vscode-ext/edp-code/webview/chat.css', 'v8/vscode-ext/edp-code/src/vscode/chat.ts']);
    expect(matchPaths(rows, 'mcj').map(h => h.path)).toEqual(['v8/tests/fixtures/mention_cases.json']);
  });

  it('finds folders too, and a query with / matches across folders', () => {
    const got = matchPaths(rows, 'edp-code');
    expect(got[0]).toEqual({ path: 'v8/vscode-ext/edp-code', kind: 'folder' });
    expect(matchPaths(rows, 'code/webview')[0]).toEqual({ path: 'v8/vscode-ext/edp-code/webview', kind: 'folder' });
    expect(matchPaths(rows, 'vscode-ext/')[0]).toEqual({ path: 'v8/vscode-ext', kind: 'folder' });
  });

  it('is case-insensitive', () => expect(matchPaths(rows, 'readme').map(h => h.path)).toEqual(['README.md', 'v8/README.md']));

  it('empty query: top-level folders, then top-level files', () => {
    expect(matchPaths(rows, '')).toEqual([{ path: 'v8', kind: 'folder' }, { path: 'README.md', kind: 'file' }]);
    const az = matchPaths(indexRows(['src/a', 'gen/b', 'docs/c', 'Zeta.md', 'alpha.md']), '').map(h => h.path);
    expect(az).toEqual(['docs', 'gen', 'src', 'alpha.md', 'Zeta.md']);
  });

  it('caps the result count', () => {
    const many = indexRows(Array.from({ length: 500 }, (_, i) => `d/f${i}.ts`));
    expect(matchPaths(many, 'f')).toHaveLength(50);
    expect(matchPaths(many, 'f', 7)).toHaveLength(7);
  });

  it('stays fast on a repo-sized index (20k files)', () => {
    const big = indexRows(Array.from({ length: 20_000 }, (_, i) => `v8/pkg${i % 97}/src/mod${i % 13}/file${i}.ts`));
    const t0 = performance.now();
    for (const q of ['f', 'file19', 'pkg5/src', 'zzz']) matchPaths(big, q);
    expect((performance.now() - t0) / 4).toBeLessThan(50);
  });
});

describe('pathCandidate: which inline code spans may be links', () => {
  it.each([
    ['v8/README.md', { path: 'v8/README.md', folder: false }],
    ['v8/vscode-ext/', { path: 'v8/vscode-ext', folder: true }],
    ['README.md', { path: 'README.md', folder: false }],
  ])('%s', (t, want) => expect(pathCandidate(t)).toEqual(want));

  it.each(['npm test', 'foo', '../etc/passwd', '/abs/x', 'C:/x/y', 'a\\b.ts', '.', '', 'src/x.ts:L1-5 @abc1234'])(
    'not %j', t => expect(pathCandidate(t)).toBeUndefined());
});
