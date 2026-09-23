import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getTopics, openTopic } from "../api/endpoints";
import type { BoardApiError } from "../api/client";
import ui from "../components/ui.module.css";
import dialogStyles from "../components/NewEpicDialog.module.css";
import { useModalDialog } from "../components/useModalDialog";
import { parseTags } from "./KnowledgeDetail";
import styles from "./Topics.module.css";

// S-SME-SURFACE (s-698224fca8): Library topics — the owner's standing subjects, each with a resident sme
// seat, its own docs, thread, tags and named human experts. The list sits beside Knowledge; the topic
// page is TopicPage (./TopicPage.tsx).

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

export function OpenTopicDialog({ open, onClose, onOpened }: {
  open: boolean; onClose: () => void; onOpened: (id: string) => void;
}): React.JSX.Element | null {
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [seed, setSeed] = useState("");
  const panelRef = useRef<HTMLFormElement>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const qc = useQueryClient();
  useModalDialog(open, panelRef, firstRef, busy, onClose);
  const run = useMutation({
    mutationFn: () => openTopic({ title: title.trim(), tags: parseTags(tags), seed_url: seed.trim() || null }),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ["topics"] });
      setTitle(""); setTags(""); setSeed("");
      onClose();
      onOpened(res.value.topic.id);
    },
    onSettled: () => { busy.current = false; },
  });
  if (!open) return null;
  const seedOk = !seed.trim() || /^https:\/\/\S+$/.test(seed.trim());
  const ready = Boolean(title.trim()) && seedOk;
  return createPortal(
    <div className={dialogStyles.scrim} onMouseDown={(e) => e.target === e.currentTarget && !busy.current && onClose()}>
      <form className={dialogStyles.dialog} ref={panelRef} role="dialog" aria-modal="true" aria-label="Open topic"
        data-testid="topic-open-dialog"
        onSubmit={(e) => { e.preventDefault(); if (ready && !busy.current) { busy.current = true; run.mutate(); } }}>
        <h2 className={dialogStyles.title}>Open topic</h2>
        <label className={ui.sectionLabel} htmlFor="tp-title">Title</label>
        <input id="tp-title" ref={firstRef} className={ui.input} value={title} maxLength={80}
          onChange={(e) => setTitle(e.target.value)} data-testid="topic-open-title" />
        <label className={ui.sectionLabel} htmlFor="tp-tags">Tags (optional; the sme adds its own)</label>
        <input id="tp-tags" className={ui.input} value={tags} onChange={(e) => setTags(e.target.value)}
          placeholder="python, testing" data-testid="topic-open-tags" />
        <label className={ui.sectionLabel} htmlFor="tp-seed">Seed URL (optional)</label>
        <input id="tp-seed" className={ui.input} value={seed} onChange={(e) => setSeed(e.target.value)}
          placeholder="https://docs.pytest.org/en/stable/" data-testid="topic-open-seed" />
        <p className={dialogStyles.muted}>
          The sme reads skills.sh, GitHub skill files and pages on the seed URL's site, and nothing else. It proposes
          docs; you approve them in Knowledge. It stays on the topic until you close it.
        </p>
        {!seedOk ? <p className={ui.banner} role="alert">The seed URL must start with https://</p> : null}
        {run.isError ? <p className={ui.banner} role="alert">{errText(run.error)}</p> : null}
        <div className={dialogStyles.actions}>
          <button type="button" className={ui.button} onClick={onClose} disabled={run.isPending}>Cancel</button>
          <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!ready || run.isPending}
            data-testid="topic-open-create">{run.isPending ? "Opening…" : "Open"}</button>
        </div>
      </form>
    </div>, document.body,
  );
}

export const when = (iso: string | null | undefined): string => (iso ? iso.slice(0, 16).replace("T", " ") : "");
