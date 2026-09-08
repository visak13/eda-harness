import { useState } from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getTicketPage } from "../api/endpoints";
import type { MessageView, TicketStatus } from "../api/types";
import { StatusChip } from "../components/StatusChip";
import { ProcessStrip } from "../components/ProcessStrip";
import { StatusControl } from "../components/StatusControl";
import { AddCriterion } from "../components/CriterionControls";
import { AssignControl } from "../components/AssignControl";
import { GateOpenControl } from "../components/GateOpenControl";
import { LinkDocControl, AskRoleControl } from "../components/TicketAsks";
import { AgentLine } from "../components/AgentLine";
import { CriterionCard } from "../components/CriterionCard";
import { Composer } from "../components/Composer";
import { useDocDrawer } from "../components/DocDrawer";
import { identity } from "../auth/identity";
import ui from "../components/ui.module.css";
import styles from "./Ticket.module.css";

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

  const page = useQuery({ queryKey: ["ticket", id], queryFn: () => getTicketPage(id) });

  if (page.isPending) return <p className={ui.empty}>Loading ticket…</p>;
  if (page.isError)
    return (
      <p className={ui.banner} role="alert">
        Could not load {id}: {(page.error as Error).message}
      </p>
    );

  const { ticket, epic_id, criteria, docs, thread, assignee, waiting_reason } = page.data;
  const ordered = order === "newest" ? [...thread].reverse() : thread;
  const seatLabel = assignee.handle ?? ticket.assignee ?? "unassigned";

  return (
    <div>
      <nav className={styles.crumb} aria-label="Breadcrumb">
        <Link to={`/epic/${encodeURIComponent(epic_id)}`}>← Epic {epic_id}</Link>
      </nav>

      <div className={styles.idline}>
        <span className={ui.idMono}>{ticket.id}</span>
        <StatusChip status={ticket.status} />
      </div>
      <h1 className={styles.title}>{ticket.title}</h1>
      {ticket.description ? <p className={styles.desc}>{ticket.description}</p> : null}
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

      <div className={styles.layout}>
        <div className={styles.mainCol}>
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
                    c.verdict === "pending" && c.evidence_ref && c.evidence_version != null
                      ? { evidenceVersion: c.evidence_version }
                      : undefined
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

          <div className={styles.threadHead}>
            <span className={ui.sectionLabel}>Conversation ({thread.length})</span>
            <button
              type="button"
              className={styles.orderToggle}
              onClick={() => setOrder((o) => (o === "newest" ? "oldest" : "newest"))}
              data-testid="order-toggle"
            >
              {order === "newest" ? "Newest first" : "Oldest first"}
            </button>
          </div>
          <Composer ticketId={id} kinds={["note"]} placeholder={`Message this conversation as @${as}`} />
          {ordered.length === 0 ? (
            <p className={ui.empty}>No messages on this ticket yet.</p>
          ) : (
            <ul className={styles.messages} data-testid="thread">
              {ordered.map((m: MessageView) => (
                <li key={m.id} className={styles.message}>
                  <AgentLine by={m.by} kind={m.kind} to={m.to} viewer={as} at={m.at} />
                  <div className={styles.messageText}>{m.text}</div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <aside className={styles.rail} aria-label="Ticket details">
          <section className={ui.card} id="change-status">
            <div className={ui.sectionLabel}>Change status</div>
            <StatusControl ticketId={id} currentStatus={ticket.status as TicketStatus} />
          </section>

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Seat</div>
            <AssignControl ticketId={id} currentAssignee={assignee.handle ?? ticket.assignee ?? null} />
          </section>

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

          <section className={ui.card}>
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
                {ticket.kind} / {ticket.work_type}
              </span>
            </div>
            <div className={ui.metaRow}>
              <span>Waiting</span>
              <span>{waiting_reason.reason || "—"}</span>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
