import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import type { Quote } from "../api/types";
import { getMessage } from "../api/endpoints";
import { markRequirement } from "../api/requirements";
import { CodeCard } from "./CodeCard";
import { Icon } from "./Icon";
import { MentionInput } from "./MentionInput";
import { RefText } from "./RefText";
import { displayPassage } from "./quoteMatch";
import { quoteTray, useQuoteTray } from "./quoteTray";
import styles from "./QuoteCard.module.css";

// C19 (design-10b21760d9 §14.5): a message's quotes render as cards ABOVE its text — the passage the
// board verified, its source link and the sender's note. A doc link opens that version in the doc
// drawer scrolled to the quoted lines (?doc=&v=&line=); a message link scrolls to it in this thread,
// or opens the thread it lives on. A code quote is the existing code card. The composer's chips
// (QuoteChips) are the same quotes before sending: reorder, edit the note, remove.

/** `§14.5` for a numbered heading, else `§<heading>` clipped (mirrors edp8/quotes.py section_label). */
export function sectionLabel(heading: string | null | undefined): string {
  if (!heading) return "";
  const m = /^(\d+(?:\.\d+)*)\.?(?:\s|$)/.exec(heading);
  return `§${m ? m[1] : heading.length <= 60 ? heading : `${heading.slice(0, 59)}…`}`;
}

export function quoteSourceLabel(q: Quote): string {
  if (q.source === "doc") {
    const lo = q.locator ?? {};
    const lines = lo.line_start ? `L${lo.line_start}${lo.line_end && lo.line_end > lo.line_start ? `-${lo.line_end}` : ""}` : "";
    return [`${q.id} v${q.version}`, sectionLabel(lo.heading), lines].filter(Boolean).join(" ");
  }
  if (q.source === "message") return `${q.id}${q.author ? ` (${q.author})` : ""}`;
  return q.code ? `${q.code.path}:L${q.code.line_start}-${q.code.line_end}` : "code";
}

/** Scrolls to a message in the thread on screen and flashes it; false when it is not on screen. */
export function scrollToMessage(id: string): boolean {
  const el = document.getElementById(id);
  if (!el) return false;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  el.setAttribute("data-flash", "1");
  setTimeout(() => el.removeAttribute("data-flash"), 2000);
  return true;
}

/** s-aa76c83998 (owner m-45541e67b1): the quote card's second button. It sends no message: it records the quoted span
 *  (the message id and its character range) as a requirement of the epic the message sits on. Owners and guests both. */
export interface MarkSpan { messageId: string; charStart?: number | null; charEnd?: number | null; text?: string }

/** The Mark-as-requirement button. `resolve` yields the span to record (async, so the selection popup can locate it first). */
export function MarkButton({ resolve, testid = "quote-mark-requirement", className, onError, onDone }:
  { resolve: () => Promise<MarkSpan | { error: string }>; testid?: string; className?: string;
    /** The host shows the failure itself (the selection popover's single error line); the button then renders none. */
    onError?: (message: string) => void;
    /** Called once the requirement is recorded: the selection popover closes and says so in a toast (qa fail 8). */
    onDone?: () => void }): React.JSX.Element {
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [error, setError] = useState("");
  const fail = (message: string) => { setState("error"); setError(message); onError?.(message || "Could not mark it"); };
  const mark = () => {
    setState("busy");
    setError("");
    onError?.("");
    void resolve()
      .then((s) => {
        if ("error" in s) { fail(s.error); return undefined; }
        return markRequirement(s).then((r) => { setState("done"); void qc.invalidateQueries({ queryKey: ["epic", r.epic, "requirements"] }); onDone?.(); });
      })
      .catch((e: Error) => fail(e.message));
  };
  return (
    <>
      <button type="button" className={className ?? styles.mark} data-testid={testid} onClick={mark}
        disabled={state === "busy" || state === "done"} aria-live="polite">
        {state === "done" ? "Marked as requirement" : state === "busy" ? "Marking…" : "Mark as requirement"}
      </button>
      {state === "error" && !onError ? <span className={styles.markError} role="alert" data-testid="quote-mark-error">{error || "Could not mark it"}</span> : null}
    </>
  );
}

export function spanOf(q: { id?: string | null; locator?: object; text?: string | null }): MarkSpan {
  return { messageId: q.id ?? "", charStart: (q.locator as { char_start?: number | null } | undefined)?.char_start, charEnd: (q.locator as { char_end?: number | null } | undefined)?.char_end, text: q.text ?? undefined };
}

function MarkRequirement({ q }: { q: Quote }): React.JSX.Element | null {
  if (q.source !== "message" || !q.id) return null;
  return <MarkButton resolve={() => Promise.resolve(spanOf(q))} />;
}

export function QuoteCard({ q }: { q: Quote }): React.JSX.Element {
  const navigate = useNavigate();
  const note = q.note ? <p className={styles.note} data-testid="quote-note-text"><span>Note</span> <RefText text={q.note} /></p> : null;
  if (q.source === "code" && q.code) {
    return <div className={styles.card} data-testid="quote-card" data-source="code"><CodeCard c={q.code} />{note}</div>;
  }
  const label = quoteSourceLabel(q);
  let link: React.ReactNode;
  if (q.source === "doc" && q.id) {
    const lo = q.locator ?? {};
    const search = new URLSearchParams({ doc: q.id, ...(q.version ? { v: String(q.version) } : {}),
      ...(lo.line_start ? { line: `${lo.line_start}-${lo.line_end ?? lo.line_start}` } : {}) });
    link = (
      <a href={`?${search}`} className={styles.source} data-testid="quote-source"
        onClick={(e) => {
          if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
          e.preventDefault();
          navigate({ search: `?${search}` });
        }}>
        <Icon name="files" size={16} /> {label}
      </a>
    );
  } else {
    link = (
      <a href={`#${q.id}`} className={styles.source} data-testid="quote-source"
        onClick={(e) => {
          if (!q.id || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
          e.preventDefault();
          if (scrollToMessage(q.id)) return;
          void getMessage(q.id).then((m) => {
            const base = m.ticket_id.startsWith("epic-") ? "epic" : "ticket";
            navigate(`/${base}/${encodeURIComponent(m.ticket_id)}#${encodeURIComponent(q.id!)}`);
          }).catch(() => {});
        }}>
        <Icon name="reply" size={16} /> {label}
      </a>
    );
  }
  return (
    <figure className={styles.card} data-testid="quote-card" data-source={q.source}>
      <blockquote className={styles.passage} data-testid="quote-passage" title={q.text}>{displayPassage(q.text)}</blockquote>
      <figcaption className={styles.foot}>{link}<MarkRequirement q={q} /></figcaption>
      {note}
    </figure>
  );
}

/** The composer's quote chips for one thread: in send order, each with ↑ ↓ ✕ and its note. */
export function QuoteChips({ ticketId, disabled, invalid }: { ticketId: string; disabled?: boolean; invalid?: string | null }): React.JSX.Element | null {
  const rows = useQuoteTray(ticketId);
  if (!rows.length) return null;
  return (
    <ol className={styles.chips} data-testid="quote-chips" aria-label="Quotes in this message">
      {rows.map((r, i) => (
        <li key={r.key} className={styles.chip} data-testid="quote-chip" data-invalid={invalid === r.key || undefined}>
          <div className={styles.chipHead}>
            <span className={styles.chipLabel} data-testid="quote-chip-label">{r.label}</span>
            <button type="button" aria-label={`Move quote ${i + 1} up`} disabled={disabled || i === 0}
              data-testid="quote-chip-up" onClick={() => quoteTray.move(ticketId, r.key, -1)}>↑</button>
            <button type="button" aria-label={`Move quote ${i + 1} down`} disabled={disabled || i === rows.length - 1}
              data-testid="quote-chip-down" onClick={() => quoteTray.move(ticketId, r.key, 1)}>↓</button>
            <button type="button" aria-label={`Remove quote ${i + 1}`} disabled={disabled}
              data-testid="quote-chip-remove" onClick={() => quoteTray.remove(ticketId, r.key)}><Icon name="close" size={16} /></button>
          </div>
          <p className={styles.chipText} data-testid="quote-chip-text">{clip(displayPassage(r.quote.text), 160)}</p>
          {r.quote.source === "message" ? <MarkButton testid="quote-chip-mark" resolve={() => Promise.resolve(spanOf(r.quote))} /> : null}
          <MentionInput className={styles.chipNote} value={r.quote.note ?? ""} maxLength={2000} disabled={disabled}
            placeholder="Note (optional). @ to notify someone" aria-label={`Note on quote ${i + 1}`} data-testid="quote-chip-note"
            onValue={(v) => quoteTray.setNote(ticketId, r.key, v)} />
        </li>
      ))}
    </ol>
  );
}

function clip(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
