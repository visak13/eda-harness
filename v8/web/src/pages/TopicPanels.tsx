import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addTopicExpert, postTopicMessage, removeTopicExpert } from "../api/endpoints";
import type { ExpertAdded, TopicPage } from "../api/types";
import ui from "../components/ui.module.css";
import { errText, when } from "./Topics";
import styles from "./Topics.module.css";

// The topic page's thread and experts panels (S-SME-SURFACE). An expert posts note/question/answer; every
// post wakes the topic's sme. An expert's token shows once, in the add result, and never again.

const POST_KINDS = ["note", "question", "answer"] as const;

export function TopicThread({ page }: { page: TopicPage }): React.JSX.Element {
  const id = page.topic.id;
  const [text, setText] = useState("");
  const [kind, setKind] = useState<string>("question");
  const qc = useQueryClient();
  const send = useMutation({
    mutationFn: () => postTopicMessage(id, { text: text.trim(), kind }),
    onSuccess: () => { setText(""); void qc.invalidateQueries({ queryKey: ["topic", id] }); },
  });
  const isOpen = page.topic.status === "open";
  return (
    <section className={styles.panel} aria-label="Thread" data-testid="topic-thread">
      <span className={ui.sectionLabel}>Thread</span>
      {page.thread.length === 0 ? <p className={styles.muted}>No messages yet. Ask the sme anything about this topic.</p> : (
        <ul className={styles.list}>
          {page.thread.map((m) => (
            <li key={m.id} className={styles.msg} data-testid="topic-message">
              <span className={styles.msgMeta}>
                {m.created_by}{m.from.role ? ` · ${m.from.role}` : ""} · {m.kind} · {when(m.created_at)}
                {m.to ? ` → ${m.to}` : ""}
              </span>
              <p className={styles.msgText}>{m.text}</p>
            </li>
          ))}
        </ul>
      )}
      {isOpen ? (
        <form className={styles.col} onSubmit={(e) => { e.preventDefault(); if (text.trim()) send.mutate(); }}>
          <textarea className={ui.textarea} rows={3} aria-label="Message" value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Write to the sme (and the experts)…" data-testid="topic-composer" />
          <div className={styles.inline}>
            <select className={ui.select} aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              {POST_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!text.trim() || send.isPending}
              data-testid="topic-send">Send</button>
          </div>
          {send.isError ? <p className={ui.banner} role="alert">{errText(send.error)}</p> : null}
        </form>
      ) : <p className={styles.muted}>The topic is closed.</p>}
    </section>
  );
}

export function TopicExperts({ page }: { page: TopicPage }): React.JSX.Element {
  const id = page.topic.id;
  const [handle, setHandle] = useState("");
  const [added, setAdded] = useState<ExpertAdded | null>(null);
  const qc = useQueryClient();
  const refresh = () => void qc.invalidateQueries({ queryKey: ["topic", id] });
  const add = useMutation({
    mutationFn: () => addTopicExpert(id, { handle: handle.trim() }),
    onSuccess: (res) => { setHandle(""); setAdded(res.value); refresh(); },
  });
  const remove = useMutation({ mutationFn: (expertId: string) => removeTopicExpert(id, expertId), onSuccess: refresh });
  const isOpen = page.topic.status === "open";
  return (
    <section className={styles.panel} aria-label="Experts" data-testid="topic-experts">
      <span className={ui.sectionLabel}>Experts</span>
      <p className={styles.muted}>Named people from your team. An expert reads this topic and posts on its thread, nothing else.</p>
      {page.experts.length === 0 ? <p className={styles.muted}>No experts yet.</p> : (
        <ul className={styles.list}>
          {page.experts.map((x) => (
            <li key={x.id} className={styles.inline} data-testid="topic-expert">
              <strong>{x.handle}</strong>
              <span className={styles.muted}>added {when(x.created_at)}</span>
              <button type="button" className={ui.button} disabled={remove.isPending}
                onClick={() => { if (window.confirm(`Remove ${x.handle}? Their link stops working.`)) remove.mutate(x.id); }}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      {remove.isError ? <p className={ui.banner} role="alert">{errText(remove.error)}</p> : null}
      {isOpen ? (
        <form className={styles.inline} onSubmit={(e) => { e.preventDefault(); if (handle.trim()) add.mutate(); }}>
          <input className={ui.input} aria-label="Expert handle" placeholder="handle, e.g. priya" value={handle}
            onChange={(e) => setHandle(e.target.value)} data-testid="topic-expert-handle" />
          <button type="submit" className={ui.button} disabled={!handle.trim() || add.isPending} data-testid="topic-expert-add">Add expert</button>
        </form>
      ) : null}
      {add.isError ? <p className={ui.banner} role="alert">{errText(add.error)}</p> : null}
      {added ? (
        <div role="status" data-testid="topic-expert-link">
          <p className={styles.muted}>Send {added.expert.handle} this link now. It carries their token, which is not shown again.</p>
          <p className={styles.secret}>{`${window.location.origin}${added.link}`}</p>
          <button type="button" className={ui.button} onClick={() => setAdded(null)}>Done</button>
        </div>
      ) : null}
    </section>
  );
}
