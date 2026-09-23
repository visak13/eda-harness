import { useCallback, useState } from "react";
import { useLocation, useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getTicketPage, finalizeArtifacts } from "../api/endpoints";
import type { MessageView, TicketStatus, UploadedArtifact } from "../api/types";
import { ProcessStrip, nextActionFor } from "../components/ProcessStrip";
import { StatusControl } from "../components/StatusControl";
import { AddCriterion } from "../components/CriterionControls";
import { AssignControl } from "../components/AssignControl";
import { SpawnSeatForm } from "../components/SpawnSeatForm";
import { GateOpenControl } from "../components/GateOpenControl";
import { GateForm, useRetainedGates } from "../components/GateForm";
import { LinkDocControl, AskRoleControl } from "../components/TicketAsks";
import { Term } from "../components/Term";
import { CriterionCard } from "../components/CriterionCard";
import { Composer } from "../components/Composer";
import { ExpandableComposer } from "../components/ExpandableComposer";
import { copyItem, copyProps } from "../copy/pages";
import { useDocDrawer } from "../components/DocDrawer";
import { identity } from "../auth/identity";
import ui from "../components/ui.module.css";
import { ArtifactLink } from "../components/ArtifactLink";
import { useDropUpload } from "../components/useDropUpload";
import styles from "./Ticket.module.css";
import { useThreadHistory } from "../components/useThreadHistory";
import { WorkHeader } from "../components/WorkHeader";
import { ActionsMenu, type ActionItem } from "../components/ActionsMenu";
import { Conversation } from "../components/Conversation";

// Ticket page (design-a2e5369133): the SAME WorkHeader as the epic (owner defect: "placeholder
// ticket page … even the universal theme isn't applied"), the conversation under it, controls
// under Actions ▾, and the description / tags / criteria / process ladder / linked documents
// behind the Work link.

const KINDS_DEFAULT = ["note", "question", "steer", "finding", "status", "deviation", "answer"] as const;
const KINDS_REPLY = ["answer", "note", "question", "steer", "finding", "status", "deviation"] as const;

export function TicketPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const as = identity();
  const [order, setOrder] = useState<"newest" | "oldest">("newest");
  const drawer = useDocDrawer();
  const [reply, setReply] = useState<{ id: string; by: string } | null>(null);
  const [attached, setAttached] = useState<UploadedArtifact[]>([]);
  const qc = useQueryClient();
  // Finding 11: a file dropped on the ticket's Files card must REALLY attach. The upload is staged;
  // finalise it onto the ticket (unstaged + `produced` link) before we show it, so it lands in
  // Files & evidence and survives reload instead of lingering staged until the 24 h sweep. A
  // finalise failure rejects so useDropUpload surfaces the reason and keeps the file retryable.
  // Consult claim 6: invalidate the mounted ["contextual", id] query so the Files & evidence pane
  // refetches the board's truth — the optimistic `attached` row alone left the open pane stale.
  const onAttached = useCallback(async (art: UploadedArtifact) => {
    await finalizeArtifacts([art.id], id);
    setAttached((a) => [...a, { ...art, staged: false }]);
    void qc.invalidateQueries({ queryKey: ["contextual", id] });
  }, [id, qc]);
  const docsDrop = useDropUpload(id, onAttached);

  const { hash } = useLocation();
  const include = hash.startsWith("#m-") ? hash.slice(1) : null;
  const page = useQuery({ queryKey: ["ticket", id, include], queryFn: () => getTicketPage(id, include) });
  const history = useThreadHistory(id, page.data);
  // S22: before the early returns (a hook); keeps a gate answered elsewhere while its ruling is unsent.
  const gates = useRetainedGates((page.data?.open_gates ?? []).filter((g) => g.gate !== "design_signoff"));

  if (page.isPending) return <p className={ui.empty}>Loading ticket…</p>;
  if (page.isError)
    return (
      <p className={ui.banner} role="alert">
        Could not load {id}: {(page.error as Error).message}
      </p>
    );

  const { ticket, epic_id, criteria, docs, assignee, waiting_reason } = page.data;
  const seat = assignee.handle ?? ticket.assignee ?? null;
  const gloss = (k: string) => copyItem("ticket", k).text;

  const actions: ActionItem[] = [
    { key: "change-status", label: "Change status", gloss: gloss("process-strip"), copy: copyProps("ticket", "process-strip"),
      render: () => <StatusControl ticketId={id} currentStatus={ticket.status as TicketStatus} /> },
    { key: "assign-spawn", label: "Assign or spawn a seat", gloss: copyItem("epic", "assign-spawn").text,
      render: () => <AssignControl ticketId={id} currentAssignee={seat} /> },
    ...(gates.length ? [{ key: "answer-decision", label: "Answer a decision", count: gates.length, gloss: copyItem("epic", "answer-decision").text,
      render: () => <>{gates.map(({ gate: g, closed, onDismiss }) => <GateForm key={`${g.ticket_id}:${g.gate}`} gate={g} closed={closed} onDismiss={onDismiss} />)}</> } as ActionItem] : []),
    ...(ticket.kind === "story" ? [{ key: "spawn-seat", label: "Spawn seat", gloss: copyItem("ticket", "spawn-seat").text,
      render: () => <SpawnSeatForm ticketId={id} roles={["engineer", "qa", "adversary"]} /> } as ActionItem] : []),
    { key: "raise-decision", label: "Raise a decision", gloss: copyItem("epic", "raise-decision").text,
      render: () => <GateOpenControl ticketId={id} /> },
    { key: "ask-role", label: "Ask a role", gloss: copyItem("epic", "ask-role").text,
      render: () => <AskRoleControl ticketId={id} /> },
    { key: "link-doc", label: "Link a document", gloss: gloss("documents"), copy: copyProps("ticket", "documents"),
      render: () => <LinkDocControl ticketId={id} /> },
    { key: "add-criterion", label: "Add an acceptance criterion", gloss: gloss("criteria"),
      render: () => <AddCriterion ticketId={id} /> },
    { key: "record", label: "Record ids", gloss: "the ticket's id, kind, work type and raw status, for a message or a shell.",
      render: () => <dl className={styles.record}>
        <div><dt>Id</dt><dd className={ui.idMono}>{ticket.id}</dd></div>
        <div><dt>Epic</dt><dd className={ui.idMono}>{epic_id}</dd></div>
        <div><dt>Kind</dt><dd><Term category="ticket_kind" value={ticket.kind} /> / <Term category="work_type" value={ticket.work_type} /></dd></div>
        <div><dt>Status</dt><dd>{ticket.status}</dd></div>
        <div><dt>Waiting</dt><dd>{waiting_reason.reason || "—"}</dd></div>
      </dl> },
  ];

  const work = (
    <div className={styles.work} data-testid="ticket-work">
      {ticket.description ? <section>
        <div className={ui.sectionLabel}>Description</div>
        <p className={styles.desc} data-testid="description">{ticket.description}</p>
        {ticket.tags.length > 0 ? <div className={styles.tags}>{ticket.tags.map((t) => <span key={t} className={ui.tag}>{t}</span>)}</div> : null}
      </section> : null}
      <section data-testid="assignee">
        <div className={ui.sectionLabel}>Seat</div>
        <div className={styles.seat}>
          <span className={styles.seatName}>{seat ?? "unassigned"}</span>
          {assignee.role ? <span className={ui.tag}>{assignee.role}</span> : null}
          <span className={styles.seatState}>{waiting_reason.presence ? waiting_reason.presence : "no live shell"}</span>
        </div>
      </section>
      <section>
        <div className={ui.sectionLabel}>Process</div>
        <ProcessStrip status={ticket.status} nextAction={<span>{nextActionFor(ticket.status)} Change it under Actions → Change status.</span>} />
      </section>
      <section>
        <div className={ui.sectionLabel}>Acceptance criteria ({criteria.length})</div>
        {criteria.length === 0 ? (
          <p className={ui.empty}>No acceptance criteria have been added. Add one under Actions.</p>
        ) : (
          <div className={styles.criteria}>
            {criteria.map((c) => (
              <CriterionCard key={c.id} criterion={c} ticketId={id}
                ruling={c.verdict === "pending" && c.evidence_ref ? { evidenceVersion: c.evidence_version ?? null } : undefined}
                canReword={c.verdict === "pending"} onOpenEvidence={(docId) => drawer.openDoc(docId)} />
            ))}
          </div>
        )}
      </section>
      <section
        className={`${styles.dropTarget} ${docsDrop.dragOver ? styles.dragging : ""}`}
        data-testid="linked-documents" {...copyProps("ticket", "documents")} {...docsDrop.dropProps}>
        {docsDrop.dragOver ? <div className={styles.dropVeil} data-testid="drop-veil">Drop to attach to {ticket.id}</div> : null}
        <div className={ui.sectionLabel}>Linked documents ({docs.length})</div>
        {docs.length === 0 ? <p className={ui.empty}>No documents linked.</p> : (
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
              {attached.map((a) => <li key={a.id} data-testid="attached-artifact"><span className={ui.tag}>{a.form}</span> <ArtifactLink id={a.id} /></li>)}
            </ul>
          </>
        ) : null}
        {docsDrop.error ? <p className={styles.uploadError} role="alert">Upload failed: {docsDrop.error}.</p> : null}
        <p className={styles.dropHint}>Drop a file here to attach it to this ticket.</p>
      </section>
    </div>
  );

  const composer = (
    <ExpandableComposer title={`Message ${ticket.id}`}>{(expand) => (
      <Composer
        key={reply?.id ?? "new"}
        ticketId={id}
        kinds={[...(reply ? KINDS_REPLY : KINDS_DEFAULT)]}
        showTo to={reply ? reply.by : null} replyTo={reply?.id ?? null} replyToBy={reply?.by ?? null}
        onCancelReply={() => setReply(null)}
        placeholder={reply ? `Reply to @${reply.by}` : `Write a message as @${as}… use @ to mention someone.`}
        expand={expand}
      />
    )}</ExpandableComposer>
  );

  return (
    <div className={styles.page}>
      <WorkHeader
        ticketId={id} kind="ticket" title={ticket.title} purpose={ticket.description} status={ticket.status}
        assignee={seat} designRef={ticket.design_ref} epic={{ id: epic_id, title: page.data.epic_title ?? epic_id }}
        actions={<ActionsMenu items={actions} subject={ticket.title} />} work={work}
      />
      <Conversation ticketId={id} history={history} order={order} viewer={as}
        onToggleOrder={() => setOrder((o) => (o === "newest" ? "oldest" : "newest"))}
        onReply={(m: MessageView) => setReply({ id: m.id, by: m.by })}
        composer={composer} />
    </div>
  );
}
