// The chat webview document (strategyll-5e3ecdb625 §1, C1-measured): the bundled JS and CSS are
// INLINED as one nonce'd <script> and one nonce'd <style>; nothing is fetched after the HTML (Firefox
// code-server#7913 fails every vscode-resource URI). A fresh node:crypto nonce per resolve.
import { randomBytes } from 'node:crypto';

export const cspFor = (nonce: string) =>
  `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; img-src data:; form-action 'none'; base-uri 'none'`;

export function chatHtml(js: string, css: string, nonce = randomBytes(16).toString('base64')): string {
  // `</script` inside the bundle would end the element early; `</style` likewise for the CSS
  const safeJs = js.replace(/<\/script/gi, '<\\/script');
  const safeCss = css.replace(/<\/style/gi, '<\\/style');
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${cspFor(nonce)}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EDP Chat</title>
<style nonce="${nonce}">${safeCss}</style></head><body><div id="app"></div>
<script nonce="${nonce}">${safeJs}</script></body></html>`;
}
