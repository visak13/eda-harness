import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getConversations } from "../api/endpoints";
import { scopePath, type Attention } from "../api/attention";
import { AttentionDot } from "./AttentionDot";
import styles from "./WaitingOnYou.module.css";

// S20 (design-e963c656f5 §4.18): the rail count opens this popover in place of the retired Needs you page — one line
// per epic, quick task, topic or Admin that waits on the viewer, with its reason, each opening the page where the
// dots continue. Architect ruling m-e972777a3d: the page's Conversations panel moved here as a footer (last 5).

function threadPath(id: string, epicId: string | null): string {
  if (id.startsWith("topic-")) return `/library/topics/${encodeURIComponent(id)}`;
  return `/${epicId === id ? "epic" : "ticket"}/${encodeURIComponent(id)}`;
}

export function WaitingOnYou({ attention, onPick }: { attention: Attention; onPick: () => void }): React.JSX.Element {
  const convos = useQuery({ queryKey: ["me", "conversations"], queryFn: getConversations, retry: false });
  const recent = (convos.data ?? []).slice(0, 5);
  return (
    <div className={styles.body} data-testid="waiting-on-you">
      {attention.scopes.length ? (
        <ul className={styles.list}>
          {attention.scopes.map((s) => (
            <li key={s.id}>
              <Link to={scopePath(s)} className={styles.row} onClick={onPick} data-testid="waiting-row" data-attention="true">
                <span className={styles.main}>
                  <span className={styles.kind}>{s.type === "quick" ? "quick task" : s.type}</span>
                  <span className={styles.title}>{s.title}</span>
                  <span className={styles.reason} data-testid="waiting-reason">{s.reason}</span>
                </span>
                <AttentionDot count={s.count} />
              </Link>
            </li>
          ))}
        </ul>
      ) : <p className={styles.empty} data-testid="waiting-empty">Nothing is waiting on you.</p>}
      {recent.length ? (
        <section className={styles.footer} aria-label="Recent conversations" data-testid="recent-conversations">
          <h3 className={styles.footerTitle}>Recent conversations</h3>
          <ul className={styles.list}>
            {recent.map((c) => (
              <li key={c.ticket_id}>
                <Link to={threadPath(c.ticket_id, c.epic_id)} className={styles.convo} onClick={onPick}>
                  <span className={styles.title}>{c.title}</span>
                  {c.last ? <span className={styles.reason}>{c.last.by}: {c.last.text}</span> : null}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
