import { useMemo } from "react";
import DOMPurify from "dompurify";
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
