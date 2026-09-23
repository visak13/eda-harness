import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getTopics } from "../api/endpoints";
import type { BoardApiError } from "../api/client";
import ui from "../components/ui.module.css";
import { OpenTopicDialog } from "../components/OpenTopicDialog";
import styles from "./Topics.module.css";

// S-SME-SURFACE (s-698224fca8): Library topics — the owner's standing subjects, each with a resident sme
// seat, its own docs, thread, tags and named human experts. The list sits beside Knowledge; the topic
// page is TopicPage (./TopicPage.tsx); the Open-topic dialog is components/OpenTopicDialog.tsx (t-f5bf848f0f).

export { OpenTopicDialog };

export function errText(e: unknown): string | null {
  if (!e) return null;
  const b = e as BoardApiError;
  return b.hint || b.message;
}

export function TopicsSection(): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [params] = useSearchParams();
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["topics"], queryFn: getTopics });
  return (
    <div data-testid="topics">
      <div className={styles.bar}>
        <p className={styles.muted}>
          A topic is a subject you keep: its sme researches skills.sh and your seed site, proposes docs for you to
          approve, and answers you and the experts you add.
        </p>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} onClick={() => setOpen(true)}
          data-testid="topic-open-button">Open topic</button>
      </div>
      {q.isPending ? <p className={ui.empty}>Loading…</p>
        : q.isError ? <p className={ui.banner} role="alert">{errText(q.error)}</p>
          : q.data.length === 0 ? <p className={ui.empty}>No topics yet.</p> : (
            <ul className={styles.list} data-testid="topic-list">
              {q.data.map((t) => (
                <li key={t.id}>
                  <Link className={styles.row} to={`/library/topics/${t.id}${suffix}`} data-testid="topic-row">
                    <span className={ui.tag}>{t.status}</span>
                    <span className={styles.rowTitle}>{t.title}</span>
                    <span className={styles.tags}>{t.tags.map((g) => <span key={g} className={ui.tag}>{g}</span>)}</span>
                    <span className={styles.muted}>
                      {t.docs} docs · {t.experts} experts · {t.messages} messages · seat {t.seat.state}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
      <OpenTopicDialog open={open} onClose={() => setOpen(false)}
        onOpened={(id) => navigate(`/library/topics/${id}${suffix}`)} />
    </div>
  );
}

export const when = (iso: string | null | undefined): string => (iso ? iso.slice(0, 16).replace("T", " ") : "");
