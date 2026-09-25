// The reader's markdown (C16 s-579fa02cca; design §14.7): a board doc is untrusted text, rendered like a chat
// message (markdown-it html:false, then DOMPurify with a closed tag list and an http(s)-only URI rule), plus two
// things a reader needs: every block element carries its SOURCE line range (`data-ls`/`data-le`, 1-based inclusive,
// from markdown-it's token.map) so a selection maps back to lines of the markdown (C20's quote + note), and every
// heading gets a stable id for the outline.
import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';

const TAGS = ['p', 'br', 'hr', 'blockquote', 'pre', 'code', 'strong', 'em', 'del', 's', 'a', 'ul', 'ol', 'li',
  'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'];
export type Heading = { level: number; text: string; id: string; line: number };

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
// stamp source lines on every opening block token that has a map (paragraphs, headings, lists, items, tables,
// fences, blockquotes); a fence renders through its own rule, so it gets its attrs there too
// (a list's map runs through the blank line after it: trailing blank lines are not part of the block)
md.core.ruler.push('edp_lines', state => {
  const src = state.src.split('\n');
  for (const t of state.tokens) {
    if (t.map && (t.nesting === 1 || t.type === 'fence' || t.type === 'code_block' || t.type === 'hr')) {
      const ls = t.map[0] + 1;
      let le = Math.max(ls, t.map[1]);
      while (le > ls && !(src[le - 1] ?? '').trim()) le--;
      t.attrSet('data-ls', String(ls));
      t.attrSet('data-le', String(le));
    }
  }
});

/** GitHub-like slug, unique within the doc (`-1`, `-2` for repeats), prefixed so it can never clobber a DOM name. */
export function slugger(): (text: string) => string {
  const seen = new Map<string, number>(), used = new Set<string>();
  return text => {
    const base = 'h-' + (text.toLowerCase().trim().replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s+/g, '-').slice(0, 80) || 'section');
    // `A`, `A`, `A-1`: the second `A` took h-a-1, so the literal `A-1` steps on to h-a-1-1; every id is unique
    let n = seen.get(base) ?? 0, id = n ? `${base}-${n}` : base;
    while (used.has(id)) id = `${base}-${++n}`;
    seen.set(base, n + 1);
    used.add(id);
    return id;
  };
}

/** The doc as a sanitised fragment plus its outline. */
export function renderDoc(doc: Document, body: string): { frag: DocumentFragment; outline: Heading[] } {
  const env = {};
  const tokens = md.parse(body, env);
  const slug = slugger();
  const outline: Heading[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (t.type !== 'heading_open') continue;
    const text = tokens[i + 1]?.children?.map(c => c.content).join('') ?? tokens[i + 1]?.content ?? '';
    const id = slug(text);
    t.attrSet('id', id);
    outline.push({ level: Number(t.tag.slice(1)), text, id, line: (t.map?.[0] ?? 0) + 1 });
  }
  const html = md.renderer.render(tokens, md.options, env);
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ['href', 'title', 'class', 'id', 'data-ls', 'data-le', 'start'], ALLOWED_URI_REGEXP: /^https?:/i,
  });
  const tpl = doc.createElement('template');
  tpl.innerHTML = clean;
  tpl.content.querySelectorAll('a').forEach(a => a.setAttribute('rel', 'noreferrer noopener'));
  return { frag: tpl.content, outline };
}

/** The source line range a DOM range covers: from the first line of the block holding its start to the last line
 *  of the block holding its end. `null`: the selection is outside the doc's blocks. */
export function lineRange(start: Node | null, end: Node | null, root: Element): { from: number; to: number } | null {
  const block = (n: Node | null) => {
    const e = n instanceof Element ? n : n?.parentElement ?? null;
    const b = e?.closest('[data-ls]') ?? null;
    return b && root.contains(b) ? b : null;
  };
  const a = block(start), b = block(end);
  if (!a || !b) return null;
  const lines = [a, b].flatMap(x => [Number(x.getAttribute('data-ls')), Number(x.getAttribute('data-le'))]).filter(n => Number.isSafeInteger(n) && n > 0);
  if (!lines.length) return null;
  return { from: Math.min(...lines), to: Math.max(...lines) };
}

/** A unified diff (`GET /v1/docs/{id}/diff`) as lines classed add/del/hunk/meta for the reader. */
export function diffLines(text: string): { cls: 'add' | 'del' | 'hunk' | 'meta' | 'ctx'; text: string }[] {
  return text.split('\n').map(l => ({
    cls: l.startsWith('+++') || l.startsWith('---') ? 'meta' : l.startsWith('@@') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : 'ctx',
    text: l,
  }));
}
