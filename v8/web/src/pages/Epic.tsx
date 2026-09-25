import { useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getEpicPage, getEpicsSummary, getTicketsTable } from "../api/endpoints";
import { getPoolCapabilities, resumeSeat } from "../api/seats";
import { BoardApiError } from "../api/client";
import type { CriterionView, EpicKnowledgeRow, EpicSummaryRow, EpicTreeNode, MessageView, PoolCapabilities, TicketStatus } from "../api/types";
import { StatusChip } from "../components/StatusChip";
import { ProcessStrip } from "../components/ProcessStrip";
import { StatusControl } from "../components/StatusControl";
import { GateOpenControl } from "../components/GateOpenControl";
import { GateForm, useRetainedGates } from "../components/GateForm";
import { AssignControl } from "../components/AssignControl";
import { AskRoleControl } from "../components/AskRole";
import { SpawnArchitect } from "../components/SpawnArchitect";
import { CriterionCard } from "../components/CriterionCard";
import { AddCriterion } from "../components/CriterionControls";
import { Composer } from "../components/Composer";
import { ExpandableComposer } from "../components/ExpandableComposer";
import { copyItem, copyProps } from "../copy/pages";
import { useDocDrawer } from "../components/DocDrawer";
import { identity } from "../auth/identity";
import ui from "../components/ui.module.css";
import { Clamp } from "../components/Clamp";
import styles from "./Epic.module.css";
import { useThreadHistory } from "../components/useThreadHistory";
import { WorkHeader } from "../components/WorkHeader";
import { ActionsMenu, type ActionItem } from "../components/ActionsMenu";
import { Conversation } from "../components/Conversation";
import { ModelsControl } from "../components/ModelsControl";

// The epic page per revision3-clean-epic.png (design-a2e5369133): WorkHeader (topline + Actions ▾,
// title, purpose, metadata, links) over the conversation canvas with the composer under it. Every
// control that used to be a rail card lives under Actions ▾; the stories/kanban/criteria/process
// ladder live behind the Work link. "Steer" is a Type in the composer, not a button.

function roleOf(assignee: string | null): string {
  if (!assignee) return "unassigned";
  return assignee.includes(".") ? assignee.split(".")[0] : assignee;
}

function flatten(node: EpicTreeNode): EpicTreeNode[] {
  return [node, ...node.children.flatMap(flatten)];
}

function tallyTotals(node: EpicTreeNode): { passed: number; total: number } {
  return flatten(node)
    .filter((n) => n.kind !== "epic")
    .reduce((acc, n) => {
      const [p, t] = n.criteria.split("/").map(Number);
      return { passed: acc.passed + (p || 0), total: acc.total + (t || 0) };
    }, { passed: 0, total: 0 });
}

const KANBAN: [string, string[]][] = [
  ["Backlog", ["drafted", "designed", "signed_off", "blocked"]],
  ["Ready", ["ready"]],
  ["In progress", ["in_progress"]],
  ["In review", ["in_review"]],
  ["Done", ["done", "partial"]],
];

const KINDS_DEFAULT = ["note", "steer", "question", "status", "finding", "deviation", "answer"] as const;
const KINDS_REPLY = ["answer", "note", "question", "steer", "status", "finding", "deviation"] as const;

export function EpicPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const [order, setOrder] = useState<"newest" | "oldest">("newest");
  const [reply, setReply] = useState<{ id: string; by: string } | null>(null);
  const { hash } = useLocation();
  const include = hash.startsWith("#m-") ? hash.slice(1) : null;

  const page = useQuery({ queryKey: ["epic", id, include], queryFn: () => getEpicPage(id, include) });
  const history = useThreadHistory(id, page.data);
  const summary = useQuery({ queryKey: ["epics", "summary", "", ""], queryFn: () => getEpicsSummary() });
  // S22: before the early returns (a hook); keeps a gate answered elsewhere while its ruling is unsent.
  const gates = useRetainedGates((page.data?.answerable_gates ?? []).filter((g) => g.gate !== "design_signoff"));

  if (page.isPending) return <p className={ui.empty}>Loading epic…</p>;
  if (page.isError)
    return (
      <p className={ui.banner} role="alert">
        Could not load {id}: {(page.error as Error).message}
      </p>
    );

  const data = page.data;
  const epic = data.board.epic;
  const words = data.words ?? epic.title;
  const heading = data.title ?? epic.title;
  const stories = epic.children;
  const directive = [...data.thread].reverse().find((m) => m.kind === "steer") ?? null;
  const row = summary.data?.find((r: EpicSummaryRow) => r.id === id) ?? null;
  const totals = tallyTotals(epic);
  const design = data.docs.find((d) => d.doc_type === "design") ?? null;
  const gloss = (k: string) => copyItem("epic", k).text;

  const actions: ActionItem[] = [
    { key: "change-status", label: "Change status", gloss: gloss("change-status"), copy: copyProps("epic", "change-status"),
      render: () => <StatusControl ticketId={id} currentStatus={epic.status as TicketStatus} /> },
    ...(gates.length ? [{ key: "answer-decision", label: "Answer a decision", count: gates.length, gloss: gloss("answer-decision"), copy: copyProps("epic", "answer-decision"),
      render: () => <>{gates.map(({ gate: g, closed, onDismiss }) => <GateForm key={`${g.ticket_id}:${g.gate}`} gate={g} closed={closed} onDismiss={onDismiss} />)}</> } as ActionItem] : []),
    { key: "raise-decision", label: "Raise a decision", gloss: gloss("raise-decision"), copy: copyProps("epic", "raise-decision"),
      render: () => <GateOpenControl ticketId={id} /> },
    { key: "assign-spawn", label: "Assign or spawn a seat", gloss: gloss("assign-spawn"), copy: copyProps("epic", "assign-spawn"),
      render: () => <>
        <AssignControl ticketId={id} currentAssignee={epic.assignee ?? null} seatChoice={data.seat_choice ?? null} />
        <SpawnArchitect epicId={id} assignedSeats={row?.assigned_seats ?? []} gloss={<p className={styles.gloss}>{gloss("spawn-architect")}</p>} />
        {row && row.assigned_seats.length > 0 ? <div className={styles.seats}>
          <div className={ui.sectionLabel}>Assigned seats</div>
          {row.assigned_seats.map((s) => <AssignedSeatRow key={s} seatId={s} epicId={id} />)}
        </div> : null}
      </> },
    { key: "models", label: "Models…", gloss: "each role's model and effort on this epic; switch them for the seats spawned next.",
      render: () => <ModelsControl epicId={id} /> },
    { key: "ask-role", label: "Ask a role", gloss: gloss("ask-role"), copy: copyProps("epic", "ask-role"),
      render: () => <AskRoleControl ticketId={id} /> },
    { key: "add-criterion", label: "Add an acceptance criterion", gloss: gloss("overview"), copy: copyProps("epic", "overview"),
      render: () => <AddCriterion ticketId={id} /> },
    { key: "original-request", label: "Original request", gloss: gloss("title"),
      render: () => <figure className={styles.words} data-testid="owner-words">
        <figcaption className={styles.wordsLabel}>Owner&rsquo;s words · original request</figcaption>
        <blockquote className={styles.wordsText} data-testid="owner-words-text">{words}</blockquote>
      </figure> },
    { key: "record", label: "Record ids", gloss: "the epic's id, kind and raw status, for a message or a shell.",
      render: () => <dl className={styles.record}>
        <div><dt>Id</dt><dd className={ui.idMono}>{epic.id}</dd></div>
        <div><dt>Kind</dt><dd>{epic.kind}</dd></div>
        <div><dt>Status</dt><dd>{epic.status}</dd></div>
        <div><dt>Design</dt><dd>{design ? <DocLink id={design.id} /> : "Not linked"}</dd></div>
      </dl> },
  ];

  const work = (
    <div className={styles.work} data-testid="epic-work">
      {data.description?.trim() ? <section data-testid="architect-brief" {...copyProps("epic", "directive")}>
        <div className={ui.sectionLabel}>Architect&rsquo;s brief</div>
        <Clamp className={styles.briefText} text={data.description} lines={6} />
      </section> : null}
      {directive ? <section data-testid="directive">
        <div className={ui.sectionLabel}>Latest steer · {directive.by}</div>
        <Clamp className={styles.briefText} text={directive.text} lines={3} />
      </section> : null}
      <section>
        <div className={ui.sectionLabel}>Process</div>
        <ProcessStrip status={epic.status} ariaLabel="Epic process" />
      </section>
      <OverviewTab epicId={id} storyCount={stories.length} totals={totals} openGates={data.open_gates.length} docs={data.docs} knowledge={data.knowledge ?? []} criteria={data.criteria} />
      <WorkTab epicId={id} epic={epic} stories={stories} />
    </div>
  );

  const composer = (
    <ExpandableComposer title={`Message ${id}`}>{(expand) => <Composer
      ticketId={id}
      kinds={[...(reply ? KINDS_REPLY : KINDS_DEFAULT)]}
      showTo to={reply?.by} replyTo={reply?.id} replyToBy={reply?.by} onCancelReply={() => setReply(null)}
      expand={expand}
      quotes
      placeholder="Write a message… use @ to mention someone. Type = Steer to steer this epic."
    />}</ExpandableComposer>
  );

  return (
    <div className={styles.page}>
      <WorkHeader
        ticketId={id} kind="epic" title={heading} purpose={data.description || (words !== heading ? words : null)}
        status={epic.status} assignee={epic.assignee ?? row?.assigned_seats[0] ?? null} designRef={design?.id ?? null}
        reviewRequested={data.answerable_gates.some((g) => g.gate === "design_signoff") || undefined}
        architect={data.architect ?? null}
        actions={<ActionsMenu items={actions} subject={heading} />}
        work={work}
      />
      <Conversation ticketId={id} history={history} order={order} viewer={identity()}
        onToggleOrder={() => setOrder((o) => (o === "newest" ? "oldest" : "newest"))}
        onReply={(m: MessageView) => setReply({ id: m.id, by: m.by })}
        composer={composer} />
    </div>
  );
}

/** Human #24: an assigned seat links to its row on Seats with Message / Resume inline. */
function AssignedSeatRow({ seatId, epicId }: { seatId: string; epicId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const [hint, setHint] = useState<string | null>(null);
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false });
  const caps = capsQ.data as PoolCapabilities | undefined;
  const canResume = !!(caps?.resume_parked || caps?.resume_closed);
  const dot = seatId.indexOf(".");
  const seatTicket = dot > 0 ? seatId.slice(dot + 1) : epicId;
  const resume = useMutation({
    mutationFn: () => resumeSeat(seatId, seatTicket),
    onSuccess: (res) => {
      setHint(res.hint || `Resumed ${seatId}.`);
      void qc.invalidateQueries({ queryKey: ["seats"] });
      void qc.invalidateQueries({ queryKey: ["epics", "summary"] });
    },
  });
  const err = resume.error as BoardApiError | undefined;
  return (
    <div className={styles.seat} data-testid="assigned-seat" data-seat={seatId}>
      <div className={styles.seatRow}>
        <Link to={`/seats#${encodeURIComponent(seatId)}`} className={`${ui.idMono} ${styles.seatLink}`} data-testid="assigned-seat-link">{seatId}</Link>
        <div className={styles.seatActions}>
          <Link to={`/seats?message=${encodeURIComponent(seatId)}#${encodeURIComponent(seatId)}`} className={styles.seatAction} data-testid="assigned-seat-message" {...copyProps("seats", "message")}>Message</Link>
          {canResume ? (
            <button type="button" className={styles.seatAction} data-testid="assigned-seat-resume" disabled={resume.isPending} onClick={() => resume.mutate()} {...copyProps("seats", "resume")}>
              {resume.isPending ? "Resuming…" : "Resume"}
            </button>
          ) : null}
        </div>
      </div>
      {hint ? <p className={styles.gloss} role="status" data-testid="assigned-seat-hint">{hint}</p> : null}
      {err ? <p className={styles.seatError} role="alert" data-testid="assigned-seat-error">{err.hint ?? err.message}</p> : null}
    </div>
  );
}

function DocLink({ id }: { id: string | null }): React.JSX.Element {
  const drawer = useDocDrawer();
  if (!id) return <span>Not linked</span>;
  return <button type="button" className={styles.docLink} onClick={() => drawer.openDoc(id)}>{id}</button>;
}

function OverviewTab({ epicId, storyCount, totals, openGates, docs, knowledge, criteria }: {
  epicId: string; storyCount: number; totals: { passed: number; total: number }; openGates: number;
  docs: { id: string; doc_type: string; title: string }[]; knowledge: EpicKnowledgeRow[]; criteria: CriterionView[];
}): React.JSX.Element {
  const drawer = useDocDrawer();
  const design = docs.find((d) => d.doc_type === "design");
  return (
    <section className={styles.overview}>
      <p className={styles.pulse}>
        {storyCount === 0
          ? "No stories yet — this epic is still being shaped."
          : `${storyCount} ${storyCount === 1 ? "story" : "stories"} · ` +
            `${totals.total === 0 ? "no criteria yet" : `${totals.passed} of ${totals.total} criteria passed`} · ` +
            `${openGates} open ${openGates === 1 ? "gate" : "gates"}`}
      </p>
      {design ? <p className={ui.empty}>Design: <button type="button" className={styles.docLink} onClick={() => drawer.openDoc(design.id)}>{design.title}</button></p> : null}
      {/* S-LIBRARY c-14e93ebfc7: the Library docs this epic's briefs index (link/unlink in the Library) */}
      <div className={ui.sectionLabel}>Knowledge ({knowledge.length})</div>
      {knowledge.length === 0 ? (
        <p className={ui.empty} data-testid="epic-knowledge-empty">
          No Library docs linked. <Link to="/library/knowledge">Link one from the Library</Link>.
        </p>
      ) : (
        <ul className={styles.knowledge} data-testid="epic-knowledge">
          {knowledge.map((k) => (
            <li key={k.link_id}>
              <span className={ui.tag}>{k.relation === "uses_domain" ? "domain" : "strategy"}</span>{" "}
              <Link to={`/library/knowledge?k=${encodeURIComponent(k.id)}`}>{k.title}</Link>{" "}
              <span className={ui.idMono}>v{k.version}{k.tags?.length ? ` · ${k.tags.join(", ")}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
      <div className={ui.sectionLabel}>Acceptance criteria ({criteria.length})</div>
      {criteria.length === 0 ? (
        <p className={ui.empty}>No acceptance criteria on the epic itself. Add one under Actions.</p>
      ) : (
        <div className={styles.epicCriteria}>
          {criteria.map((c) => (
            <CriterionCard key={c.id} criterion={c} ticketId={epicId}
              ruling={c.verdict === "pending" && c.evidence_ref ? { evidenceVersion: c.evidence_version ?? null } : undefined}
              canReword={c.verdict === "pending"} onOpenEvidence={(docId) => drawer.openDoc(docId)} />
          ))}
        </div>
      )}
    </section>
  );
}

function WorkTab({ epicId, epic, stories }: { epicId: string; epic: EpicTreeNode; stories: EpicTreeNode[] }): React.JSX.Element {
  const [status, setStatus] = useState("");
  const [workType, setWorkType] = useState("");
  const [assignee, setAssignee] = useState("");
  const [q, setQ] = useState("");
  const search = useQuery({
    queryKey: ["tickets", "table", epicId, "q", q],
    queryFn: () => getTicketsTable({ epic: epicId, q }),
    enabled: q.trim().length > 0,
  });
  const qHits = useMemo(() => (q.trim() ? new Set((search.data?.rows ?? []).map((r) => r.id)) : null), [q, search.data]);
  const all = flatten(epic).filter((n) => n.kind !== "epic");
  const needle = q.trim().toLowerCase();
  const textHit = (n: EpicTreeNode) =>
    !needle || n.title.toLowerCase().includes(needle) || n.id.toLowerCase().includes(needle) || !!qHits?.has(n.id);
  const match = (n: EpicTreeNode) =>
    (!status || n.status === status) && (!workType || n.work_type === workType) &&
    (!assignee || (n.assignee ?? "").includes(assignee)) && textHit(n);
  const filtered = all.filter(match);
  const filterCount = [status, workType, assignee].filter(Boolean).length;

  if (stories.length === 0) return <p className={ui.empty}>This epic has no stories yet.</p>;

  return (
    <section>
      <div className={ui.sectionLabel}>Stories and tasks ({all.length})</div>
      <div className={styles.workTools}>
        <input className={`${ui.input} ${styles.workSearch}`} type="search" aria-label="Search words"
          placeholder="Search by title or id…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="work-search" />
        <details className={styles.filters} data-testid="work-filters-fold">
          <summary className={styles.filtersSummary}>Filters{filterCount > 0 ? ` (${filterCount})` : ""}</summary>
          <form className={styles.filterBar} onSubmit={(e) => e.preventDefault()} data-testid="work-filters">
            <select className={ui.select} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">any status</option>
              {["drafted", "designed", "signed_off", "ready", "in_progress", "in_review", "blocked", "done", "partial", "dropped"].map((s) => (
                <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
              ))}
            </select>
            <select className={ui.select} aria-label="Work type" value={workType} onChange={(e) => setWorkType(e.target.value)}>
              <option value="">any work type</option>
              {["feature", "bug", "rnd", "creative"].map((w) => <option key={w} value={w}>{w}</option>)}
            </select>
            <input className={ui.input} aria-label="Assignee contains" placeholder="assignee contains…" value={assignee} onChange={(e) => setAssignee(e.target.value)} />
          </form>
        </details>
      </div>

      <div className={styles.tree} data-testid="work-tree">
        <div className={styles.treeHead} aria-hidden="true">
          <span>Ticket</span><span>Role</span><span>Status</span><span className={styles.treeHeadRight}>Criteria</span>
        </div>
        {stories.filter(match).length === 0 && filtered.length === 0
          ? <p className={ui.empty}>No tickets match these filters.</p>
          : stories.map((s) => <TreeNode key={s.id} node={s} match={match} depth={0} />)}
      </div>

      <div className={styles.kanban} data-testid="kanban">
        {KANBAN.map(([label, states]) => {
          const cards = filtered.filter((n) => states.includes(n.status));
          return (
            <div key={label} className={styles.kanbanCol}>
              <div className={styles.kanbanHead}>{label} <span className={styles.kanbanCount}>{cards.length}</span></div>
              {cards.map((n) => (
                <Link key={n.id} to={`/ticket/${encodeURIComponent(n.id)}`} className={styles.kanbanCard}>
                  <span className={styles.kanbanTitle}>{n.title}</span>
                  <span className={ui.idMono}>{n.id}</span>
                </Link>
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function TreeNode({ node, match, depth }: { node: EpicTreeNode; match: (n: EpicTreeNode) => boolean; depth: number }): React.JSX.Element | null {
  const selfShown = match(node);
  const kids = node.children.map((k) => <TreeNode key={k.id} node={k} match={match} depth={depth + 1} />).filter(Boolean);
  if (!selfShown && kids.length === 0) return null;
  return (
    <>
      {selfShown ? (
        <div className={styles.treeRow} style={{ paddingLeft: 16 + depth * 20 }} data-testid="work-row">
          <Link to={`/ticket/${encodeURIComponent(node.id)}`} className={styles.treeLink}>
            <span className={styles.treeTitle}>{node.title}</span>
            <span className={styles.treeId}>{node.id}</span>
          </Link>
          <span className={styles.treeRole}>{roleOf(node.assignee)}</span>
          <span className={styles.treeStatus}><StatusChip status={node.status} /></span>
          <span className={styles.treeTally}>{node.criteria}</span>
        </div>
      ) : null}
      {kids}
    </>
  );
}
