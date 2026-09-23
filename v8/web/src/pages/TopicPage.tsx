import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { closeTopic, getTopicDoc, getTopicPage, setTopicTags } from "../api/endpoints";
import type { TopicDoc, TopicPage as TopicPageData } from "../api/types";
import ui from "../components/ui.module.css";
import { PageHeader } from "../components/PageHeader";
import { parseTags } from "./KnowledgeDetail";
import { errText, when } from "./Topics";
import { TopicExperts, TopicThread } from "./TopicPanels";
import styles from "./Topics.module.css";

// S-SME-SURFACE (s-698224fca8): one Library topic — docs, thread, experts, seat and tags. The same page
// serves the owner and a topic's expert; it reads only /v1/topics/{id}* so an expert's scoped token
// (refused everywhere else) sees it whole. Owner-only controls hide for an expert.

export function TopicPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["topic", id], queryFn: () => getTopicPage(id), refetchInterval: 5000 });
  const close = useMutation({
    mutationFn: () => closeTopic(id),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["topic", id] }); void qc.invalidateQueries({ queryKey: ["topics"] }); },
  });
  if (q.isPending) return <p className={ui.empty}>Loading…</p>;
  if (q.isError) return <p className={ui.banner} role="alert">{errText(q.error)}</p>;
  const p = q.data;
  const owner = p.viewer.role !== "expert";
  const isOpen = p.topic.status === "open";
  return (
    <div data-testid="topic-page">
      <PageHeader title="Library" subtitle={owner ? "A topic you keep, with its resident sme." : `You are an expert on this topic (${p.viewer.id}).`} />
      {owner ? <p><Link to={`/library/topics${suffix}`} className={styles.muted}>← All topics</Link></p> : null}
      <div className={styles.head}>
        <h2 className={styles.headTitle}>{p.topic.title}</h2>
        <span className={ui.tag} data-testid="topic-status">{p.topic.status}</span>
        <span className={styles.muted} data-testid="topic-seat">sme seat {p.seat.participant} · {p.seat.state}{p.seat.model ? ` · ${p.seat.model}${p.seat.effort ? ` at ${p.seat.effort}` : ""}` : ""}</span>
        {owner && isOpen ? (
          <button type="button" className={ui.button} disabled={close.isPending} data-testid="topic-close"
            onClick={() => { if (window.confirm("Close this topic? Its sme seat is released.")) close.mutate(); }}>
            Close topic
          </button>
        ) : null}
      </div>
      {close.isError ? <p className={ui.banner} role="alert">{errText(close.error)}</p> : null}
      {p.topic.words ? <p className={styles.words} data-testid="topic-words">{p.topic.words}</p> : null}
      {p.seed_url ? <p className={styles.muted}>Seed <a href={p.seed_url} target="_blank" rel="noreferrer">{p.seed_url}</a></p> : null}
      <div className={styles.layout}>
        <div className={styles.col}>
          <TopicTags page={p} canEdit={owner && isOpen} />
          <TopicDocs page={p} />
          <TopicThread page={p} />
        </div>
        <div className={styles.col}>
          {owner ? <TopicExperts page={p} /> : null}
          <TopicFetches page={p} />
        </div>
      </div>
    </div>
  );
}

function TopicTags({ page, canEdit }: { page: TopicPageData; canEdit: boolean }): React.JSX.Element {
  const id = page.topic.id;
  const [draft, setDraft] = useState<string | null>(null);
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: () => setTopicTags(id, parseTags(draft ?? "")),
    onSuccess: () => { setDraft(null); void qc.invalidateQueries({ queryKey: ["topic", id] }); },
  });
  const by = page.tags_set_by;
  return (
    <section className={styles.panel} aria-label="Tags">
      <div className={styles.inline} data-testid="topic-tags">
        <span className={ui.sectionLabel}>Tags</span>
        {page.topic.tags.length ? page.topic.tags.map((g) => <span key={g} className={ui.tag}>{g}</span>) : <span className={styles.muted}>none yet</span>}
        {by ? <span className={styles.muted} data-testid="topic-tags-by">set by {by.by} · {when(by.at)}</span> : null}
        {canEdit && draft === null ? (
          <button type="button" className={ui.button} onClick={() => setDraft(page.topic.tags.join(", "))} data-testid="topic-tags-edit">Edit</button>
        ) : null}
      </div>
      {draft !== null ? (
        <form className={styles.inline} onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <input className={ui.input} aria-label="Tags" value={draft} onChange={(e) => setDraft(e.target.value)} data-testid="topic-tags-input" />
          <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={save.isPending} data-testid="topic-tags-save">Save</button>
          <button type="button" className={ui.button} onClick={() => setDraft(null)}>Cancel</button>
          <span className={styles.muted}>One list with the sme: the last write wins.</span>
        </form>
      ) : null}
      {save.isError ? <p className={ui.banner} role="alert">{errText(save.error)}</p> : null}
    </section>
  );
}

function TopicDocs({ page }: { page: TopicPageData }): React.JSX.Element {
  return (
    <section className={styles.panel} aria-label="Docs" data-testid="topic-docs">
      <span className={ui.sectionLabel}>Docs</span>
      {page.docs.length === 0 ? <p className={styles.muted}>No docs yet: the sme files proposals here as it researches.</p> : (
        <ul className={styles.list}>
          {page.docs.map((d) => <TopicDocRow key={d.id} topicId={page.topic.id} doc={d} />)}
        </ul>
      )}
      {page.viewer.role !== "expert" && page.docs.some((d) => d.status === "proposed") ? (
        <p className={styles.muted}>Approve or reject proposals in <Link to="/library/knowledge">Knowledge</Link>.</p>
      ) : null}
    </section>
  );
}

function TopicDocRow({ topicId, doc }: { topicId: string; doc: TopicDoc }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const full = useQuery({ queryKey: ["topic", topicId, "doc", doc.id], queryFn: () => getTopicDoc(topicId, doc.id), enabled: open });
  return (
    <li data-testid="topic-doc">
      <div className={styles.inline}>
        <span className={ui.tag}>{doc.status}</span>
        <button type="button" className={ui.button} onClick={() => setOpen((o) => !o)} aria-expanded={open}>{doc.title}</button>
        <span className={ui.idMono}>{doc.id} v{doc.version}</span>
        {doc.proposes ? <span className={styles.muted}>next version of {doc.proposes}</span> : null}
      </div>
      {doc.source_url ? <p className={styles.muted}>Source <a href={doc.source_url} target="_blank" rel="noreferrer">{doc.source_url}</a></p> : null}
      {open ? (full.isPending ? <p className={styles.muted}>Loading…</p>
        : full.isError ? <p className={ui.banner} role="alert">{errText(full.error)}</p>
          : <pre className={styles.docBody}>{full.data.body_md}</pre>) : null}
    </li>
  );
}

function TopicFetches({ page }: { page: TopicPageData }): React.JSX.Element {
  return (
    <section className={styles.panel} aria-label="Research receipts" data-testid="topic-fetches">
      <span className={ui.sectionLabel}>Research receipts</span>
      {page.fetches.length === 0 ? <p className={styles.muted}>The sme has not fetched anything yet.</p> : (
        <ul className={styles.list}>
          {page.fetches.map((f, i) => (
            <li key={`${f.url}-${i}`} className={styles.muted}>
              {f.status} · {when(f.fetched_at)} · <a href={f.url} target="_blank" rel="noreferrer">{f.url}</a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
