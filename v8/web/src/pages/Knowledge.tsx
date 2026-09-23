import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getKnowledge } from "../api/endpoints";
import type { DocStatus, KnowledgeDoc, KnowledgeLesson } from "../api/types";
import { KIND_LABEL, KNOWLEDGE_KINDS, STATUS_WORD, StatusWord } from "./knowledgeShared";
import ui from "../components/ui.module.css";
import { ImportSkillDialog, NewKnowledgeDialog } from "./KnowledgeDialogs";
import { KnowledgeDetail } from "./KnowledgeDetail";
import styles from "./Knowledge.module.css";

// S-LIBRARY (design-34bf11cc07 §4.3, owner m-5b3db5cb0d "sme tab? sure"): the Library's knowledge —
// strategies, domains and lessons — as a standing shelf any epic's seats reach through their brief's
// index (never inlined). Search + kind/tag/status filters; a row opens the detail pane (read, edit
// as a new version, tags, approve/reject a proposal against its diff, link/unlink to an epic); New
// doc and Import from skills.sh add to it. The selected doc lives in `?k=` so a link reopens it.

function matchesText(needle: string, ...fields: (string | undefined | null)[]): boolean {
  return !needle || fields.some((f) => (f ?? "").toLowerCase().includes(needle));
}

export function KnowledgeSection(): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [tag, setTag] = useState("");
  const [status, setStatus] = useState<"" | DocStatus>("");
  const [dialog, setDialog] = useState<null | "new" | "import">(null);
  const query = useQuery({ queryKey: ["knowledge"], queryFn: getKnowledge });
  const selectedId = params.get("k");
  const select = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("k", id); else next.delete("k");
    setParams(next, { replace: true });
  };

  const needle = q.trim().toLowerCase();
  const docs = useMemo<KnowledgeDoc[]>(() => (query.data?.docs ?? []).filter((d) =>
    (!kind || d.doc_type === kind) && (!tag || d.tags.includes(tag)) && (!status || d.status === status) &&
    matchesText(needle, d.title, d.id, d.summary, d.tags.join(" "))), [query.data, kind, tag, status, needle]);
  const lessons = useMemo<KnowledgeLesson[]>(() => (query.data?.lessons ?? []).filter((l) =>
    (!kind || kind === "lesson") && !tag && (!status || status === "active") &&
    matchesText(needle, l.text, l.topic, l.domain)), [query.data, kind, tag, status, needle]);

  if (query.isPending) return <p className={ui.empty}>Loading…</p>;
  if (query.isError) return <p className={ui.banner} role="alert">{(query.error as Error).message}</p>;
  const data = query.data;
  const proposed = data.docs.filter((d) => d.status === "proposed").length;
  const selected = data.docs.find((d) => d.id === selectedId) ?? null;

  return (
    <section data-testid="knowledge">
      <div className={styles.tools}>
        <input className={`${ui.input} ${styles.search}`} type="search" aria-label="Search knowledge"
          placeholder="Search title, text, tag…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="knowledge-search" />
        <select className={ui.select} aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} data-testid="knowledge-kind">
          <option value="">every kind</option>
          {[...KNOWLEDGE_KINDS, "lesson"].map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
        <select className={ui.select} aria-label="Tag" value={tag} onChange={(e) => setTag(e.target.value)} data-testid="knowledge-tag">
          <option value="">any tag</option>
          {data.tags.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className={ui.select} aria-label="Status" value={status}
          onChange={(e) => setStatus(e.target.value as "" | DocStatus)} data-testid="knowledge-status-filter">
          <option value="">any status</option>
          {(["active", "proposed", "retired"] as const).map((s) => <option key={s} value={s}>{STATUS_WORD[s]}</option>)}
        </select>
        <span className={styles.spacer} />
        <button type="button" className={ui.button} onClick={() => setDialog("import")} data-testid="knowledge-import-open">
          Import from skills.sh
        </button>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} onClick={() => setDialog("new")}
          data-testid="knowledge-new-open">New doc</button>
      </div>
      {proposed > 0 ? (
        <p className={`${ui.banner} ${styles.proposedBanner}`} data-testid="knowledge-proposed-banner">
          {proposed} proposed {proposed === 1 ? "doc waits" : "docs wait"} for your approval.{" "}
          <button type="button" className={ui.button} onClick={() => setStatus("proposed")}>Show proposed</button>
        </p>
      ) : null}
      <div className={styles.layout}>
        <div>
          <div className={ui.sectionLabel}>{docs.length} {docs.length === 1 ? "doc" : "docs"} · {lessons.length} {lessons.length === 1 ? "lesson" : "lessons"}</div>
          {docs.length === 0 && lessons.length === 0 ? (
            <p className={ui.empty}>Nothing matches. Import a skill or write a doc.</p>
          ) : null}
          <ul className={styles.linked} aria-label="Knowledge docs" data-testid="knowledge-list">
            {docs.map((d) => (
              <li key={d.id}>
                <button type="button" className={`${styles.row} ${d.id === selectedId ? styles.rowSelected : ""}`}
                  aria-pressed={d.id === selectedId} onClick={() => select(d.id)} data-testid="knowledge-row">
                  <span className={ui.tag}>{KIND_LABEL[d.doc_type] ?? d.doc_type}</span>
                  <span className={styles.rowTitle}>{d.title}</span>
                  <StatusWord status={d.status} />
                  <span className={styles.rowMeta}>
                    <span>v{d.version}</span>
                    {d.tags.length ? <span>{d.tags.map((t) => `#${t}`).join(" ")}</span> : <span>untagged</span>}
                    <span>{d.linked.length ? `linked to ${d.linked.length}` : "not linked"}</span>
                  </span>
                </button>
              </li>
            ))}
            {lessons.map((l) => (
              <li key={l.id} className={styles.lesson} data-testid="knowledge-lesson">
                <span className={ui.tag}>lesson</span> <strong>{l.domain} · {l.topic}</strong> — {l.text}
              </li>
            ))}
          </ul>
        </div>
        {selected ? (
          <KnowledgeDetail key={selected.id} doc={selected} epics={data.epics} onClose={() => select(null)} />
        ) : (
          <p className={ui.empty}>Pick a doc to read, edit, rule on or link it.</p>
        )}
      </div>
      <NewKnowledgeDialog open={dialog === "new"} onClose={() => setDialog(null)} onCreated={(id) => select(id)} />
      <ImportSkillDialog open={dialog === "import"} onClose={() => setDialog(null)} onImported={(id) => select(id)} />
    </section>
  );
}
