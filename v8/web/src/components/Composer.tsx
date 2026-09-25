import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { MessageSent, PersonRow, UploadedArtifact } from "../api/types";
import type { MessageKind } from "../api/types";
import { getPeople, resolveMessage, sendMessage, type SendMessage } from "../api/endpoints";
import { useDirtyGuard } from "../live/useDraftGuard";
import { useDropUpload } from "./useDropUpload";
import { useMentions } from "./useMentions";
import { mentionedHandles } from "./mentions";
import styles from "./Composer.module.css";
import { Icon } from "./Icon";
import { identity } from "../auth/identity";
import { readDraft, writeDraft } from "./draftStorage";
import { Avatar } from "./Avatar";
import { QuoteChips } from "./QuoteCard";
import { quoteTray, registerQuoteTarget, useQuoteTray } from "./quoteTray";
const draftStores = new WeakMap<object, Map<string, import("./draftStorage").StoredDraft>>();

// The object-attached composer (design §4.2/§13/§16.1/§18.1). The conversation is IMPLICIT — the
// object it sits on (a ticket) — so the composer carries only kind / to / text (+ staged
// attachments). Who a message reaches is the BOARD's decision: the To picker and @autocomplete
// share the one /v1/me/people list, the wake preview comes from POST /v1/messages/resolve (the
// same delivery plan the board uses, so it cannot drift), and after send the board's resolution
// note is shown verbatim. It never fans out — exactly one `to`.

const ROLES: string[] = ["architect", "engineer", "sme", "qa", "adversary", "owner"];
// Promise #16: every To/Kind option says WHO IT WAKES in one line (visible in the option label and
// as its title). Copy is local to the composer on purpose — the shared copy table is not touched.
const ROLE_GLOSS: Record<string, string> = {
  architect: "wakes the architect on this epic — design questions, rulings",
  engineer: "wakes the engineer on this epic — builds a story",
  sme: "wakes the sme on this epic — craft author",
  qa: "wakes the qa on this epic — final acceptance",
  reviewer: "wakes the reviewer on this epic — independent verdict",
  owner: "reaches the owner — the human who steers and approves",
};
const KIND_GLOSS: Partial<Record<MessageKind, string>> = {
  note: "wakes the seats working this ticket, or only the seat you @tag / pick in To",
  question: "wakes the seat or role you address; they answer here",
  answer: "wakes the seat that asked",
  deviation: "wakes the seat or role you address — the design cannot be followed as written",
};
const NEEDS_CONFIRM: MessageKind[] = ["question", "deviation"];

/** The "?" popover (promise #16): what wake / seat / role mean, once, in plain words. */
function ComposerHelp({ onClose }: { onClose: () => void }): React.JSX.Element {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => closeRef.current?.focus(), []);
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="dialog"
      aria-label="How sending works"
      className={styles.help}
      data-testid="composer-help"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <div className={styles.helpHead}>
        <strong>How sending works</strong>
        <button ref={closeRef} type="button" className={styles.helpClose} aria-label="Close help" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      <p>
        <strong>Wake</strong> — a message addressed <em>to</em> a seat or role wakes that seat&apos;s shell:
        the agent reads it and acts. A note with nobody addressed reaches the seats already working this
        ticket.
      </p>
      <p>
        <strong>Seat</strong> — one running agent shell bound to one ticket, named <code>role.ticket</code>
        (for example <code>engineer.s-12</code>). Only a live seat can be woken.
      </p>
      <p>
        <strong>Role</strong> — the job a seat does: architect, engineer, reviewer, qa, owner or
        coordinator. Addressing a role wakes the seat holding that role on this epic.
      </p>
    </div>
  );
}

/** The first `@handle` in `text` that names a known participant (handle or id), else null.
 *  Uses the shared tokeniser (round 2 #6): code spans and e-mail interiors never address anyone. */
export function firstMentionedHandle(text: string, people: PersonRow[]): string | null {
  return mentionedHandles(text, people)[0] ?? null;
}

export interface ComposerProps {
  ticketId: string;
  /** Typed document feedback keeps the full composer while replacing only the write endpoint. */
  submit?: (body: SendMessage) => ReturnType<typeof sendMessage>;
  lockRecipient?: boolean;
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
  /** Suppress the To row entirely — the host already shows the single recipient (e.g. the
   *  design-review panel's chip); `to` is kept for the send target. Avoids a duplicate recipient. */
  hideRecipient?: boolean;
  /** Report dirty (non-empty draft) so the draft guard holds live refreshes while typing. */
  onDirtyChange?: (dirty: boolean) => void;
  /** Who `replyTo` was written by — shown on the "Replying to" chip (round 2 #16). */
  replyToBy?: string | null;
  /** Clears the reply target (the chip's ✕). */
  onCancelReply?: () => void;
  /** Initial draft text (a moved draft, e.g. the §4.2 Expand drawer). */
  initialText?: string;
  /** Reports the live draft so a host can move it (Expand) or persist it. */
  onTextChange?: (text: string) => void;
  /** Staged (uploaded, unsent) artifact ids that move with the draft (§4.2 Expand). */
  initialArtifacts?: string[];
  /** Reports the staged artifact ids so a host can move them with the text. */
  onArtifactsChange?: (ids: string[]) => void;
  /** §4.2 "Expand": when given, a control opens the same composer in the right Drawer (or back).
   *  `expanded` says which side this instance is on; `onToggle` moves the draft across. */
  expand?: { expanded: boolean; onToggle: () => void };
  /** "panel" (S19, revision3-clean-review.png feedback column): no card frame, a plain textarea, a
   *  tools row "Mention · Attach · ⤢" and an actions row "<sendLabel> · Cancel". Default "card". */
  variant?: "card" | "panel";
  /** Send button text (panel: "Send feedback"). */
  sendLabel?: string;
  /** Shows a Cancel beside Send (panel variant); the host closes its panel, the draft is kept. */
  onCancel?: () => void;
  /** C19: this is the thread's composer — quotes picked from docs and messages (QuoteLayer) land here
   *  as chips and go out as `quotes[]`. */
  quotes?: boolean;
}

export function Composer(props: ComposerProps): React.JSX.Element {
  return <ComposerInstance key={`${props.ticketId}:${props.replyTo ?? "new"}`} {...props} />;
}

function ComposerInstance({
  ticketId,
  submit = sendMessage,
  lockRecipient = false,
  kinds = ["note"],
  placeholder,
  onSent,
  to: toProp = null,
  replyTo = null,
  showTo = false,
  hideRecipient = false,
  onDirtyChange,
  replyToBy = null,
  onCancelReply,
  initialText = "",
  onTextChange,
  initialArtifacts,
  onArtifactsChange,
  expand,
  variant = "card",
  sendLabel = "Send",
  onCancel,
  quotes: takesQuotes = false,
}: ComposerProps): React.JSX.Element {
  const qc = useQueryClient();
  if (!draftStores.has(qc)) draftStores.set(qc, new Map());
  const conversationDrafts = draftStores.get(qc)!;
  const draftKey = submit === sendMessage ? `${identity()}:${ticketId}:${replyTo ?? "new"}` : null;
  const saved = draftKey ? conversationDrafts.get(draftKey) ?? readDraft(draftKey) : undefined;
  const [text, setText] = useState(saved?.text ?? initialText);
  const selection = useRef(saved?.selection);
  useEffect(() => onTextChange?.(text), [text, onTextChange]);
  const [kind, setKind] = useState<MessageKind>(saved?.kind && kinds.includes(saved.kind as MessageKind) ? saved.kind as MessageKind : kinds[0]);
  const [to, setTo] = useState<string | null>(saved?.to !== undefined ? saved.to : toProp);
  // Human defect #9 (m-a7e74d81b0, 2026-09-10): an @tagged note used to go out with to=None, so
  // the board woke every seat on the ticket instead of the tagged one. The recipient is derived
  // from the FIRST @handle in the text (a known participant), shown pre-filled in the picker and
  // editable; once the writer picks a recipient by hand the text no longer overrides it. A note
  // with no tag stays a ticket broadcast (to=null).
  const [toPicked, setToPicked] = useState<boolean>(saved?.toPicked ?? (toProp != null));
  const [artifacts, setArtifacts] = useState<string[]>(saved?.artifacts ?? initialArtifacts ?? []);
  // R1 (epic-44a0576511): an upload becomes a CHIP under the textarea — filename + remove — never a
  // raw `art-…` token typed into the draft. Names live for the session; a reloaded draft shows ids.
  const names = useRef<Map<string, string>>(new Map());
  useEffect(() => { if (draftKey) { const value = { text, artifacts, kind, to, toPicked, selection: selection.current }; conversationDrafts.set(draftKey, value); writeDraft(draftKey, value); } }, [draftKey, text, artifacts, kind, to, toPicked, conversationDrafts]);
  useEffect(() => onArtifactsChange?.(artifacts), [artifacts, onArtifactsChange]);
  const [confirming, setConfirming] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const helpBtnRef = useRef<HTMLButtonElement>(null);
  const [sentNote, setSentNote] = useState<string | null>(null);
  const [unresolved, setUnresolved] = useState<string[]>([]);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const prior = selection.current;
    if (prior && taRef.current) { taRef.current.focus(); taRef.current.setSelectionRange(prior.start, prior.end); taRef.current.scrollTop = prior.scroll; }
    // A reply remounts the composer: put the caret in it and bring it on screen, else Reply looks
    // like it did nothing (owner 2026-09-20: "the chat hangs when you reply").
    else if (replyTo && taRef.current) { taRef.current.focus(); taRef.current.scrollIntoView?.({ block: "nearest" }); }
  }, [replyTo]);
  const firstKind = useRef(kinds[0]);
  useEffect(() => { if (firstKind.current !== kinds[0]) { setKind(kinds[0]); firstKind.current = kinds[0]; } }, [kinds[0]]);
  const idRef = useRef(`composer-${Math.random().toString(36).slice(2)}`);
  // C19: this thread's quote tray (the chips), and "a Quote goes to this composer" while it is mounted.
  const tray = useQuoteTray(takesQuotes ? ticketId : null);
  useEffect(() => (takesQuotes ? registerQuoteTarget(ticketId) : undefined), [takesQuotes, ticketId]);
  const [badQuote, setBadQuote] = useState<number | null>(null);
  const dirty = text.trim().length > 0 || artifacts.length > 0 || tray.length > 0;

  const previousTo = useRef(toProp);
  useEffect(() => {
    if (previousTo.current === toProp) return;
    previousTo.current = toProp;
    setTo(toProp);
    setToPicked(toProp != null);
  }, [toProp]);
  // Hold the app's live refresh while this composer has an unsent draft (design §4.2 draft guard),
  // and surface the same flag to a parent that wants it.
  useDirtyGuard(idRef.current, dirty, ticketId);
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const people = useQuery({ queryKey: ["me", "people"], queryFn: getPeople, retry: false });
  const mentions = useMentions(people.data ?? [], taRef, setText);

  const mentioned = firstMentionedHandle(text, people.data ?? []);
  useEffect(() => {
    if (toPicked) return;
    setTo(mentioned);
  }, [mentioned, toPicked]);

  // Wake preview — the board's delivery plan for this (to, kind). Reactive so it cannot drift from
  // delivery; nothing is sent (design §16.1). Enabled once there is a target to preview.
  // Round 2 #7: the draft's @mentions are part of the plan, so the preview carries the text (debounced).
  const [previewText, setPreviewText] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setPreviewText(text), 250);
    return () => clearTimeout(t);
  }, [text]);
  const preview = useQuery({
    queryKey: ["resolve", ticketId, to, kind, previewText],
    queryFn: () => resolveMessage({ ticket_id: ticketId, to, kind, text: previewText }),
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

  // Round 2 #8: the mutation carries the draft it SUBMITTED; on success only that draft is cleared —
  // text typed while the post was in flight survives — and a second Ctrl+Enter while pending is a no-op.
  const send = useMutation({
    mutationFn: (draft: { text: string; artifacts: string[]; quotes: typeof tray }) =>
      submit({
        ticket_id: ticketId,
        kind,
        text: draft.text,
        to,
        reply_to: replyTo,
        artifacts: draft.artifacts.length ? draft.artifacts : undefined,
        quotes: draft.quotes.length ? draft.quotes.map((q) => q.quote) : undefined,
      }).then((r) => ({ ...r, draft })),
    onSuccess: ({ value, hint, draft }) => {
      setSentNote(hint || "Sent.");
      setUnresolved(value.unresolved_mentions ?? []);
      setText((t) => (t.trim() === draft.text ? "" : t));
      setArtifacts((a) => a.filter((id) => !draft.artifacts.includes(id)));
      if (draft.quotes.length) quoteTray.removeSent(ticketId, draft.quotes.map((q) => q.key));
      setBadQuote(null);
      setConfirming(false);
      if (draftKey) {
        const remaining = { text: text.trim() === draft.text ? "" : text, artifacts: artifacts.filter((id) => !draft.artifacts.includes(id)), kind, to, toPicked };
        conversationDrafts.set(draftKey, remaining); writeDraft(draftKey, remaining);
      }
      onDirtyChange?.(false);
      onCancelReply?.();
      onSent?.(value);
      for (const queryKey of [["ticket", ticketId], ["epic", ticketId], ["messages", ticketId], ["me", "conversations"], ["me", "replies"], ["me", "summary"]]) {
        void qc.invalidateQueries({ queryKey });
      }
    },
    onError: (e) => {
      // A 422 names the quote the board could not verify ("quotes[1]: …"): that chip is marked.
      const m = /quotes\[(\d+)\]/.exec(e instanceof Error ? e.message : "");
      setBadQuote(m ? Number(m[1]) : null);
    },
  });

  const inFlight = useRef(false); // synchronous guard: isPending flips only on the next render
  function trySend() {
    if (send.isPending || inFlight.current || pendingUploads > 0) return;
    if (text.trim().length === 0 && artifacts.length === 0 && tray.length === 0) return;
    if (needsConfirm && !confirming) {
      setConfirming(true); // one confirm step when a question/deviation would wake nobody
      return;
    }
    inFlight.current = true;
    send.mutate({ text: text.trim(), artifacts: [...artifacts], quotes: [...tray] }, { onSettled: () => (inFlight.current = false) });
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (mentions.onKeyDown(e)) return; // menu nav / accept consumes the key first
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      trySend();
    }
    // plain Enter falls through → a newline (design §4.2: Enter never sends)
  }

  // Drop / paste attach through the shared upload path (promise #19: the Ticket page's documents
  // card and the ruling drawer attach the same way). A refused upload leaves the draft intact.
  const onUploaded = useCallback((art: UploadedArtifact, file?: File) => {
    if (file?.name) names.current.set(art.id, file.name);
    setArtifacts((a) => (a.includes(art.id) ? a : [...a, art.id]));
  }, []);
  const { dragOver, error: uploadError, pending: pendingUploads, retry: retryUpload, clearError: clearUploadError, ingestFiles, dropProps } = useDropUpload(ticketId, onUploaded);
  useEffect(() => {
    if (!pendingUploads && !send.isPending) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [pendingUploads, send.isPending]);

  const kindFixed = kinds.length <= 1;
  const panel = variant === "panel";
  const showRecipient = (showTo || to != null) && !hideRecipient;
  const expandButton = expand ? (
    <button
      type="button"
      className={panel ? styles.tool : styles.expand}
      disabled={pendingUploads > 0 || send.isPending}
      onClick={expand.onToggle}
      aria-label={expand.expanded ? "Collapse the composer back into the page" : "Expand the composer into the drawer"}
      title={panel ? (expand.expanded ? "Collapse" : "Expand") : undefined}
      data-testid="composer-expand"
    >
      <Icon name={expand.expanded ? "collapse" : "expand"} />{panel ? null : <> {expand.expanded ? "Collapse" : "Expand"}</>}
    </button>
  ) : null;
  const sendButton = (
    <button
      className={styles.send}
      type="button"
      disabled={send.isPending || pendingUploads > 0 || (text.trim().length === 0 && artifacts.length === 0 && tray.length === 0)}
      onClick={trySend}
      data-testid="composer-send"
    >
      {confirming ? "Send anyway — wakes nobody" : sendLabel}
    </button>
  );


  return (
    <section
      className={`${styles.composer} ${panel ? styles.panel : ""} ${dragOver ? styles.dragging : ""}`}
      data-testid="composer"
      data-busy={pendingUploads > 0 || send.isPending ? "true" : undefined}
      {...dropProps}
    >
      {dragOver ? <div className={styles.veil} data-testid="drop-veil">Drop to attach</div> : null}

      {replyTo ? (
        <div className={styles.replyChip} data-testid="reply-chip">
          Replying to {replyToBy ? `@${replyToBy}` : replyTo}
          {onCancelReply ? (
            <button type="button" className={styles.replyCancel} onClick={onCancelReply} aria-label="Stop replying" disabled={pendingUploads > 0 || send.isPending}>
              <Icon name="close" />
            </button>
          ) : null}
        </div>
      ) : null}

      {showRecipient || !kindFixed || (expand && !panel) ? <div className={styles.controls}>
        {showRecipient ? (
          <label className={styles.field}>
            <span className={styles.fieldLabel}>To</span>
            <span className={styles.selectWrap}>
              {to ? <Avatar id={to} size={22} className={styles.toAvatar} /> : null}
              <select
                className={to ? styles.withAvatar : undefined}
                disabled={lockRecipient}
                value={to ?? ""}
                onChange={(e) => {
                  setTo(e.target.value || null);
                  setToPicked(e.target.value !== "");
                }}
                aria-label="Recipient"
                data-testid="to-picker"
              >
                <option value="">This conversation</option>
                <ToGroups people={people.data ?? []} />
              </select>
            </span>
          </label>
        ) : null}
        {kindFixed ? null : (
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Type</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as MessageKind)} aria-label="Message kind" data-testid="kind-picker">
              {kinds.map((k) => (
                <option key={k} value={k} title={KIND_GLOSS[k]}>
                  {k === "note" ? "Message" : k[0].toUpperCase() + k.slice(1)}
                </option>
              ))}
            </select>
            {KIND_GLOSS[kind] ? (
              <span className={styles.gloss} data-testid="kind-gloss" hidden={!helpOpen}>
                {KIND_GLOSS[kind]}
              </span>
            ) : null}
          </label>
        )}
        {panel ? null : expandButton}
      </div> : null}

      {takesQuotes ? <QuoteChips ticketId={ticketId} disabled={send.isPending} invalid={badQuote} /> : null}

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
        onPaste={(e) => {
          // A pasted image/file attaches like a drop (adversary finding #10, 2026-09-10).
          const files = Array.from(e.clipboardData?.files ?? []);
          if (files.length) {
            e.preventDefault();
            void ingestFiles(files);
          }
        }}
        onSelect={(e) => {
          selection.current = { start: e.currentTarget.selectionStart, end: e.currentTarget.selectionEnd, scroll: e.currentTarget.scrollTop };
          if (draftKey) { const value = { text, artifacts, kind, to, toPicked, selection: selection.current }; conversationDrafts.set(draftKey, value); writeDraft(draftKey, value); }
        }}
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

      {artifacts.length > 0 ? (
        <ul className={styles.chips} data-testid="attachment-chips" aria-label="Attachments">
          {artifacts.map((id) => (
            <li key={id} className={styles.chip} data-testid="attachment-chip" data-artifact={id}>
              <Icon name="attach" size={16} />
              <span className={styles.chipName}>{names.current.get(id) ?? id}</span>
              <button type="button" className={styles.chipRemove} aria-label={`Remove ${names.current.get(id) ?? id}`}
                disabled={send.isPending} onClick={() => setArtifacts((a) => a.filter((x) => x !== id))}>
                <Icon name="close" size={16} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {pendingUploads > 0 ? <p role="status">Uploading {pendingUploads} attachment(s)… Keep this view open.</p> : null}
      {uploadError ? (
        <p className={styles.error} role="alert">
          Upload failed: {uploadError}. Your draft is kept.
          <button type="button" onClick={retryUpload}>Retry upload</button>
          <button type="button" onClick={clearUploadError}>Remove failed upload</button>
        </p>
      ) : null}

      <div className={styles.footer}>
        <input ref={fileRef} type="file" multiple hidden onChange={(e) => { void ingestFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        <button type="button" className={styles.tool} onClick={() => { const at = taRef.current?.selectionStart ?? text.length; setText((t) => `${t.slice(0, at)}@${t.slice(at)}`); taRef.current?.focus(); requestAnimationFrame(() => { taRef.current?.setSelectionRange(at + 1, at + 1); mentions.refresh(); }); }}><Icon name="mention" /> Mention</button>
        <button type="button" className={styles.tool} onClick={() => fileRef.current?.click()} data-testid="composer-attach"><Icon name="attach" /> Attach</button>
        {panel ? expandButton : null}
        {panel ? null : <button
          ref={helpBtnRef}
          type="button"
          className={styles.tool}
          aria-label="How sending works"
          aria-haspopup="dialog"
          aria-expanded={helpOpen}
          onClick={() => setHelpOpen((o) => !o)}
          data-testid="composer-help-toggle"
        >
          <Icon name="help" />
        </button>}
        {/* Wake preview — the board's plan, verbatim, as the render's one delivery line; every
            per-recipient reason sits in its title. The preview cannot drift from delivery. */}
        {preview.data ? (
          <span className={styles.delivery} data-testid="wake-preview"
            title={preview.data.plan.map((w) => `${w.recipient}${w.alive === false ? " (not alive)" : ""} — ${w.why}`).join("\n") || preview.data.note}>
            {preview.data.plan.length > 0
              ? `Will notify ${preview.data.plan.map((w) => w.recipient).join(", ")}`
              : preview.data.note || "Nobody will be woken."}
          </span>
        ) : <span className={styles.delivery} />}
        {panel ? null : sendButton}
      </div>
      {panel ? (
        <div className={styles.actionsRow}>
          {sendButton}
          {onCancel ? <button type="button" className={styles.cancel} onClick={onCancel} disabled={send.isPending} data-testid="composer-cancel">Cancel</button> : null}
        </div>
      ) : null}

      {helpOpen ? (
        <ComposerHelp
          onClose={() => {
            setHelpOpen(false);
            helpBtnRef.current?.focus();
          }}
        />
      ) : null}

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
            <option key={r} value={r} title={ROLE_GLOSS[r]}>
              {r} · {liveRoles.has(r) ? "seat live" : "no seat yet"}{ROLE_GLOSS[r] ? ` — ${ROLE_GLOSS[r]}` : ""}

            </option>
          ))}
        </optgroup>
      </>
    );
  }
}
