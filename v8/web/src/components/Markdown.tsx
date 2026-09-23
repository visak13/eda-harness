import { useMemo } from "react";
import DOMPurify from "dompurify";
import { useNavigate } from "react-router";
import styles from "./Markdown.module.css";

// Server-rendered doc HTML (views.render_markdown) is sanitised AGAIN in the browser before it
// is injected — defence in depth, and the criterion (c-d2dbb34b06) requires the client to strip
// an injected <script>/onerror from a hostile fixture. dangerouslySetInnerHTML is the only way
// to render server HTML; DOMPurify.sanitize is what makes it safe (strategy_ll §7).
/** Demote every body heading one level (h1→h2 … h5→h6): the page's <h1> is the doc TITLE, and a
 *  body that opens with `# Heading` must not render a second h1 (axe page-has-heading-one / the
 *  fidelity spec's single `main h1`). Runs on the sanitised HTML, so it can only ever shrink it. */
export function demoteHeadings(html: string): string {
  if (typeof DOMParser === "undefined") return html;
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  for (let level = 5; level >= 1; level--) {
    for (const el of Array.from(doc.body.querySelectorAll(`h${level}`))) {
      const next = doc.createElement(`h${level + 1}`);
      for (const { name, value } of Array.from(el.attributes)) next.setAttribute(name, value);
      while (el.firstChild) next.appendChild(el.firstChild);
      el.replaceWith(next);
    }
  }
  return doc.body.innerHTML;
}

export function Markdown({ html, className }: { html: string; className?: string }): React.JSX.Element {
  // React 19 re-applies innerHTML whenever the dangerouslySetInnerHTML OBJECT changes identity —
  // a fresh `{ __html }` per render would rebuild the body's DOM on every parent re-render and
  // detach whatever the reader had (a link mid-click, a selection). Memoise on the sanitised
  // string so the body's nodes survive re-renders (qa finding while pinning doc versions, 2026-09-10).
  const inner = useMemo(() => ({ __html: demoteHeadings(DOMPurify.sanitize(html)) }), [html]);
  return (
    <div
      className={`${styles.docMd} doc-md ${className ?? ""}`}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={inner}
    />
  );
}

const LINKABLE = /(art-[0-9a-f]{6,}|https?:\/\/[^\s<>"']+)/g;

/** A same-origin in-app URL loses its `token` query in the DOM href (qa S17): copy-link, Ctrl-click and
 *  middle-click read the href, not the click handler. Other URLs are left as typed. */
function stripToken(raw: string): string {
  try {
    const url = new URL(raw, window.location.href);
    if (url.origin === window.location.origin && url.searchParams.has("token")) { url.searchParams.delete("token"); return url.toString(); }
  } catch { /* leave malformed input as typed */ }
  return raw;
}

/** Post-process a sanitised message body (S17 c-b1f32f8b33): drop the artifact tokens the attachment
 *  cards already render, and turn bare URLs / `art-…` tokens in TEXT nodes (never inside a link or
 *  code) into links — the plain-text thread linked them, Markdown alone would not. Only builds
 *  <a href> with http(s) or an in-app /artifact/ path, so it cannot widen what DOMPurify allowed. */
export function linkifyMessageHtml(html: string, strip: string[] = []): string {
  if (typeof DOMParser === "undefined") return html;
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n as Text);
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  for (const node of nodes) {
    let text = node.data;
    for (const id of strip) if (id) text = text.split(id).join("");
    if (text !== node.data) node.data = text;
    if (node.parentElement?.closest("a, code, pre")) continue;
    const parts = text.split(LINKABLE);
    if (parts.length === 1) continue;
    const frag = doc.createDocumentFragment();
    parts.forEach((p, i) => {
      if (i % 2 === 0) { if (p) frag.appendChild(doc.createTextNode(p)); return; }
      const a = doc.createElement("a");
      if (p.startsWith("art-")) { a.setAttribute("href", `${base}/artifact/${encodeURIComponent(p)}`); a.setAttribute("data-testid", "artifact-link"); }
      else { a.setAttribute("href", stripToken(p)); a.setAttribute("rel", "noopener noreferrer"); }
      a.textContent = p;
      frag.appendChild(a);
    });
    node.replaceWith(frag);
  }
  return doc.body.innerHTML;
}

/** A thread message rendered from the board's `html` (views.render_message_markdown: the docs'
 *  renderer and allowlist, raw HTML escaped), sanitised AGAIN here like every doc body. Same-origin
 *  in-app links route inside the SPA (no reload, draft kept); external links open a new tab. */
export function MessageMarkdown({ html, strip, className }: { html: string; strip?: string[]; className?: string }): React.JSX.Element {
  const navigate = useNavigate();
  const key = strip?.join(",") ?? "";
  const inner = useMemo(() => ({ __html: linkifyMessageHtml(demoteHeadings(DOMPurify.sanitize(html)), key ? key.split(",") : []) }), [html, key]);
  function onClick(e: React.MouseEvent<HTMLDivElement>) {
    const a = (e.target as HTMLElement).closest("a");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    let url: URL;
    try { url = new URL(a.getAttribute("href") ?? "", window.location.href); } catch { return; }
    const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
    if (url.origin === window.location.origin && url.pathname.startsWith(`${base}/`) && /\/(artifact|doc|epic|ticket)\//.test(url.pathname)) {
      e.preventDefault();
      url.searchParams.delete("token");
      navigate(`${url.pathname.slice(base.length)}${url.search}${url.hash}`);
    } else if (url.origin !== window.location.origin) {
      a.setAttribute("target", "_blank");
    }
  }
  return (
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
    <div className={`${styles.docMd} ${styles.chatMd} ${className ?? ""}`} data-testid="message-md" onClick={onClick}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={inner} />
  );
}
