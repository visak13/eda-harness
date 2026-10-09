import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { useRouteId } from "../routeId";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getTicketPage, finalizeArtifacts } from "../api/endpoints";
import { getSeats } from "../api/seats";
import type { CriterionView, MessageView, SignoffRow, TicketStatus, TicketPage as TicketPageData, UploadedArtifact } from "../api/types";
import { ProcessStrip, nextActionFor } from "../components/ProcessStrip";
import { StatusControl } from "../components/StatusControl";
import { AddCriterion } from "../components/CriterionControls";
import { AssignControl, assignLabel, usePoolCanSpawn } from "../components/AssignControl";
import { SpawnSeatForm } from "../components/SpawnSeatForm";
import { GateOpenControl } from "../components/GateOpenControl";
import { GateForms, useRetainedGates } from "../components/GateForm";
import { attentionMark } from "../components/AttentionDot";
import { LinkDocControl, AskRoleControl } from "../components/TicketAsks";
import { Term } from "../components/Term";
import { CriterionCard } from "../components/CriterionCard";
import { RulingDrawer } from "../components/RulingDrawer";
import { Composer } from "../components/Composer";
import { ExpandableComposer } from "../components/ExpandableComposer";
import { actionGloss, copyProps } from "../copy/pages";
import { useDocDrawer } from "../components/DocDrawer";
import { identity } from "../auth/identity";
import ui from "../components/ui.module.css";
import { ArtifactLink } from "../components/ArtifactLink";
import { useDropUpload } from "../components/useDropUpload";
import styles from "./Ticket.module.css";
import { useThreadHistory } from "../components/useThreadHistory";
import { WorkHeader } from "../components/WorkHeader";
import { ActionsMenu, type ActionItem } from "../components/ActionsMenu";
import { ModelsControl } from "../components/ModelsControl";
import { useIsGuest } from "../auth/guest";
import { Conversation } from "../components/Conversation";
import { Markdown } from "../components/Markdown";

// Ticket page (design-a2e5369133): the SAME WorkHeader as the epic (owner defect: "placeholder
// ticket page … even the universal theme isn't applied"), the conversation under it, controls
// under Actions ▾, and the description / tags / criteria / process ladder / linked documents
// behind the Work link.

const KINDS_DEFAULT = ["note", "question", "steer", "finding", "status", "deviation", "answer"] as const;
const KINDS_REPLY = ["answer", "note", "question", "steer", "finding", "status", "deviation"] as const;
// e0cec S5: a guest posts only a question or a note, and its Actions menu keeps reading and asking.
const KINDS_GUEST = ["question", "note"] as const;
const GUEST_ACTIONS = new Set(["ask-role", "record"]);

export function TicketPage(): React.JSX.Element {
  return <TicketSurface id={useRouteId()} />;
}

/** The ticket page's body for one id. A Library topic (S16) renders it too, embedded: `home` replaces the
 *  breadcrumb's "Epics" root and `children` render above the SAME conversation and composer a ticket gets
 *  (the topic's own panels). */
export function TicketSurface({ id, home, children }: {
  id: string;
  home?: { label: string; to: string };
  children?: React.ReactNode;
}): React.JSX.Element {
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

  const { hash, search } = useLocation();
  const navigate = useNavigate();
  const include = hash.startsWith("#m-") ? hash.slice(1) : null;
  const page = useQuery({ queryKey: ["ticket", id, include], queryFn: () => getTicketPage(id, include) });
  // C10 (design-10b21760d9 §13): an epic has its own page. A /ticket/<epic id> link (the VS Code
  // chat's, an old bookmark) replaces itself with /epic/<id>, query and #m- anchor kept.
  const isEpic = page.data?.ticket.kind === "epic";
  // S16: a topic's own page is the Library's, so a /ticket/<topic id> link lands there the same way
  const isTopic = page.data?.ticket.kind === "topic" && !children;
  useEffect(() => {
    if (isEpic) navigate(`/epic/${encodeURIComponent(id)}${search}${hash}`, { replace: true });
    else if (isTopic) navigate(`/library/topics/${encodeURIComponent(id)}${search}${hash}`, { replace: true });
  }, [isEpic, isTopic, id, search, hash, navigate]);
  const history = useThreadHistory(id, page.data);
  // S22: before the early returns (a hook); keeps a gate answered elsewhere while its ruling is unsent.
  const gates = useRetainedGates((page.data?.open_gates ?? []).filter((g) => g.gate !== "design_signoff"));
  const guest = useIsGuest();
  const canSpawn = usePoolCanSpawn();
  // An owner-checked criterion with evidence is marked, and it (or its #c- deep link, once) opens the ruling drawer:
  // the evidence frozen at its version beside the verdict.
  const [ruling, setRuling] = useState<string | null>(null);
  const rulingOpener = useRef<HTMLElement | null>(null);
  const landed = useRef<string | null>(null);
  const target = hash.startsWith("#c-") ? decodeURIComponent(hash.slice(1)) : null;
  const signoffWaiting = !guest && Boolean(page.data?.criteria.some((c) => c.id === target && awaitsOwner(c)));
  useEffect(() => {
    if (!target || !signoffWaiting || landed.current === target || !page.data) return;
    landed.current = target;
    document.getElementById(target)?.scrollIntoView?.({ block: "center" });
    setRuling(target);
  }, [target, signoffWaiting, page.data]);
  // S12-ui2 (qa m-da89ef8294 m4): a seat alive on this ticket is who works it, even before the ticket names an assignee
  const seats = useQuery({ queryKey: ["seats"], queryFn: getSeats, retry: false });
  const liveSeat = seats.data?.seats.find((s) => s.ticket_id === id && s.state === "alive")?.handle ?? null;

  // embedded (a topic), the host's own panels stay readable while the ticket surface loads or if it is refused
  // the children keep one slot (second child of the page div) in every state, so their state survives the load
  if (page.isPending || isEpic || isTopic) return children ? <div className={styles.page}><p className={ui.empty}>Loading ticket…</p>{children}</div> : <p className={ui.empty}>Loading ticket…</p>;
  if (page.isError) {
    const failed = (
      <p className={ui.banner} role="alert">
        Could not load {id}: {(page.error as Error).message}
      </p>
    );
    return children ? <div className={styles.page}>{failed}{children}</div> : failed;
  }

  const { ticket, epic_id, criteria, docs, assignee, waiting_reason, description_html } = page.data;
  const seat = assignee.handle ?? ticket.assignee ?? liveSeat;
  const gloss = (k: string) => actionGloss("ticket", k);
  const topic = ticket.kind === "topic"; // its seat is the resident sme and it has no epic's model rows

  const waitingCriteria = new Set(guest ? [] : criteria.filter(awaitsOwner).map((c) => c.id));
  const request = new URLSearchParams(search).get("request");
  const openKey = request && gates.some(({ gate: g }) => g.event_id === request) ? "answer-decision" : null;
  const all: ActionItem[] = [
    { key: "change-status", label: "Change status", gloss: gloss("change-status"), copy: copyProps("ticket", "process-strip"),
      render: () => <StatusControl ticketId={id} currentStatus={ticket.status as TicketStatus} /> },
    ...(topic ? [] : [{ key: "assign-spawn", label: assignLabel(canSpawn), gloss: gloss(canSpawn ? "assign-spawn" : "assign"),
      render: () => <AssignControl ticketId={id} currentAssignee={seat} /> } as ActionItem]),
    ...(gates.length ? [{ key: "answer-decision", label: "Answer a decision", count: gates.length, gloss: gloss("answer-decision"),
      render: () => <GateForms gates={gates} /> } as ActionItem] : []),
    ...(ticket.kind === "story" ? [{ key: "spawn-seat", label: "Spawn seat", gloss: gloss("spawn-seat"),
      render: () => <SpawnSeatForm ticketId={id} roles={["engineer", "qa", "adversary"]} /> } as ActionItem] : []),
    ...(topic ? [] : [{ key: "models", label: "Models…", gloss: gloss("models"),
      render: () => <ModelsControl epicId={epic_id} storyId={ticket.kind === "story" ? id : undefined} /> } as ActionItem]),
    { key: "raise-decision", label: "Raise a decision", gloss: gloss("raise-decision"),
      render: () => <GateOpenControl ticketId={id} /> },
    { key: "ask-role", label: "Ask a role", gloss: gloss("ask-role"),
      render: () => <AskRoleControl ticketId={id} /> },
    { key: "link-doc", label: "Link a document", gloss: gloss("link-doc"), copy: copyProps("ticket", "documents"),
      render: () => <LinkDocControl ticketId={id} /> },
    { key: "add-criterion", label: "Add an acceptance criterion", gloss: gloss("add-criterion"),
      render: () => <AddCriterion ticketId={id} /> },
    { key: "record", label: "Record ids", gloss: gloss("record"),
      render: () => <dl className={styles.record}>
        <div><dt>Id</dt><dd className={ui.idMono}>{ticket.id}</dd></div>
        <div><dt>Epic</dt><dd className={ui.idMono}>{epic_id}</dd></div>
        <div><dt>Kind</dt><dd><Term category="ticket_kind" value={ticket.kind} /> / <Term category="work_type" value={ticket.work_type} /></dd></div>
        <div><dt>Status</dt><dd>{ticket.status}</dd></div>
        <div><dt>Waiting</dt><dd>{waiting_reason.reason || "—"}</dd></div>
      </dl> },
  ];
  const actions = guest ? all.filter((a) => GUEST_ACTIONS.has(a.key)) : all;

  const work = (
    <div className={styles.work} data-testid="ticket-work">
      {ticket.description ? <section>
        <div className={ui.sectionLabel}>Description</div>
        {/* t-994970028d (owner m-3fa1996dea): the board renders the description as escaped, sanitised
            markdown; an older board without description_html keeps the plain text. */}
        {description_html
          ? <div data-testid="description"><Markdown html={description_html} className={styles.descMd} /></div>
          : <p className={styles.desc} data-testid="description">{ticket.description}</p>}
        {ticket.tags.length > 0 ? <div className={styles.tags}>{ticket.tags.map((t) => <span key={t} className={ui.tag}>{t}</span>)}</div> : null}
      </section> : null}
      <section data-testid="assignee">
        <div className={ui.sectionLabel}>Seat</div>
        <div className={styles.seat}>
          <span className={styles.seatName}>{seat ?? "unassigned"}</span>
          {assignee.role ? <span className={ui.tag}>{assignee.role}</span> : null}
          <span className={styles.seatState}>{waiting_reason.presence ? waiting_reason.presence : "not running"}</span>
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
              <div key={c.id} id={c.id} className={waitingCriteria.has(c.id) ? attentionMark : undefined}
                data-attention={waitingCriteria.has(c.id) ? "true" : undefined}>
                {waitingCriteria.has(c.id) && c.evidence_ref ? <button type="button" className={ui.button}
                  data-testid="review-signoff" onClick={(e) => { rulingOpener.current = e.currentTarget; setRuling(c.id); }}>
                  Review the evidence and rule</button> : null}
                <CriterionCard criterion={c} ticketId={id}
                  ruling={c.verdict === "pending" && c.evidence_ref ? { evidenceVersion: c.evidence_version ?? null } : undefined}
                  canReword={c.verdict === "pending"} onOpenEvidence={(docId) => drawer.openDoc(docId)} />
              </div>
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
        kinds={[...(guest ? KINDS_GUEST : reply ? KINDS_REPLY : KINDS_DEFAULT)]}
        showTo to={reply ? reply.by : null} replyTo={reply?.id ?? null} replyToBy={reply?.by ?? null}
        onCancelReply={() => setReply(null)}
        placeholder={reply ? `Reply to @${reply.by}` : `Write a message as @${as}… use @ to mention someone.`}
        expand={expand}
        quotes
      />
    )}</ExpandableComposer>
  );

  return (
    <div className={styles.page}>
      <WorkHeader
        ticketId={id} kind="ticket" title={ticket.title} purpose={ticket.description} status={ticket.status}
        assignee={seat} designRef={ticket.design_ref} epic={{ id: epic_id, title: page.data.epic_title ?? epic_id }} home={home}
        actions={<ActionsMenu items={actions} subject={ticket.title} openKey={openKey} />} work={work}
      />
      {children}
      <Conversation ticketId={id} history={history} order={order} viewer={as}
        onToggleOrder={() => setOrder((o) => (o === "newest" ? "oldest" : "newest"))}
        onReply={(m: MessageView) => setReply({ id: m.id, by: m.by })}
        composer={composer} />
      <RulingDrawer signoff={rulingFor(page.data, criteria.find((c) => c.id === ruling), seat)}
        onClose={() => setRuling(null)} returnFocusTo={rulingOpener.current} />
    </div>
  );
}

/** An owner-checked criterion that has evidence and no verdict yet: the owner reviews it and rules. */
const awaitsOwner = (c: CriterionView): boolean => c.checked_by === "owner" && c.verdict === "pending" && Boolean(c.evidence_ref);

/** The ruling drawer's row for one of this ticket's criteria: its evidence doc at the version the evidence named. */
export function rulingFor(data: TicketPageData, c: CriterionView | undefined, assignee: string | null, ask?: string): SignoffRow | null {
  if (!c?.evidence_ref) return null;
  const d = data.docs.find((x) => x.id === c.evidence_ref);
  return {
    criterion: c,
    ticket: { id: data.ticket.id, title: data.ticket.title, epic_id: data.epic_id, epic_title: data.epic_title ?? data.epic_id, assignee },
    doc: { id: c.evidence_ref, title: d?.title ?? c.evidence_ref, doc_type: d?.doc_type ?? "report", version: c.evidence_version ?? d?.version ?? 1 },
    excerpt: "",
    ask,
  };
}
