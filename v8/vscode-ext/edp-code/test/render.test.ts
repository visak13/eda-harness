// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { bodyFragment, renderBody } from '../webview/render';

const html = (text: string) => { const d = document.createElement('div'); d.append(bodyFragment(document, text, new Set(['owner']))); return d; };

describe('renderBody (markdown-it html:false + DOMPurify)', () => {
  it('<script> and <img onerror> render as inert text', () => {
    const d = html('hi <img src=x onerror=alert(1)> and <script>alert(2)</script>');
    expect(d.querySelector('img,script')).toBeNull();
    expect(d.textContent).toContain('<img src=x onerror=alert(1)>');
    expect(d.textContent).toContain('<script>alert(2)</script>');
    expect(d.innerHTML).not.toMatch(/<img|<script/);
  });

  it('[x](javascript:…) is not a link; http(s) links are', () => {
    expect(html('[x](javascript:alert(1))').querySelector('a')).toBeNull();
    expect(html('[x](data:text/html,hi)').querySelector('a')).toBeNull();
    expect(html('[ok](https://example.com)').querySelector('a')?.getAttribute('href')).toBe('https://example.com');
  });

  it('raw HTML is shown as text; code fences are kept', () => {
    expect(renderBody('<b>bold</b>')).toContain('&lt;b&gt;bold&lt;/b&gt;');
    const d = html('```\nconst a = 1;\n```');
    expect(d.querySelector('pre code')?.textContent).toBe('const a = 1;\n');
  });

  it('@handles are highlighted in text, never inside code', () => {
    const d = html('ping @owner and @nobody, `@owner` stays code');
    const spans = [...d.querySelectorAll('span.mention')];
    expect(spans.map(s => s.textContent)).toEqual(['@owner', '@nobody']);
    expect(spans[0].classList.contains('known')).toBe(true);
    expect(d.querySelector('code')?.textContent).toBe('@owner');
  });
});
