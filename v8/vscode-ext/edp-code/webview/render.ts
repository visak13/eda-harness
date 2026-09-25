// Message bodies (strategyll-1a201146c8 §2, design R7): agent text is untrusted. markdown-it with raw
// HTML off, then DOMPurify with a closed tag list and an http(s)-only URI rule. One renderer for the
// history AND the live path (the board's thread `html` field is ignored, so both paths are identical).
// `@handle` highlighting runs on text nodes of the sanitised DOM, never on the HTML string.
import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';
import { mentionSpans } from '../src/core/mentions';
import { kindLabel, splitRefs, type RefPart } from '../src/core/boardRefs';

const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
const TAGS = ['p', 'br', 'hr', 'blockquote', 'pre', 'code', 'strong', 'em', 'del', 's', 'a', 'ul', 'ol', 'li',
  'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'];

export function renderBody(text: string): string {
  return DOMPurify.sanitize(md.render(text), {
    ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ['href', 'title', 'class'], ALLOWED_URI_REGEXP: /^https?:/i,
  });
}

/** C24: a `$<id>` reference as a chip button (its label, or the id); a click posts `openRef` (onRefClick). */
export function refChip(doc: Document, r: Exclude<RefPart, string>): HTMLButtonElement {
  const b = doc.createElement('button');
  b.type = 'button';
  b.className = 'ref-chip';
  b.dataset.ref = r.id;
  b.dataset.kind = r.kind;
  b.title = `${kindLabel(r.kind)} $${r.id}`;
  b.textContent = r.label ? `${kindLabel(r.kind)} · ${r.label}` : `$${r.id}`;
  return b;
}

/** Plain text with its `$<id>` references as chips (a quote's note). */
export function refFragment(doc: Document, text: string): DocumentFragment {
  const frag = doc.createDocumentFragment();
  for (const p of splitRefs(text)) frag.append(typeof p === 'string' ? doc.createTextNode(p) : refChip(doc, p));
  return frag;
}

/** The sanitised body as a fragment, with @handles wrapped in `span.mention` (known handles get
 *  `known`) and C24's `$<id>` references as chips. Text inside <code>/<pre>/<a> is left alone, as the
 *  tokenisers skip code. */
export function bodyFragment(doc: Document, text: string, known: ReadonlySet<string>): DocumentFragment {
  const tpl = doc.createElement('template');
  tpl.innerHTML = renderBody(text);
  const walker = doc.createTreeWalker(tpl.content, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!(n.parentElement?.closest('code,pre,a'))) nodes.push(n as Text);
  }
  for (const node of nodes) {
    const refs = splitRefs(node.data);
    if (refs.length === 1 && typeof refs[0] === 'string' && !mentionSpans(node.data).length) continue;
    const frag = doc.createDocumentFragment();
    for (const r of refs) {
      if (typeof r !== 'string') { frag.append(refChip(doc, r)); continue; }
      let at = 0;
      for (const sp of mentionSpans(r)) {
        if (sp.start > at) frag.append(r.slice(at, sp.start));
        const el = doc.createElement('span');
        el.className = known.has(sp.handle) ? 'mention known' : 'mention';
        el.textContent = r.slice(sp.start, sp.end);
        frag.append(el);
        at = sp.end;
      }
      if (at < r.length) frag.append(r.slice(at));
    }
    node.replaceWith(frag);
  }
  // links open through the webview runtime (the host routes http/https externally)
  tpl.content.querySelectorAll('a').forEach(a => a.setAttribute('rel', 'noreferrer noopener'));
  return tpl.content;
}
