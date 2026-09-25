// C19 (design-10b21760d9 §14.5): map a selection made in RENDERED markdown back to its SOURCE.
// The board (C18, edp8/quotes.py) verifies a quote's `text` as a whitespace-normalised substring of
// the source (a doc version's body_md lines, a message's text), so a quote of "**bold** words" must
// carry the markdown, not the "bold words" the reader selected. Both sides are projected onto their
// "significant" characters (no whitespace, no inline markdown syntax, no link targets, no line-level
// markers) with an index map back into the source; the selection is found in the source projection
// and the hit becomes the verbatim source slice the board can verify. Pure: no DOM, no React.

/** Characters markdown uses as syntax (or a renderer drops); ignored on BOTH sides of a match. */
const SYNTAX = new Set(["*", "_", "~", "`", "#", ">", "<", "|", "[", "]", "(", ")", "!", "\\"]);

export interface Projection {
  /** The significant characters, in order. */
  chars: string;
  /** For each char of `chars`, its index in the source string. */
  at: number[];
}

function significant(ch: string): boolean {
  return !/\s/.test(ch) && !SYNTAX.has(ch);
}

/** Project arbitrary (rendered/selected) text: every significant character, source index kept. */
export function projectPlain(text: string): Projection {
  const chars: string[] = [];
  const at: number[] = [];
  for (let i = 0; i < text.length; i++) {
    if (significant(text[i])) { chars.push(text[i]); at.push(i); }
  }
  return { chars: chars.join(""), at };
}

// Line-level markers a renderer turns into structure (never into selectable text).
const LINE_MARKER = /^(\s{0,3}(?:>\s?)*)\s*(?:#{1,6}\s+|(?:\d{1,9}[.)]|[-*+])\s+(?:\[[ xX]\]\s+)?)?/;
const FENCE = /^\s{0,3}(```|~~~)/;
const RULE = /^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const HTML_ENTITY: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": "\"", "&#39;": "'", "&nbsp;": " " };

/** Project markdown source: drops fence lines, rules, table separator rows, line markers (heading
 *  #s, quote >, list bullets/numbers, task boxes), link/image targets `](…)`, backslash escapes and
 *  inline syntax. An HTML entity projects as the character it renders. */
export function projectMarkdown(src: string): Projection {
  const chars: string[] = [];
  const at: number[] = [];
  let lineStart = 0;
  while (lineStart <= src.length) {
    let lineEnd = src.indexOf("\n", lineStart);
    if (lineEnd === -1) lineEnd = src.length;
    const line = src.slice(lineStart, lineEnd);
    if (!(FENCE.test(line) || RULE.test(line) || TABLE_SEP.test(line))) {
      const marker = LINE_MARKER.exec(line)?.[0].length ?? 0;
      let i = marker;
      while (i < line.length) {
        const ch = line[i];
        if (ch === "]" && line[i + 1] === "(") { // a link/image target is not rendered text
          const close = line.indexOf(")", i + 2);
          if (close !== -1) { i = close + 1; continue; }
        }
        if (ch === "\\" && i + 1 < line.length && /[!-/:-@[-`{-~]/.test(line[i + 1])) {
          const esc = line[i + 1]; // an escaped char renders literally: keep it if significant
          if (significant(esc)) { chars.push(esc); at.push(lineStart + i + 1); }
          i += 2; continue;
        }
        if (ch === "&") {
          const m = /^&(?:amp|lt|gt|quot|#39|nbsp);/.exec(line.slice(i));
          if (m) {
            const out = HTML_ENTITY[m[0]];
            if (significant(out)) { chars.push(out); at.push(lineStart + i); }
            i += m[0].length; continue;
          }
        }
        if (significant(ch)) { chars.push(ch); at.push(lineStart + i); }
        i++;
      }
    }
    lineStart = lineEnd + 1;
  }
  return { chars: chars.join(""), at };
}

function allStarts(hay: string, needle: string): number[] {
  const out: number[] = [];
  if (!needle) return out;
  for (let i = hay.indexOf(needle); i !== -1; i = hay.indexOf(needle, i + 1)) out.push(i);
  return out;
}

export interface SourceSpan {
  /** Source char offsets, end-exclusive. */
  start: number;
  end: number;
  /** The verbatim source slice (what the board verifies). */
  text: string;
}

/** Where the rendered `selected` text sits in markdown `src`. `before` is the rendered text that
 *  precedes the selection in the same region: it picks WHICH occurrence was selected when the
 *  passage repeats (the n-th in the render is the n-th in the source). Null when not found. */
export function locateInSource(src: string, selected: string, before = ""): SourceSpan | null {
  const needle = projectPlain(selected).chars;
  if (!needle) return null;
  const proj = projectMarkdown(src);
  const hits = allStarts(proj.chars, needle);
  if (!hits.length) return null;
  const rendered = projectPlain(before + selected).chars;
  const nth = Math.max(0, allStarts(rendered, needle).length - 1);
  const hit = hits[Math.min(nth, hits.length - 1)];
  const start = proj.at[hit];
  const last = proj.at[hit + needle.length - 1];
  // An entity maps to its "&"; extend the end over the whole entity so the slice stays verbatim.
  const ent = /^&(?:amp|lt|gt|quot|#39|nbsp);/.exec(src.slice(last));
  const end = last + (ent ? ent[0].length : 1);
  return { start, end, text: src.slice(start, end) };
}

/** 1-based inclusive line numbers of a source span (the board's doc locator). */
export function linesOf(src: string, span: { start: number; end: number }): { line_start: number; line_end: number } {
  const count = (s: string) => s.split("\n").length;
  return { line_start: count(src.slice(0, span.start)), line_end: count(src.slice(0, Math.max(span.start, span.end - 1)) ) };
}

/** The nearest non-blank line above/below a line range, within the board's 3-line reach, clipped to
 *  200 chars (a prefix/suffix of a line stays a substring after whitespace normalisation). */
export function contextOf(src: string, lineStart: number, lineEnd: number): { before: string; after: string } {
  const lines = src.split("\n");
  let before = "", after = "";
  for (let n = lineStart - 1; n >= Math.max(1, lineStart - 3); n--) {
    const l = lines[n - 1]?.trim();
    if (l) { before = l.length > 200 ? l.slice(-200) : l; break; }
  }
  for (let n = lineEnd + 1; n <= Math.min(lines.length, lineEnd + 3); n++) {
    const l = lines[n - 1]?.trim();
    if (l) { after = l.length > 200 ? l.slice(0, 200) : l; break; }
  }
  return { before, after };
}

/** The rendered passage of lines a..b of `src`, found in rendered `text`: a [start, end) range of
 *  `text` (the reader scrolls to it), or null. */
export function findRendered(text: string, src: string, lineStart: number, lineEnd: number): { start: number; end: number } | null {
  const lines = src.split("\n").slice(lineStart - 1, lineEnd).join("\n");
  const needle = projectMarkdown(lines).chars;
  if (!needle) return null;
  const proj = projectPlain(text);
  const hit = proj.chars.indexOf(needle);
  if (hit === -1) return null;
  return { start: proj.at[hit], end: proj.at[hit + needle.length - 1] + 1 };
}

/** UTF-8 byte length (the board caps a passage at 4096 bytes). */
export function utf8Bytes(s: string): number {
  return new TextEncoder().encode(s).length;
}

/** A verified passage as a reader sees it: the markdown source a quote carries (so the board could
 *  verify it) without its inline syntax: emphasis/code markers, link targets, line markers. Display
 *  only; the stored quote keeps the source. */
export function displayPassage(src: string): string {
  return src.split("\n").map((line) => line
    .replace(/^\s{0,3}(?:>\s?)*\s*(?:#{1,6}\s+|(?:\d{1,9}[.)]|[-*+])\s+(?:\[[ xX]\]\s+)?)?/, "")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    // an escaped char is literal text: park it in the private-use area until the syntax is gone
    .replace(/\\([!-/:-@[-`{-~])/g, (_, c: string) => String.fromCharCode(0xe000 + c.charCodeAt(0)))
    .replace(/(\*\*|__|~~|`+)/g, "")
    .replace(/(^|[^\w*])[*_]([^*_\s][^*_]*?)[*_](?=[^\w*]|$)/g, "$1$2")
    .replace(/[*_]+$|^[*_]+/g, "")
    .replace(/[-]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xe000))
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&#39;/g, "'"))
    .join("\n");
}
