import { useEffect, useState } from "react";
import { Link } from "react-router";
import type { MessageAttachment, MessageView } from "../api/types";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { Term } from "./Term";
import { dispositionOf, fetchArtifactContent, MessageText, openArtifact, PREVIEW_TYPES } from "./ArtifactLink";
import { ThreadHistoryControls, type useThreadHistory } from "./useThreadHistory";
import { pendingWork } from "./PendingNavigation";
import { useScrollToHash } from "./useScrollToHash";
import { useViewerFlag } from "./viewerPrefs";
import { MessageMarkdown } from "./Markdown";
import { CodeCard } from "./CodeCard";
import styles from "./Conversation.module.css";

// The conversation canvas per revision3-clean-epic.png: "Conversation · N messages · Today" and a
// continuous run of messages (36px avatar, bold name, "To x", time, Reply on the right), with an
// attachment CARD (thumbnail, filename, "View image") under a message that carries artifacts —
// never the raw `art-…` token in the text (owner defect m-f33ab9207d). The composer sits under
// the run, in flow, always mounted; the page owns it and passes it as `composer`.

function nameOf(by: string): string {
  return by.includes(".") ? by.split(".")[0] : by;
}

function clock(at: string): string {
  const d = new Date(at);
  if (!Number.isFinite(d.getTime())) return at.slice(11, 16);
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(d);
}

function dayLabel(at: string | undefined): string {
  if (!at) return "";
  const d = new Date(at);
  if (!Number.isFinite(d.getTime())) return "";
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return "Today";
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(d);
}

/** Message text without the artifact tokens the cards already render. */
export function stripTokens(text: string, attachments: MessageAttachment[] | undefined): string {
  if (!attachments?.length) return text;
  let out = text;
  for (const a of attachments) out = out.split(a.id).join("");
  return out.replace(/[ \t]{2,}/g, " ").trim();
}

function AttachmentCard({ a }: { a: MessageAttachment }): React.JSX.Element {
  const image = a.form === "image" && PREVIEW_TYPES.has(a.content_type);
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!image) return;
    let cancelled = false, blobUrl: string | null = null;
    void fetchArtifactContent(a.id).then(async (res) => {
      if (!dispositionOf(res).inline) return;
      const blob = await res.blob();
      if (cancelled) return;
      blobUrl = URL.createObjectURL(blob); setUrl(blobUrl);
    }).catch(() => {});
    return () => { cancelled = true; if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [a.id, image]);
  const name = a.filename || a.note || a.id;
  return (
    <div className={styles.attachment} data-testid="attachment-card" data-artifact={a.id}>
      <Link to={`/artifact/${encodeURIComponent(a.id)}`} className={styles.thumb} aria-label={`Open ${name}`}>
        {url ? <img src={url} alt={a.note || name} loading="lazy" /> : <Icon name={image ? "files" : "attach"} size={24} />}
      </Link>
      <div className={styles.caption}>
        <span className={styles.filename}>{name}</span>
        <span>{a.note && a.note !== name ? `${a.note} · ` : ""}{image ? "image attachment" : `${a.form} attachment`}</span>
        <button type="button" className={styles.view} onClick={() => void openArtifact(a.id)}>
          <Icon name="external" size={16} /> {image ? "View image" : "Open file"}
        </button>
      </div>
    </div>
  );
}

export function Conversation({ ticketId, history, order, onToggleOrder, onReply, composer, viewer }: {
  ticketId: string;
  history: ReturnType<typeof useThreadHistory>;
  order: "newest" | "oldest";
  onToggleOrder: () => void;
  onReply: (m: MessageView) => void;
  composer: React.ReactNode;
  viewer: string;
}): React.JSX.Element {
  const thread = history.messages;
  const ordered = order === "newest" ? [...thread].reverse() : thread;
  const byId = new Map(thread.map((m) => [m.id, m]));
  useScrollToHash(Boolean(thread.length));
  const last = thread[thread.length - 1]?.at;
  const [composerCollapsed, setComposerCollapsed] = useViewerFlag(viewer, "composer-collapsed");
  return (
    <section className={styles.conversation} aria-label="Conversation" data-testid="conversation" data-ticket={ticketId}>
      <div className={styles.heading}>
        <h2>Conversation</h2>
        <span data-testid="conversation-total">{history.total} {history.total === 1 ? "message" : "messages"}</span>
        <button type="button" className={styles.order} onClick={onToggleOrder} data-testid="order-toggle">
          {order === "newest" ? "Newest first" : "Oldest first"}
        </button>
        <span className={styles.end}>{dayLabel(last)}</span>
      </div>
      <ThreadHistoryControls history={history} />
      {ordered.length === 0 ? (
        <p className={styles.empty}>No messages yet. Write the first one below.</p>
      ) : (
        <ul ref={history.listRef} className={styles.messages} data-testid="thread" tabIndex={0} aria-label="Conversation messages">
          {ordered.map((m) => {
            const parent = m.reply_to ? byId.get(m.reply_to) : undefined;
            const waiting = m.kind === "question" && m.to === viewer;
            return (
              <li key={m.id} id={m.id} className={styles.msg} data-testid="thread-message" data-reply-to={m.reply_to ?? undefined}>
                <Avatar id={m.by} size={36} className={styles.avatar} />
                <div className={styles.body}>
                  <div className={styles.by}>
                    <strong>{nameOf(m.by)}</strong>
                    {m.by.includes(".") ? <span className={styles.id}>{m.by}</span> : null}
                    {m.to ? <span className={styles.to}>To {m.to === viewer ? "you" : nameOf(m.to)}</span> : null}
                    {m.kind !== "note" ? <Term category="message_kind" value={m.kind} className={styles.kind} /> : null}
                    {waiting ? <span className={styles.waiting} data-testid="reader-tag">Waiting on you</span> : null}
                    <time dateTime={m.at}>{clock(m.at)}</time>
                    <button type="button" className={styles.reply} data-testid="thread-reply"
                      onClick={() => { if (!pendingWork()) { setComposerCollapsed(false); onReply(m); } }}>
                      <Icon name="reply" size={16} /> Reply
                    </button>
                  </div>
                  {parent ? (
                    <p className={styles.quote} data-testid="reply-quote">
                      <span>replying to {parent.by === viewer ? "you" : `@${parent.by}`}:</span> {parent.text.slice(0, 160)}
                    </p>
                  ) : null}
                  {/* S17 c-b1f32f8b33: Markdown from the board's renderer; an older board without
                      `html` keeps the plain linkified text. */}
                  {m.html !== undefined
                    ? <MessageMarkdown className={styles.md} html={m.html} strip={m.attachments?.map((a) => a.id)} />
                    : <MessageText className={styles.text} text={stripTokens(m.text, m.attachments)} />}
                  {m.code_context ? <CodeCard c={m.code_context} /> : null}
                  {m.attachments?.map((a) => <AttachmentCard key={a.id} a={a} />)}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <div className={styles.composer} data-testid="conversation-composer" data-collapsed={composerCollapsed || undefined}>
        {/* S17 c-7a3c3ec439: MS-Word-style collapse of the message box, remembered per viewer. The
            composer stays MOUNTED while collapsed (hidden, not unmounted), so a draft, its
            attachments and pending uploads survive a collapse/expand. */}
        <div className={styles.composerBar}>
          {/* S-UI c-cb386d6be1: minimized, the box is ONE slim bar (prompt + expand chevron in the same
              control) with no band under it; expanded, the small tab on the top edge collapses it. */}
          {composerCollapsed ? (
            <button type="button" className={styles.composerCollapsedBar} data-testid="composer-collapsed-bar"
              aria-expanded={false} aria-controls={`composer-body-${ticketId}`}
              aria-label="Expand message box" title="Expand message box"
              onClick={() => setComposerCollapsed(false)}>
              <Icon name="edit" size={16} /> <span className={styles.collapsedPrompt}>Write a message…</span>
              <span className={styles.chevronUp} aria-hidden="true"><Icon name="chevron" size={16} /></span>
            </button>
          ) : (
            <button type="button" className={styles.composerToggle} data-testid="composer-collapse"
              aria-expanded aria-controls={`composer-body-${ticketId}`}
              aria-label="Collapse message box" title="Collapse message box"
              onClick={() => setComposerCollapsed(true)}>
              <span className={styles.chevronDown} aria-hidden="true"><Icon name="chevron" size={18} /></span>
            </button>
          )}
        </div>
        <div id={`composer-body-${ticketId}`} hidden={composerCollapsed}>{composer}</div>
      </div>
    </section>
  );
}
