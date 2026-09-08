import DOMPurify from "dompurify";
import styles from "./Markdown.module.css";

// Server-rendered doc HTML (views.render_markdown) is sanitised AGAIN in the browser before it
// is injected — defence in depth, and the criterion (c-d2dbb34b06) requires the client to strip
// an injected <script>/onerror from a hostile fixture. dangerouslySetInnerHTML is the only way
// to render server HTML; DOMPurify.sanitize is what makes it safe (strategy_ll §7).
export function Markdown({ html, className }: { html: string; className?: string }): React.JSX.Element {
  const clean = DOMPurify.sanitize(html);
  return (
    <div
      className={`${styles.docMd} doc-md ${className ?? ""}`}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: clean }}
    />
  );
}
