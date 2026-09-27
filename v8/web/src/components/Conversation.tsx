import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "react-router";
import type { MessageAttachment, MessageView } from "../api/types";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { Term } from "./Term";
import { ArtifactVideo, dispositionOf, fetchArtifactContent, isVideoType, MessageText, NotUploaded, openArtifact, PREVIEW_TYPES } from "./ArtifactLink";
import { ThreadHistoryControls, type useThreadHistory } from "./useThreadHistory";
import { pendingWork } from "./PendingNavigation";
import { useScrollToHash } from "./useScrollToHash";
import { useViewerFlag } from "./viewerPrefs";
import { useRetired } from "./useRetired";
import { MessageMarkdown } from "./Markdown";
import { CodeCard } from "./CodeCard";
import { QuoteCard } from "./QuoteCard";
import { quoteRegionRef } from "./QuoteLayer";
import styles from "./Conversation.module.css";
import { dismissAsks, threadAsks, useAttention, type PageItem } from "../api/attention";
import { attentionMark } from "./AttentionDot";
import { ago, highlightMessage, useJumpToMessage } from "./AttentionAsks";

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

/** S10 (owner m-e587ecc667): the thread fills the viewport to its bottom edge. The list keeps its 56vh
 *  cap (it scrolls inside, the composer stays reachable) but gets a floor: the viewport height left
 *  under the list's top, less what sits under it in the section (the composer). Written as
 *  --thread-fill on the section; recomputed when the page, the section or the viewport resizes
 *  (title bar or composer collapse, rail toggle, rewrap). A page taller than the viewport gets no floor. */
function useFillViewport(): React.RefObject<HTMLElement | null> {
  const ref = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const sec = ref.current;
    if (!sec) return;
    const fit = () => {
      const body = sec.querySelector<HTMLElement>("[data-fill]");
      if (!body) return;
      const top = body.getBoundingClientRect().top + window.scrollY;
      const below = sec.getBoundingClientRect().bottom - body.getBoundingClientRect().bottom;
      const fill = `${Math.max(0, Math.floor(document.documentElement.clientHeight - top - below))}px`;
      if (sec.style.getPropertyValue("--thread-fill") !== fill) sec.style.setProperty("--thread-fill", fill);
    };
    fit();
    window.addEventListener("resize", fit);
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    ro?.observe(sec);
    if (sec.parentElement) ro?.observe(sec.parentElement);
    return () => { window.removeEventListener("resize", fit); ro?.disconnect(); };
  }, []);
  return ref;
}

/** Message text without the artifact tokens the cards already render. */
export function stripTokens(text: string, attachments: MessageAttachment[] | undefined): string {
  if (!attachments?.length) return text;
  let out = text;
  for (const a of attachments) out = out.split(a.id).join("");
  return out.replace(/[ \t]{2,}/g, " ").trim();
}

function AttachmentCard({ a }: { a: MessageAttachment }): React.JSX.Element {
  const stored = a.has_content !== false;
  const image = stored && a.form === "image" && PREVIEW_TYPES.has(a.content_type);
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
  const video = stored && isVideoType(a.content_type);
  return (
    <div className={styles.attachment} data-testid="attachment-card" data-artifact={a.id}>
      {video ? <ArtifactVideo id={a.id} label={a.note || name} /> : (
        <Link to={`/artifact/${encodeURIComponent(a.id)}`} className={styles.thumb} aria-label={`Open ${name}`}>
          {url ? <img src={url} alt={a.note || name} loading="lazy" /> : <Icon name={image ? "files" : "attach"} size={24} />}
        </Link>
      )}
      <div className={styles.caption}>
        <span className={styles.filename}>{name}</span>
        <span>{a.note && a.note !== name ? `${a.note} · ` : ""}{image ? "image attachment" : video ? "video attachment" : `${a.form} attachment`}</span>
        {stored ? (
          <button type="button" className={styles.view} onClick={() => void openArtifact(a.id)}>
            <Icon name="external" size={16} /> {image ? "View image" : "Open file"}
          </button>
        ) : <NotUploaded uri={a.uri ?? ""} />}
      </div>
    </div>
  );
}

/** v34 item 3 (owner m-8aa6439a77 "the rest i dont know how to find them"): the asks waiting on the viewer that
 *  sit older than the loaded window. Each row jumps to its message: the #m- hash loads it in place (?include). */
function EarlierWaiting({ items }: { items: PageItem[] }): React.JSX.Element | null {
  const jump = useJumpToMessage();
  if (!items.length) return null;
  return (
    <div className={styles.earlier} data-testid="earlier-waiting" role="group" aria-label={`${items.length} earlier waiting`}>
      <span className={styles.earlierHead}>{items.length} earlier waiting</span>
      {items.map((i) => (
        <button key={i.id} type="button" className={styles.earlierItem} data-testid="earlier-waiting-item" data-ask={i.id}
          onClick={() => jump(i.id)}>
          {i.label}{i.since ? ` · ${ago(i.since)}` : ""}
        </button>
      ))}
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
  const retired = useRetired(); // t-882e4d2eeb: people who left keep their name here, greyed
  useScrollToHash(Boolean(thread.length));
  // S20: the asks waiting on the viewer come from the one attention list (never a rule of this thread's own);
  // a #m-<id> landing (a notification, a Work row, the earlier-waiting bar) highlights that message once loaded.
  const waitingItems = threadAsks(useAttention(), ticketId);
  const asks = new Set(waitingItems.map((i) => i.id));
  const earlier = waitingItems.filter((i) => !byId.has(i.id));
  const qc = useQueryClient();
  // v34 item 6: Dismiss is the no-reply path, a server-side write; refetching the ["me", …] reads clears the rail
  // count, the trail dots and this highlight together (the page reads refresh its header's asks).
  const dismiss = useMutation({
    mutationFn: (id: string) => dismissAsks([id]),
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["me"] }); void qc.invalidateQueries({ queryKey: ["ticket"] });
      void qc.invalidateQueries({ queryKey: ["epic"] }); },
  });
  const { hash } = useLocation();
  const target = hash.startsWith("#m-") ? decodeURIComponent(hash.slice(1)) : null;
  const loaded = Boolean(target && byId.has(target));
  useEffect(() => { if (target && loaded) highlightMessage(target); }, [target, loaded]);
  const last = thread[thread.length - 1]?.at;
  const [composerCollapsed, setComposerCollapsed] = useViewerFlag(viewer, "composer-collapsed");
  const fillRef = useFillViewport();
  return (
    <section ref={fillRef} className={styles.conversation} aria-label="Conversation" data-testid="conversation" data-ticket={ticketId}>
      <div className={styles.heading}>
        <h2>Conversation</h2>
        <span data-testid="conversation-total">{history.total} {history.total === 1 ? "message" : "messages"}</span>
        <button type="button" className={styles.order} onClick={onToggleOrder} data-testid="order-toggle">
          {order === "newest" ? "Newest first" : "Oldest first"}
        </button>
        <span className={styles.end}>{dayLabel(last)}</span>
      </div>
      <ThreadHistoryControls history={history} />
      <EarlierWaiting items={earlier} />
      {ordered.length === 0 ? (
        <p className={styles.empty} data-fill>No messages yet. Write the first one below.</p>
      ) : (
        <ul ref={history.listRef} className={styles.messages} data-fill data-testid="thread" tabIndex={0} aria-label="Conversation messages">
          {ordered.map((m) => {
            const parent = m.reply_to ? byId.get(m.reply_to) : undefined;
            const waiting = asks.has(m.id);
            return (
              <li key={m.id} id={m.id} className={`${styles.msg} ${waiting ? attentionMark : ""}`} data-testid="thread-message"
                data-reply-to={m.reply_to ?? undefined} data-attention={waiting ? "true" : undefined}>
                <Avatar id={m.by} size={36} className={styles.avatar} />
                <div className={styles.body}>
                  <div className={styles.by}>
                    {retired.has(m.by)
                      ? <strong className={styles.retired} title="No longer on this board" data-testid="retired-author">{nameOf(m.by)}</strong>
                      : <strong>{nameOf(m.by)}</strong>}
                    {m.by.includes(".") ? <span className={styles.id}>{m.by}</span> : null}
                    {m.to ? <span className={styles.to}>To {m.to === viewer ? "you" : nameOf(m.to)}</span> : null}
                    {m.kind !== "note" ? <Term category="message_kind" value={m.kind} className={styles.kind} /> : null}
                    {/* v34 item 5: the large highlight is the marker; the tag is a quiet caption, no dot */}
                    {waiting ? <span className={styles.waiting} data-testid="reader-tag">Waiting on you</span> : null}
                    <time dateTime={m.at}>{clock(m.at)}</time>
                    <span className={styles.actions}>
                      {waiting ? (
                        <button type="button" className={styles.reply} data-testid="thread-dismiss"
                          title="Mark as read without replying: it stops waiting on you. The sender is not notified."
                          disabled={dismiss.isPending && dismiss.variables === m.id}
                          onClick={() => dismiss.mutate(m.id)}>
                          <Icon name="check" size={16} /> Dismiss
                        </button>
                      ) : null}
                      <button type="button" className={styles.reply} data-testid="thread-reply"
                        onClick={() => { if (!pendingWork()) { setComposerCollapsed(false); onReply(m); } }}>
                        <Icon name="reply" size={16} /> Reply
                      </button>
                    </span>
                  </div>
                  {parent ? (
                    <p className={styles.quote} data-testid="reply-quote">
                      <span>replying to {parent.by === viewer ? "you" : `@${parent.by}`}:</span> {parent.text.slice(0, 160)}
                    </p>
                  ) : null}
                  {/* S17 c-b1f32f8b33: Markdown from the board's renderer; an older board without
                      `html` keeps the plain linkified text. */}
                  {/* C19: the message's verified quotes, as cards above its text. */}
                  {m.quotes?.map((q, i) => <QuoteCard key={`${m.id}:q${i}`} q={q} />)}
                  {/* C19: the text is a quotable region (QuoteLayer maps a selection back to m.text). */}
                  <div ref={quoteRegionRef({ kind: "message", id: m.id, ticketId, author: m.by, text: m.text })}>
                    {m.html !== undefined
                      ? <MessageMarkdown className={styles.md} html={m.html} strip={m.attachments?.map((a) => a.id)} />
                      : <MessageText className={styles.text} text={stripTokens(m.text, m.attachments)} />}
                  </div>
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
