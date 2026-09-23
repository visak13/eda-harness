import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { approveDoc, createLink, deleteLink, getDoc, getDocDiff, rejectDoc, updateDoc } from "../api/endpoints";
import type { BoardApiError } from "../api/client";
import type { KnowledgeDoc, KnowledgeView } from "../api/types";
import { useDocDrawer } from "../components/DocDrawer";
import ui from "../components/ui.module.css";
import { KIND_LABEL, StatusWord } from "./knowledgeShared";
import styles from "./Knowledge.module.css";

// One knowledge doc: meta + provenance, Read (the doc drawer), Edit (title/body/tags → the board
// writes a new version), a proposal's diff against the active version with Approve / Reject, and
// the epics it is linked to with Unlink + Link to an epic (uses_domain for a domain doc, else
// uses_strategy). Every write invalidates ["knowledge"] and the epic pages so the change shows at once.

export function parseTags(s: string): string[] {
  return s.split(/[,\s]+/).map((t) => t.trim().toLowerCase()).filter(Boolean);
}

function errText(e: unknown): string | null {
  if (!e) return null;
  const b = e as BoardApiError;
  return b.hint || b.message;
}

export function DiffView({ diff, titleFrom, titleTo }: {
  diff: string; titleFrom?: string | null; titleTo?: string;
}): React.JSX.Element {
  // approval overwrites the active title too, so a title change is shown even when the body is equal
  const title = titleFrom != null && titleTo !== undefined && titleFrom !== titleTo ? (
    <p className={styles.muted} data-testid="knowledge-title-change">Title: “{titleFrom}” → “{titleTo}”</p>
  ) : null;
  if (!diff) return <>{title}<p className={styles.muted}>{title ? "The body is unchanged." : "No change against the active version."}</p></>;
  return (
    <>{title}<pre className={styles.diff} data-testid="knowledge-diff" aria-label="Changes against the active version">
      {diff.split("\n").map((line, i) => {
        const cls = line.startsWith("+") && !line.startsWith("+++") ? styles.diffAdd
          : line.startsWith("-") && !line.startsWith("---") ? styles.diffDel : styles.diffCtx;
        const word = cls === styles.diffAdd ? "added: " : cls === styles.diffDel ? "removed: " : "";
        return <span key={i} className={cls}><span className="srOnly">{word}</span>{line || " "}</span>;
      })}
    </pre></>
  );
}

export function KnowledgeDetail({ doc, epics, onClose }: {
  doc: KnowledgeDoc; epics: KnowledgeView["epics"]; onClose: () => void;
}): React.JSX.Element {
  const qc = useQueryClient();
  const drawer = useDocDrawer();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["knowledge"] });
    void qc.invalidateQueries({ queryKey: ["epic"] });
    void qc.invalidateQueries({ queryKey: ["doc", doc.id] });
  };
  const [editing, setEditing] = useState(false);
  const [epicPick, setEpicPick] = useState("");
  const relation = doc.doc_type === "domain" ? "uses_domain" : "uses_strategy";

  const diff = useQuery({ queryKey: ["doc", doc.id, "diff"], queryFn: () => getDocDiff(doc.id), enabled: doc.status === "proposed" });
  const approve = useMutation({ mutationFn: () => approveDoc(doc.id), onSuccess: refresh });
  const reject = useMutation({ mutationFn: () => rejectDoc(doc.id), onSuccess: refresh });
  const link = useMutation({
    mutationFn: () => createLink({ from_id: epicPick, to_id: doc.id, relation }),
    onSuccess: () => { setEpicPick(""); refresh(); },
  });
  const unlink = useMutation({ mutationFn: (linkId: string) => deleteLink(linkId), onSuccess: refresh });
  const linkedIds = new Set(doc.linked.map((l) => l.ticket_id));
  const error = errText(approve.error ?? reject.error ?? link.error ?? unlink.error);

  return (
    <aside className={styles.detail} aria-label={`Knowledge doc ${doc.title}`} data-testid="knowledge-detail">
      <h2 className={styles.detailTitle}>{doc.title}</h2>
      <p className={styles.muted}>
        <span className={ui.tag}>{KIND_LABEL[doc.doc_type] ?? doc.doc_type}</span> <StatusWord status={doc.status} /> ·
        v{doc.version} · {doc.id} · by {doc.created_by}
      </p>
      <p className={styles.muted} data-testid="knowledge-tags">Tags: {doc.tags.length ? doc.tags.join(", ") : "none"}</p>
      {doc.source_url ? <p className={styles.muted}>Imported from <a href={doc.source_url} target="_blank" rel="noreferrer">{doc.source_url}</a></p> : null}
      {doc.source ? (
        <p className={styles.muted} data-testid="knowledge-source">
          Proposed by {doc.source.participant}
          {doc.source.ticket ? <> on <Link to={`/ticket/${encodeURIComponent(doc.source.ticket)}`}>{doc.source.ticket}</Link></> : null}
          {doc.proposes ? <> as the next version of {doc.proposes}</> : " as a new doc"}
        </p>
      ) : null}
      {doc.resolution ? <p className={styles.muted}>Resolution: {doc.resolution}</p> : null}
      <div className={styles.actions}>
        <button type="button" className={ui.button} onClick={() => drawer.openDoc(doc.id)} data-testid="knowledge-read">Read</button>
        {doc.status !== "retired" ? (
          <button type="button" className={ui.button} onClick={() => setEditing((v) => !v)} aria-expanded={editing}
            data-testid="knowledge-edit">{editing ? "Close editor" : "Edit"}</button>
        ) : null}
        <button type="button" className={ui.button} onClick={onClose}>Close</button>
      </div>
      {editing ? <KnowledgeEditor doc={doc} onSaved={() => { setEditing(false); refresh(); }} /> : null}

      {doc.status === "proposed" ? (
        <section aria-label="Proposal">
          <div className={ui.sectionLabel}>
            {doc.proposes ? `Changes against the active version of ${doc.proposes}` : "A new doc (no active version)"}
          </div>
          {diff.isPending ? <p className={styles.muted}>Loading the diff…</p> : null}
          {diff.isError ? <p className={ui.banner} role="alert">{errText(diff.error)}</p> : null}
          {diff.data ? <DiffView diff={diff.data.diff} titleFrom={diff.data.title_changed ? diff.data.base_title : null} titleTo={diff.data.title} /> : null}
          <div className={styles.actions}>
            <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={approve.isPending || reject.isPending}
              onClick={() => approve.mutate()} data-testid="knowledge-approve">
              {doc.proposes ? "Approve — becomes the next version" : "Approve — becomes active"}
            </button>
            <button type="button" className={`${ui.button} ${ui.buttonFail}`} disabled={approve.isPending || reject.isPending}
              onClick={() => reject.mutate()} data-testid="knowledge-reject">Reject — retire it</button>
          </div>
        </section>
      ) : null}

      {doc.status === "active" ? (
        <section aria-label="Linked epics">
          <div className={ui.sectionLabel}>Linked to ({doc.linked.length})</div>
          {doc.linked.length === 0 ? <p className={styles.muted}>No epic uses it yet.</p> : (
            <ul className={styles.linked} data-testid="knowledge-linked">
              {doc.linked.map((l) => (
                <li key={l.link_id} className={styles.linkedRow}>
                  <span className={ui.tag}>{l.kind}</span>
                  <Link className={styles.linkedTitle} to={`/${l.kind === "epic" ? "epic" : "ticket"}/${encodeURIComponent(l.ticket_id)}`}>
                    {l.title}
                  </Link>
                  <button type="button" className={ui.button} disabled={unlink.isPending}
                    onClick={() => unlink.mutate(l.link_id)} data-testid="knowledge-unlink">Unlink</button>
                </li>
              ))}
            </ul>
          )}
          <form className={styles.linkForm} onSubmit={(e) => { e.preventDefault(); if (epicPick) link.mutate(); }}>
            <select className={ui.select} aria-label="Epic to link" value={epicPick} onChange={(e) => setEpicPick(e.target.value)}
              data-testid="knowledge-link-epic">
              <option value="">Choose an epic…</option>
              {epics.filter((e) => !linkedIds.has(e.id)).map((e) => (
                <option key={e.id} value={e.id}>{e.title} ({e.status.replace(/_/g, " ")})</option>
              ))}
            </select>
            <button type="submit" className={ui.button} disabled={!epicPick || link.isPending} data-testid="knowledge-link">
              Link to epic
            </button>
          </form>
          <p className={styles.muted}>Linked docs appear in that epic's briefs as one index line, read on demand.</p>
        </section>
      ) : null}
      {error ? <p className={ui.banner} role="alert" data-testid="knowledge-error">{error}</p> : null}
    </aside>
  );
}

function KnowledgeEditor({ doc, onSaved }: { doc: KnowledgeDoc; onSaved: () => void }): React.JSX.Element {
  const full = useQuery({ queryKey: ["doc", doc.id, "record"], queryFn: () => getDoc(doc.id) });
  const [title, setTitle] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [tags, setTags] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => updateDoc(doc.id, {
      title: title ?? undefined, body_md: body ?? undefined, tags: tags === null ? undefined : parseTags(tags),
    }),
    onSuccess: onSaved,
  });
  if (full.isPending) return <p className={styles.muted}>Loading the doc…</p>;
  if (full.isError) return <p className={ui.banner} role="alert">{errText(full.error)}</p>;
  const changed = title !== null || body !== null || tags !== null;
  return (
    <form className={styles.editor} onSubmit={(e) => { e.preventDefault(); if (changed) save.mutate(); }}
      data-testid="knowledge-editor">
      <label className={ui.sectionLabel} htmlFor="kd-title">Title</label>
      <input id="kd-title" className={ui.input} value={title ?? full.data.title} onChange={(e) => setTitle(e.target.value)} />
      <label className={ui.sectionLabel} htmlFor="kd-tags">Tags (comma or space separated)</label>
      <input id="kd-tags" className={ui.input} value={tags ?? (full.data.tags ?? []).join(", ")}
        onChange={(e) => setTags(e.target.value)} data-testid="knowledge-edit-tags" />
      <label className={ui.sectionLabel} htmlFor="kd-body">Body (markdown)</label>
      <textarea id="kd-body" className={ui.textarea} rows={14} value={body ?? full.data.body_md}
        onChange={(e) => setBody(e.target.value)} data-testid="knowledge-edit-body" />
      {save.isError ? <p className={ui.banner} role="alert">{errText(save.error)}</p> : null}
      <div className={styles.actions}>
        <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!changed || save.isPending}
          data-testid="knowledge-save">{save.isPending ? "Saving…" : `Save as v${doc.version + 1}`}</button>
      </div>
    </form>
  );
}
