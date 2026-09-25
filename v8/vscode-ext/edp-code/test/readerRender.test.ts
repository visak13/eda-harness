// @vitest-environment jsdom
// C16 s-579fa02cca: the reader's markdown: sanitised like a message, source lines on every block (C20's hook),
// heading ids for the outline, the selection mapped back to source lines, the proposal diff classed.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { chatHtml } from '../src/core/chatHtml';
import { diffLines, lineRange, renderDoc, slugger } from '../webview/readerRender';

const SRC = ['# Title', '', 'Intro line one', 'intro line two.', '', '## Part A', '', '- item 1', '- item 2', '', '```ts', 'const x = 1;', '```', '', '## Part A', '', '| a | b |', '|---|---|', '| 1 | 2 |'].join('\n');
const dom = (body: string) => { const d = document.createElement('div'); const r = renderDoc(document, body); d.append(r.frag); return { d, outline: r.outline }; };

describe('renderDoc', () => {
  it('stamps 1-based inclusive source lines on blocks', () => {
    const { d } = dom(SRC);
    const at = (sel: string) => { const e = d.querySelector(sel)!; return [Number(e.getAttribute('data-ls')), Number(e.getAttribute('data-le'))]; };
    expect(at('h1')).toEqual([1, 1]);
    expect(at('p')).toEqual([3, 4]);
    expect(at('ul')).toEqual([8, 9]);
    expect(at('li:nth-child(2)')).toEqual([9, 9]);
    expect(at('pre code')).toEqual([11, 13]); // markdown-it puts a fence's attrs on its <code>
    expect(at('table')).toEqual([17, 19]);
  });
  it('outline: every heading with a unique prefixed id and its line', () => {
    const { d, outline } = dom(SRC);
    expect(outline).toEqual([
      { level: 1, text: 'Title', id: 'h-title', line: 1 },
      { level: 2, text: 'Part A', id: 'h-part-a', line: 6 },
      { level: 2, text: 'Part A', id: 'h-part-a-1', line: 15 },
    ]);
    expect([...d.querySelectorAll('h1,h2')].map(h => h.id)).toEqual(['h-title', 'h-part-a', 'h-part-a-1']);
  });
  it('untrusted text stays inert: raw HTML is text, javascript: links are not links', () => {
    const { d } = dom('<img src=x onerror=alert(1)> <script>alert(2)</script>\n\n[x](javascript:alert(1)) [ok](https://example.com)');
    expect(d.querySelector('img,script')).toBeNull();
    expect(d.textContent).toContain('<script>alert(2)</script>');
    expect([...d.querySelectorAll('a')].map(a => a.getAttribute('href'))).toEqual(['https://example.com']);
    expect(d.querySelector('a')!.getAttribute('rel')).toBe('noreferrer noopener');
  });
  it('slugger: unicode kept, punctuation dropped, repeats numbered', () => {
    const s = slugger();
    expect(s('14.2 Proposal — Docs!')).toBe('h-142-proposal-docs');
    expect(s('14.2 Proposal — Docs!')).toBe('h-142-proposal-docs-1');
    expect(s('???')).toBe('h-section');
  });
  it('slugger: a heading whose text is a numbered repeat never takes an id already given (A, A, A-1)', () => {
    const s = slugger();
    const ids = ['A', 'A', 'A-1', 'A-1'].map(s);
    expect(ids).toEqual(['h-a', 'h-a-1', 'h-a-1-1', 'h-a-1-2']);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('lineRange (C20 hook)', () => {
  it('a selection inside one block is that block; across blocks spans both', () => {
    const { d } = dom(SRC);
    const p = d.querySelector('p')!.firstChild!, li2 = d.querySelector('li:nth-child(2)')!.firstChild!;
    expect(lineRange(p, p, d)).toEqual({ from: 3, to: 4 });
    expect(lineRange(p, li2, d)).toEqual({ from: 3, to: 9 });
    expect(lineRange(document.body, p, d)).toBeNull();
  });
});

describe('diffLines', () => {
  it('classes a unified diff', () => {
    expect(diffLines('--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n same').map(l => l.cls)).toEqual(['meta', 'meta', 'hunk', 'del', 'add', 'ctx']);
  });
});

describe('the reader document', () => {
  it('inlines one nonce\'d script and style under the chat CSP, titled', () => {
    const html = chatHtml('let a = "</script>";', 'b{}', 'NONCE', 'EDP design-aaaaaaaaaa v12', false);
    // the reader renders no images: its policy allows none (the chat's keeps img-src data: for pasted images)
    expect(html).toContain(`content="default-src 'none'; script-src 'nonce-NONCE'; style-src 'nonce-NONCE'; form-action 'none'; base-uri 'none'"`);
    expect(html).not.toContain('img-src');
    expect(html).toContain('<title>EDP design-aaaaaaaaaa v12</title>');
    expect(html).not.toMatch(/<\/script>";/);
  });
  it('the built reader bundle never fetches and carries no token header', () => {
    let js = '';
    try { js = readFileSync(resolve(import.meta.dirname, '..', 'dist', 'reader.js'), 'utf8'); } catch { return; } // not built yet
    expect(js).not.toMatch(/X-Token|EDP8_TOKEN|fetch\(|XMLHttpRequest|WebSocket|import\(/);
  });
});
