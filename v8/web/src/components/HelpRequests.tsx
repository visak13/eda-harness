import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BoardApiError } from "../api/client";
import { askForHelp, closeTopic, getHelpRequests } from "../api/endpoints";
import type { TopicSeat } from "../api/types";
import ui from "./ui.module.css";
import { useAttention } from "../api/attention";
import { AttentionDot, attentionMark } from "./AttentionDot";
import styles from "./HelpRequests.module.css";

/** t-67dad8c6aa: where a help request is, in the person's words (topics.seat_view's `phase`). */
export function helpPhaseText(seat: TopicSeat): string {
  switch (seat.phase) {
    case "queued": return "Queued: the Help seat starts within a few seconds";
    case "starting": return "Starting";
    case "answering": return "Answering";
    case "failed": return `Failed: ${seat.reason || "the seat ended without answering"}. Send a message to retry.`;
    case "idle": return "Idle: your next message wakes it";
    default: return seat.state;
  }
}

function errText(e: unknown): string {
  return e instanceof BoardApiError ? e.hint || e.message : String(e);
}

/** t-67dad8c6aa (owner m-8994975b6f): Ask for help takes the person's words, and lists their help requests
 *  with each seat's state and Close — help threads are not Library topics, so this is where they are found. */
export function HelpRequests({ onDone }: { onDone: () => void }): React.JSX.Element {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const need = new Map(useAttention().scopes.filter((s) => s.type === "help").map((s) => [s.id, s])); // S20 trail
  const list = useQuery({ queryKey: ["help-requests"], queryFn: () => getHelpRequests(), refetchInterval: 5000 });
  const ask = useMutation({
    mutationFn: (words: string) => askForHelp(words),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["help-requests"] });
      onDone();
      navigate(`/library/topics/${encodeURIComponent(r.value.topic.id)}`);
    },
  });
  const close = useMutation({
    mutationFn: (id: string) => closeTopic(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["help-requests"] }),
  });
  const words = text.trim();
  const rows = list.data ?? [];
  return (
    <div className={styles.wrap} data-testid="help-requests">
      <form onSubmit={(e) => { e.preventDefault(); if (words) ask.mutate(words); }}>
        <label className={styles.label} htmlFor="help-words">What is wrong?</label>
        <textarea id="help-words" className={styles.words} rows={3} value={text} data-testid="help-words"
          placeholder="Say what you see, e.g. my engineer seat never answers" onChange={(e) => setText(e.target.value)} />
        <button type="submit" className={ui.button} disabled={!words || ask.isPending} data-testid="help-send">Ask the Help seat</button>
      </form>
      {ask.isError ? <p role="alert" className={styles.error} data-testid="ask-help-error">{errText(ask.error)}</p> : null}
      <h3 className={styles.heading}>Your help requests</h3>
      {list.isError ? <p role="alert" className={styles.error}>{errText(list.error)}</p> : null}
      {list.isSuccess && rows.length === 0 ? <p className={styles.muted} data-testid="help-none">No open help requests.</p> : null}
      <ul className={styles.list}>
        {rows.map((r) => (
          <li key={r.id} className={`${styles.row} ${need.has(r.id) ? attentionMark : ""}`} data-testid="help-request"
            data-attention={need.has(r.id) ? "true" : undefined}>
            <Link to={`/library/topics/${encodeURIComponent(r.id)}`} onClick={onDone} className={styles.title}>{r.title} <AttentionDot count={need.get(r.id)?.count ?? 0} /></Link>
            <span className={styles.phase} data-testid="help-phase" data-phase={r.seat.phase ?? r.seat.state}>{helpPhaseText(r.seat)}</span>
            <button type="button" className={ui.button} disabled={close.isPending} data-testid="help-close"
              onClick={() => close.mutate(r.id)}>Close</button>
          </li>
        ))}
      </ul>
      {close.isError ? <p role="alert" className={styles.error}>{errText(close.error)}</p> : null}
    </div>
  );
}
