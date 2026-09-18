import { useCallback, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getTicketPage } from "../api/endpoints";
import type { MessageView, TicketStatus, UploadedArtifact } from "../api/types";
import { StatusChip } from "../components/StatusChip";
import { ProcessStrip } from "../components/ProcessStrip";
import { StatusControl } from "../components/StatusControl";
import { AddCriterion } from "../components/CriterionControls";
import { AssignControl } from "../components/AssignControl";
import { GateOpenControl } from "../components/GateOpenControl";
import { GateForm } from "../components/GateForm";
import { LinkDocControl, AskRoleControl } from "../components/TicketAsks";
import { AgentLine } from "../components/AgentLine";
import { Term } from "../components/Term";
import { CriterionCard } from "../components/CriterionCard";
import { Composer } from "../components/Composer";
import { Drawer } from "../components/Drawer";
import { useScrollToHash } from "../components/useScrollToHash";
import { copyProps } from "../copy/pages";
import { useDocDrawer } from "../components/DocDrawer";
import { identity } from "../auth/identity";
import ui from "../components/ui.module.css";
import { ArtifactLink, MessageText } from "../components/ArtifactLink";
import { useDropUpload } from "../components/useDropUpload";
import { Clamp } from "../components/Clamp";
import styles from "./Ticket.module.css";
import { Icon } from "../components/Icon";
import { ContextualWork } from "../components/ContextualWork";
import { useThreadHistory, ThreadHistoryControls } from "../components/useThreadHistory";
import { pendingWork } from "../components/PendingNavigation";

// Ticket page (design §4.2, criteria c-d2dbb34b06 / c-e0b24cd134): crumb to the epic, id + status
// chip, title, description, tags, the resolved assignee with its seat state, the criteria as
// read-only cards (verdict word + evidence link, opening in the doc drawer), the linked documents
// with their relation labels (also drawer), and an object-attached composer whose "as @x" mirrors
// the ?as= identity. A note posts to THIS ticket (parity with /ui/ticket/{id}/say).
// The process strip's next action links to the status control below rather than repeating the
// board's rules — the control is where the legal move actually lives (design §16).
function nextActionLink(status: string): string {
  switch (status) {
    case "in_review": return "Review the evidence, then change the status →";
    case "in_progress": return "Attach evidence, then move it to In review →";
    case "ready": return "Assign or spawn a seat, then start it →";
    case "done": return "Complete — see the status below.";
    default: return "Change the status →";
  }
}

export function TicketPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const as = identity();
  const [order, setOrder] = useState<"newest" | "oldest">("newest");
  const drawer = useDocDrawer();
  // Round 2 #16: a reply is a THREADED reply — the Reply action on a message carries reply_to and
  // the sender into the composer; an @tag alone never picks a parent.
  const [reply, setReply] = useState<{ id: string; by: string } | null>(null);
  const composerRef = useRef<HTMLDivElement>(null);

  // §4.2 "Expand" (promise #15): the SAME composer opens inside the right Drawer. The draft (text +
  // staged artifacts) is mirrored into a ref by the mounted instance and handed to the next one as
  // its initial state, so it moves out on Expand and back on Collapse. `?compose=1` carries the
  // expanded state, so a refresh or a shared link reopens the drawer with the composer in it.
  const [params, setParams] = useSearchParams();
  const composeExpanded = params.get("compose") === "1" && !params.get("doc");
  const setComposeExpanded = useCallback(
    (on: boolean) =>
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          if (on) p.set("compose", "1");
          else p.delete("compose");
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );

  // Promise #19: the "Linked documents" card is a drop target. A dropped file goes through the
  // composer's upload path (POST /v1/artifacts/upload against this ticket) and the new artifact is
  // listed right there under "Attached files", openable through the authenticated ArtifactLink.
  const [attached, setAttached] = useState<UploadedArtifact[]>([]);
  const onAttached = useCallback((art: UploadedArtifact) => setAttached((a) => [...a, art]), []);
  const docsDrop = useDropUpload(id, onAttached);

  // A deep-linked message (#m-…) is always fetched, even outside the newest-100 window (round 2 #5/#13).
  const { hash } = useLocation();
  const include = hash.startsWith("#m-") ? hash.slice(1) : null;
  const page = useQuery({ queryKey: ["ticket", id, include], queryFn: () => getTicketPage(id, include) });
  const history = useThreadHistory(id, page.data);
  useScrollToHash(Boolean(page.data?.thread.length)); // before the early returns: hooks run every render

  if (page.isPending) return <p className={ui.empty}>Loading ticket…</p>;
  if (page.isError)
    return (
      <p className={ui.banner} role="alert">
        Could not load {id}: {(page.error as Error).message}
      </p>
    );

  const { ticket, epic_id, criteria, docs, assignee, waiting_reason, open_gates } = page.data;
  const thread = history.messages;
  const ordered = order === "newest" ? [...thread].reverse() : thread;
  // A reply is shown attached to the message it answers (human #3 widened, 2026-09-10): the
  // thread is flat on the wire (reply_to), so the parent is quoted above the reply in one line.
  const byId = new Map(thread.map((m) => [m.id, m]));
  const seatLabel = assignee.handle ?? ticket.assignee ?? "unassigned";

  // One composer definition for both hosts (inline / drawer); the key remounts it across the move
  // so `initialText` / `initialArtifacts` are read from the mirrored draft.
  const composer = (expanded: boolean) => (
    <Composer
      key={`${reply?.id ?? "new"}:${expanded ? "drawer" : "inline"}`}
      ticketId={id}
      kinds={reply ? ["answer", "note", "question", "steer", "finding", "status", "deviation"] : ["note", "question", "steer", "finding", "status", "deviation", "answer"]}
      showTo
      to={reply ? reply.by : null}
      replyTo={reply?.id ?? null}
      replyToBy={reply?.by ?? null}
      onCancelReply={() => setReply(null)}
      placeholder={reply ? `Reply to @${reply.by}` : `Message this conversation as @${as}`}
      expand={{ expanded, onToggle: () => setComposeExpanded(!expanded) }}
    />
  );

  return (
    <div>
      <nav className={styles.crumb} aria-label="Breadcrumb">
        <Link to={`/epic/${encodeURIComponent(epic_id)}`}><Icon name="back" /> Epic {epic_id}</Link>
      </nav>

      <div className={styles.idline}>
        <span className={ui.idMono}>{ticket.id}</span>
        <StatusChip status={ticket.status} />
      </div>
      <h1 className={`${styles.title} ${ticket.title.length > 90 ? styles.titleLong : ""}`}>{ticket.title}</h1>
      <ContextualWork ticketId={id} />
      <details id="work-details"><summary>Work description, tags and process</summary>
      {ticket.description ? <Clamp className={styles.desc} text={ticket.description} lines={4} testId="description" /> : null}
      {ticket.tags.length > 0 ? (
        <div className={styles.tags}>
          {ticket.tags.map((t) => (
            <span key={t} className={ui.tag}>
              {t}
            </span>
          ))}
        </div>
      ) : null}

      <div className={styles.seat} data-testid="assignee">
        <span className={styles.seatName}>{seatLabel}</span>
        {assignee.role ? <span className={ui.tag}>{assignee.role}</span> : null}
        <span className={styles.seatState}>
          {waiting_reason.presence ? `${waiting_reason.presence}` : "no live shell"}
        </span>
      </div>

      <ProcessStrip
        status={ticket.status}
        nextAction={<a href="#change-status">{nextActionLink(ticket.status)}</a>}
      />

      </details>
      <div className={styles.layout}>
        <div className={styles.mainCol}>
          <details><summary>Acceptance criteria & evidence ({criteria.length})</summary>
          <div className={ui.sectionLabel}>Acceptance criteria ({criteria.length})</div>
          {criteria.length === 0 ? (
            <p className={ui.empty}>No acceptance criteria have been added.</p>
          ) : (
            <div className={styles.criteria}>
              {criteria.map((c) => (
                <CriterionCard
                  key={c.id}
                  criterion={c}
                  ticketId={id}
                  // A pending criterion that already carries evidence is ready to verdict — show the
                  // one-click ruling pane (design §16 "Record verdict"; the board refuses a non-checker
                  // and the card shows why). One without evidence yet can still be reworded in place.
                  ruling={
                    c.verdict === "pending" && c.evidence_ref ? { evidenceVersion: c.evidence_version ?? null } : undefined
                  }
                  // The board freezes a criterion's text only after a verdict (board.py:830) — a
                  // PENDING criterion is rewordable whether or not it already carries evidence. Mirror
                  // exactly that rule, so the page never hides a move the board would allow.
                  canReword={c.verdict === "pending"}
                  onOpenEvidence={(docId) => drawer.openDoc(docId)}
                />
              ))}
            </div>
          )}

          <details className={styles.addCrit}>
            <summary className={styles.addCritSummary}>Add an acceptance criterion</summary>
            <AddCriterion ticketId={id} />
          </details>

          </details>
          <ThreadHistoryControls history={history} />
          <div className={styles.threadHead} {...copyProps("ticket", "thread")}>
            <span className={ui.sectionLabel}>Conversation ({history.total})</span>
            <button
              type="button"
              className={styles.orderToggle}
              onClick={() => setOrder((o) => (o === "newest" ? "oldest" : "newest"))}
              data-testid="order-toggle"
            >
              {order === "newest" ? "Newest first" : "Oldest first"}
            </button>
          </div>
          <div ref={composerRef}>
            {composeExpanded ? (
              <p className={styles.composeAway} data-testid="composer-expanded-note">
                The composer is open in the drawer.{" "}
                <button type="button" className={styles.composeBack} onClick={() => setComposeExpanded(false)}>
                  Bring it back here
                </button>
              </p>
            ) : (
              composer(false)
            )}
          </div>
          <Drawer open={composeExpanded} onClose={() => setComposeExpanded(false)} title={`Message ${ticket.id}`}>
            {composeExpanded ? <div data-testid="composer-drawer">{composer(true)}</div> : null}
          </Drawer>
          {ordered.length === 0 ? (
            <p className={ui.empty}>No messages on this ticket yet.</p>
          ) : (
            <ul ref={history.listRef} className={styles.messages} data-testid="thread" tabIndex={0} aria-label="Conversation messages">
              {ordered.map((m: MessageView) => (
                <li key={m.id} id={m.id} className={styles.message} data-testid="thread-message" data-reply-to={m.reply_to ?? undefined}>
                  <AgentLine by={m.by} kind={m.kind} to={m.to} viewer={as} at={m.at} />
                  {m.reply_to && byId.get(m.reply_to) ? (
                    <p className={styles.replyQuote} data-testid="reply-quote">
                      <span className={styles.replyQuoteWho}>
                        replying to {byId.get(m.reply_to)!.by === as ? "you" : `@${byId.get(m.reply_to)!.by}`}:
                      </span>{" "}
                      {byId.get(m.reply_to)!.text.slice(0, 160)}
                    </p>
                  ) : null}
                  <MessageText className={styles.messageText} text={m.text} />
                  <button
                    type="button"
                    className={styles.replyBtn}
                    data-testid="thread-reply"
                    onClick={() => {
                      if (pendingWork()) return;
                      setReply({ id: m.id, by: m.by });
                      composerRef.current?.scrollIntoView({ block: "nearest" });
                      composerRef.current?.querySelector("textarea")?.focus();
                    }}
                  >
                    Reply
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <details><summary>Actions & ticket details</summary><aside className={styles.rail} aria-label="Ticket details">
          <section className={ui.card} id="change-status" {...copyProps("ticket", "process-strip")}>
            <div className={ui.sectionLabel}>Change status</div>
            <StatusControl ticketId={id} currentStatus={ticket.status as TicketStatus} />
          </section>

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Seat</div>
            <AssignControl ticketId={id} currentAssignee={assignee.handle ?? ticket.assignee ?? null} />
          </section>

          {open_gates.length > 0 ? (
            <section className={ui.card} data-testid="answer-gates">
              <div className={ui.sectionLabel}>Answer a decision ({open_gates.length})</div>
              {open_gates.filter((g) => g.gate !== "design_signoff").map((g) => (
                <GateForm key={`${g.ticket_id}:${g.gate}`} gate={g} />
              ))}
            </section>
          ) : null}

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Raise a decision</div>
            <GateOpenControl ticketId={id} />
          </section>

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Link &amp; ask</div>
            <LinkDocControl ticketId={id} />
            <div className={styles.controlGap} />
            <AskRoleControl ticketId={id} />
          </section>

          <section
            className={`${ui.card} ${styles.dropTarget} ${docsDrop.dragOver ? styles.dragging : ""}`}
            data-testid="linked-documents"
            {...copyProps("ticket", "documents")}
            {...docsDrop.dropProps}
          >
            {docsDrop.dragOver ? (
              <div className={styles.dropVeil} data-testid="drop-veil">
                Drop to attach to {ticket.id}
              </div>
            ) : null}
            <div className={ui.sectionLabel}>Linked documents ({docs.length})</div>
            {docs.length === 0 ? (
              <p className={ui.empty}>No documents linked.</p>
            ) : (
              <ul className={styles.docList}>
                {docs.map((d) => (
                  <li key={d.id}>
                    <button type="button" className={styles.docRow} onClick={() => drawer.openDoc(d.id)}>
                      <span className={ui.tag}>{(d.relation ?? d.doc_type).replace(/_/g, " ")}</span>
                      <span className={styles.docTitle}>{d.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {attached.length > 0 ? (
              <>
                <div className={`${ui.sectionLabel} ${styles.dropHint}`}>Attached files ({attached.length})</div>
                <ul className={styles.attachedList} data-testid="attached-artifacts">
                  {attached.map((a) => (
                    <li key={a.id} data-testid="attached-artifact">
                      <span className={ui.tag}>{a.form}</span> <ArtifactLink id={a.id} />
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            {docsDrop.error ? (
              <p className={styles.uploadError} role="alert">
                Upload failed: {docsDrop.error}.
              </p>
            ) : null}
            <p className={styles.dropHint}>Drop a file here to attach it to this ticket.</p>
          </section>

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Details</div>
            <div className={ui.metaRow}>
              <span>Design</span>
              {ticket.design_ref ? (
                <button type="button" className={styles.docLink} onClick={() => drawer.openDoc(ticket.design_ref!)}>
                  {ticket.design_ref}
                </button>
              ) : (
                <span>Not linked</span>
              )}
            </div>
            <div className={ui.metaRow}>
              <span>Kind</span>
              <span>
                <Term category="ticket_kind" value={ticket.kind} /> /{" "}
                <Term category="work_type" value={ticket.work_type} />
              </span>
            </div>
            <div className={ui.metaRow}>
              <span>Waiting</span>
              <span>{waiting_reason.reason || "—"}</span>
            </div>
          </section>
        </aside></details>
      </div>
    </div>
  );
}
