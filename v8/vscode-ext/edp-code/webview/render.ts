// Message bodies (strategyll-1a201146c8 §2, design R7): agent text is untrusted. markdown-it with raw
// HTML off, then DOMPurify with a closed tag list and an http(s)-only URI rule. One renderer for the
// history AND the live path (the board's thread `html` field is ignored, so both paths are identical).
// `@handle` highlighting runs on text nodes of the sanitised DOM, never on the HTML string.
import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';
import { mentionSpans } from '../src/core/mentions';

const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
const TAGS = ['p', 'br', 'hr', 'blockquote', 'pre', 'code', 'strong', 'em', 'del', 's', 'a', 'ul', 'ol', 'li',
  'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'];

export function renderBody(text: string): string {
  return DOMPurify.sanitize(md.render(text), {
    ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ['href', 'title', 'class'], ALLOWED_URI_REGEXP: /^https?:/i,
  });
}

/** The sanitised body as a fragment, with @handles wrapped in `span.mention` (known handles get
 *  `known`). Text inside <code>/<pre>/<a> is left alone, as the tokeniser skips code. */
export function bodyFragment(doc: Document, text: string, known: ReadonlySet<string>): DocumentFragment {
  const tpl = doc.createElement('template');
  tpl.innerHTML = renderBody(text);
  const walker = doc.createTreeWalker(tpl.content, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!(n.parentElement?.closest('code,pre,a'))) nodes.push(n as Text);
  }
  for (const node of nodes) {
    const s = node.data;
    const spans = mentionSpans(s);
    if (!spans.length) continue;
    const frag = doc.createDocumentFragment();
    let at = 0;
    for (const sp of spans) {
      if (sp.start > at) frag.append(s.slice(at, sp.start));
      const el = doc.createElement('span');
      el.className = known.has(sp.handle) ? 'mention known' : 'mention';
      el.textContent = s.slice(sp.start, sp.end);
      frag.append(el);
      at = sp.end;
    }
    if (at < s.length) frag.append(s.slice(at));
    node.replaceWith(frag);
  }
  // links open through the webview runtime (the host routes http/https externally)
  tpl.content.querySelectorAll('a').forEach(a => a.setAttribute('rel', 'noreferrer noopener'));
  return tpl.content;
}
