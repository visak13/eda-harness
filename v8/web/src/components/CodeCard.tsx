import { Link } from "react-router";
import type { CodeContext } from "../api/types";
import { Icon } from "./Icon";
import styles from "./Conversation.module.css";

// epic-91fcd3b370 S4: a message tagged from the Code tab carries a code anchor; the ticket page shows
// it as a card (path, lines, short sha, snippet) with an "Open in Code" deep link. The snippet is a
// React text node inside <pre><code> — never HTML — so `<script>` in code stays literal text.

/** The Code tab deep link (design-449b628cdd §4): /code?folder=<abs>&file=<rel>&line=<n>[-<m>]; a
 *  multi-line anchor carries its range (S3 parses it in pages/codeLink.ts). */
export function codeHref(c: CodeContext): string {
  const line = c.line_end > c.line_start ? `${c.line_start}-${c.line_end}` : String(c.line_start);
  const q = new URLSearchParams({ folder: c.repo_root, file: c.path, line });
  return `/code?${q.toString()}`;
}

export function CodeCard({ c }: { c: CodeContext }): React.JSX.Element {
  const lines = c.line_start === c.line_end ? `L${c.line_start}` : `L${c.line_start}–${c.line_end}`;
  return (
    <figure className={styles.codeCard} data-testid="code-card">
      <figcaption className={styles.codeHead}>
        <span className={styles.codePath} data-testid="code-path" title={`${c.repo_root}/${c.path}`}>{c.path}</span>
        <span data-testid="code-lines">{lines}</span>
        {c.commit
          ? <span className={styles.codeSha} data-testid="code-sha" title={c.commit}>{c.commit.slice(0, 7)}</span>
          : <span className={styles.codeSha} data-testid="code-sha">no git</span>}
        {c.commit && c.dirty ? <span className={styles.codeDirty} title="uncommitted changes when tagged">dirty</span> : null}
        <Link to={codeHref(c)} className={styles.codeOpen} data-testid="code-open">
          <Icon name="external" size={16} /> Open in Code
        </Link>
      </figcaption>
      <pre className={styles.codeSnippet} data-testid="code-snippet"><code>{c.snippet}</code></pre>
    </figure>
  );
}
