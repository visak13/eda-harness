import { describe, expect, it } from 'vitest';
import { chatHtml, cspFor } from '../src/core/chatHtml';

describe('chatHtml', () => {
  it('CSP is exactly default-src none + nonce script/style (+ img data:, form-action, base-uri), no connect-src', () => {
    const html = chatHtml('console.log(1)', 'body{}', 'N0nce');
    expect(cspFor('N0nce')).toBe("default-src 'none'; script-src 'nonce-N0nce'; style-src 'nonce-N0nce'; img-src data:; form-action 'none'; base-uri 'none'");
    expect(html).toContain(`content="${cspFor('N0nce')}"`);
    expect(html).not.toMatch(/connect-src|unsafe-inline|unsafe-eval|vscode-resource|vscode-cdn/);
    expect(html).toContain('<script nonce="N0nce">console.log(1)</script>');
    expect(html).toContain('<style nonce="N0nce">body{}</style>');
    expect(html.match(/<script/g)).toHaveLength(1);
  });

  it('a new node:crypto nonce per call', () => {
    const n = (h: string) => /nonce="([^"]+)"/.exec(h)![1];
    const a = chatHtml('', ''), b = chatHtml('', '');
    expect(n(a)).not.toBe(n(b));
    expect(n(a)).toMatch(/^[A-Za-z0-9+/]{22}==$/);
  });

  it('escapes </script in the bundle and </style in the CSS', () => {
    const html = chatHtml('var s="</script><script>alert(1)</script>"', 'a{content:"</style>"}', 'n');
    expect(html.match(/<\/script>/g)).toHaveLength(1);
    expect(html.match(/<\/style>/g)).toHaveLength(1);
  });

  it('carries no token field', () => {
    expect(chatHtml('x', 'y')).not.toMatch(/X-Token|EDP8_TOKEN/);
  });
});
