import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { MessageSent, PersonRow } from "../api/types";
import type { MessageKind } from "../api/types";
import { getPeople, resolveMessage, sendMessage, uploadArtifact } from "../api/endpoints";
import { useDirtyGuard } from "../live/useDraftGuard";
import { useMentions } from "./useMentions";
import styles from "./Composer.module.css";

// The object-attached composer (design §4.2/§13/§16.1/§18.1). The conversation is IMPLICIT — the
// object it sits on (a ticket) — so the composer carries only kind / to / text (+ staged
// attachments). Who a message reaches is the BOARD's decision: the To picker and @autocomplete
// share the one /v1/me/people list, the wake preview comes from POST /v1/messages/resolve (the
// same delivery plan the board uses, so it cannot drift), and after send the board's resolution
// note is shown verbatim. It never fans out — exactly one `to`.

const ROLES: string[] = ["architect", "engineer", "sme", "qa", "reviewer", "owner"];
const ROLE_GLOSS: Record<string, string> = {
  architect: "design questions, rulings",
  engineer: "builds a story",
  sme: "craft author",
  qa: "final acceptance",
  reviewer: "independent verdict",
  owner: "the human who steers and approves",
};
const NEEDS_CONFIRM: MessageKind[] = ["question", "deviation"];

export interface ComposerProps {
  ticketId: string;
  /** Selectable message kinds; when one, the kind is fixed and no selector shows. Default ['note']. */
  kinds?: MessageKind[];
  placeholder?: string;
  onSent?: (m: MessageSent) => void;
  /** Prefill / fix the recipient (a Seats "Message", a "New conversation", a reply). */
  to?: string | null;
  /** Reply threading: the message this answers (Questions tab inline reply posts kind=answer). */
  replyTo?: string | null;
  /** Show the People / Live seats / Roles "To" picker. Off for a fixed-recipient reply. */
  showTo?: boolean;
  /** Report dirty (non-empty draft) so the draft guard holds live refreshes while typing. */
  onDirtyChange?: (dirty: boolean) => void;
}

export function Composer({
  ticketId,
  kinds = ["note"],
  placeholder,
  onSent,
  to: toProp = null,
  replyTo = null,
  showTo = false,
  onDirtyChange,
}: ComposerProps): React.JSX.Element {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [kind, setKind] = useState<MessageKind>(kinds[0]);
  const [to, setTo] = useState<string | null>(toProp);
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [sentNote, setSentNote] = useState<string | null>(null);
  const [unresolved, setUnresolved] = useState<string[]>([]);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const idRef = useRef(`composer-${Math.random().toString(36).slice(2)}`);
  const dirty = text.trim().length > 0 || artifacts.length > 0;

  useEffect(() => setTo(toProp), [toProp]);
  // Hold the app's live refresh while this composer has an unsent draft (design §4.2 draft guard),
  // and surface the same flag to a parent that wants it.
  useDirtyGuard(idRef.current, dirty);
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const people = useQuery({ queryKey: ["me", "people"], queryFn: getPeople, retry: false });
  const mentions = useMentions(people.data ?? [], taRef, setText);

  // Wake preview — the board's delivery plan for this (to, kind). Reactive so it cannot drift from
  // delivery; nothing is sent (design §16.1). Enabled once there is a target to preview.
  const preview = useQuery({
    queryKey: ["resolve", ticketId, to, kind],
    queryFn: () => resolveMessage({ ticket_id: ticketId, to, kind }),
    enabled: Boolean(ticketId),
    retry: false,
  });

  // Auto-grow the textarea from 4 rows to 14 (design §4.2 composer size).
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const line = 22;
    const min = line * 4 + 16;
    const max = line * 14 + 16;
    ta.style.height = `${Math.min(Math.max(ta.scrollHeight, min), max)}px`;
  }, [text]);

  const emptyPlan = (preview.data?.plan?.length ?? 0) === 0;
  const needsConfirm = NEEDS_CONFIRM.includes(kind) && emptyPlan;

  const send = useMutation({
    mutationFn: () =>
      sendMessage({
        ticket_id: ticketId,
        kind,
        text: text.trim(),
        to,
        reply_to: replyTo,
        artifacts: artifacts.length ? artifacts : undefined,
      }),
    onSuccess: ({ value, hint }) => {
      setSentNote(hint || "Sent.");
      setUnresolved(value.unresolved_mentions ?? []);
      setText("");
      setArtifacts([]);
      setConfirming(false);
      onDirtyChange?.(false);
      onSent?.(value);
      void qc.invalidateQueries();
    },
  });

  function trySend() {
    if (text.trim().length === 0 && artifacts.length === 0) return;
    if (needsConfirm && !confirming) {
      setConfirming(true); // one confirm step when a question/deviation would wake nobody
      return;
    }
    send.mutate();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (mentions.onKeyDown(e)) return; // menu nav / accept consumes the key first
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      trySend();
    }
    // plain Enter falls through → a newline (design §4.2: Enter never sends)
  }

  async function ingestFiles(files: FileList | File[]) {
    setUploadError(null);
    for (const file of Array.from(files)) {
      try {
        const art = await uploadArtifact(file, ticketId);
        setArtifacts((a) => [...a, art.id]);
        // The artifact id is already `art-…`; insert it verbatim as the token the message parser
        // resolves to a thumbnail/chip (design §18.1). Do NOT prefix another "art-".
        setText((t) => `${t}${t && !t.endsWith(" ") ? " " : ""}${art.id} `);
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : String(err)); // draft is left intact
      }
    }
  }

  const kindFixed = kinds.length <= 1;
  const glossFor = (v: string) => (ROLE_GLOSS[v] ? ` — ${ROLE_GLOSS[v]}` : "");

  return (
    <section
      className={`${styles.composer} ${dragOver ? styles.dragging : ""}`}
      data-testid="composer"
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (e.dataTransfer.files.length) void ingestFiles(e.dataTransfer.files);
      }}
    >
      {dragOver ? <div className={styles.veil} data-testid="drop-veil">Drop to attach</div> : null}

      <div className={styles.controls}>
        {kindFixed ? null : (
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Kind</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as MessageKind)} aria-label="Message kind">
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
        )}
        {showTo ? (
          <label className={styles.field}>
            <span className={styles.fieldLabel}>To</span>
            <select
              value={to ?? ""}
              onChange={(e) => setTo(e.target.value || null)}
              aria-label="Recipient"
              data-testid="to-picker"
            >
              <option value="">Note on this ticket — reaches the seats working it</option>
              <ToGroups people={people.data ?? []} />
            </select>
          </label>
        ) : null}
      </div>

      <textarea
        ref={taRef}
        className={styles.text}
        value={text}
        placeholder={placeholder ?? "Type a message. @ to notify someone. Ctrl+Enter sends."}
        onChange={(e) => {
          setText(e.target.value);
          setSentNote(null);
        }}
        onKeyDown={onKeyDown}
        onKeyUp={mentions.refresh}
        onClick={mentions.refresh}
        aria-label="Message"
        data-testid="composer-text"
      />

      {mentions.menu.open ? (
        <ul className={styles.mentions} role="listbox" data-testid="mentions-menu">
          {mentions.menu.items.map((p, i) => (
            <li
              key={p.id}
              role="option"
              aria-selected={i === mentions.menu.index}
              className={i === mentions.menu.index ? styles.mentionActive : ""}
              onMouseDown={(e) => {
                e.preventDefault();
                mentions.accept(p);
              }}
            >
              <span className={styles.mentionHandle}>@{p.handle}</span>
              <span className={styles.mentionLabel}>{p.label}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {/* Wake preview — the board's plan, verbatim; the preview cannot drift from delivery. */}
      {preview.data ? (
        <div className={styles.preview} data-testid="wake-preview">
          {preview.data.plan.length > 0 ? (
            preview.data.plan.map((w) => (
              <div key={w.recipient} className={styles.previewLine}>
                Wakes <strong>{w.recipient}</strong>
                {w.alive === true ? " (alive)" : w.alive === false ? " (not alive)" : ""} — {w.why}
              </div>
            ))
          ) : (
            <div className={styles.previewLine}>{preview.data.note || "Nobody will be woken."}</div>
          )}
        </div>
      ) : null}

      {uploadError ? (
        <p className={styles.error} role="alert">
          Upload failed: {uploadError}. Your draft is kept.
        </p>
      ) : null}

      <div className={styles.footer}>
        <span className={styles.hint}>Ctrl/Cmd+Enter sends · Enter for a newline · @ to notify</span>
        <button
          className={styles.send}
          type="button"
          disabled={send.isPending || (text.trim().length === 0 && artifacts.length === 0)}
          onClick={trySend}
          data-testid="composer-send"
        >
          {confirming ? "Send anyway — wakes nobody" : "Send"}
        </button>
      </div>

      {send.error ? (
        <p className={styles.error} role="alert">
          {send.error instanceof Error ? send.error.message : "Send failed"} — your draft is kept.
        </p>
      ) : null}

      {sentNote ? (
        <p className={styles.sent} role="status" data-testid="sent-note">
          {sentNote}
        </p>
      ) : null}

      {unresolved.length > 0 ? (
        <div className={styles.unresolved} role="status" data-testid="unresolved-banner">
          No participant matched: {unresolved.map((h) => `@${h}`).join(", ")} — the message posted, but nobody was woken for these.
        </div>
      ) : null}
    </section>
  );

  function ToGroups({ people: rows }: { people: PersonRow[] }): React.JSX.Element {
    const humans = rows.filter((p) => p.type === "human");
    const seats = rows.filter((p) => p.type === "agent");
    const liveRoles = new Set(seats.map((s) => s.role));
    return (
      <>
        {humans.length ? (
          <optgroup label="People">
            {humans.map((p) => (
              <option key={p.id} value={p.handle}>
                {p.handle} · person
              </option>
            ))}
          </optgroup>
        ) : null}
        {seats.length ? (
          <optgroup label="Live seats">
            {seats.map((p) => (
              <option key={p.id} value={p.handle}>
                {p.label} · {p.seat_ticket ?? "—"} · {p.seat_state}
              </option>
            ))}
          </optgroup>
        ) : null}
        <optgroup label="Roles on this epic">
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r} · {liveRoles.has(r) ? "seat live" : "no seat yet"}
              {glossFor(r)}
            </option>
          ))}
        </optgroup>
      </>
    );
  }
}
