import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getEpicPage, getEpicsSummary, getTicketsTable } from "../api/endpoints";
import { getPoolCapabilities, resumeSeat } from "../api/seats";
import { BoardApiError } from "../api/client";
import type { CriterionView, EpicSummaryRow, EpicTreeNode, MessageView, PoolCapabilities, TicketStatus } from "../api/types";
import { StatusChip } from "../components/StatusChip";
import { ProcessStrip, nextActionFor } from "../components/ProcessStrip";
import { label as glossLabel, meaning as glossMeaning } from "../copy/glossary";
import { StatusControl } from "../components/StatusControl";
import { GateOpenControl } from "../components/GateOpenControl";
import { GateForm } from "../components/GateForm";
import { AssignControl } from "../components/AssignControl";
import { AskRoleControl } from "../components/AskRole";
import { SpawnArchitect } from "../components/SpawnArchitect";
import { CriterionCard } from "../components/CriterionCard";
import { AddCriterion } from "../components/CriterionControls";
import { Tabs } from "../components/Tabs";
import { Composer } from "../components/Composer";
import { useScrollToHash } from "../components/useScrollToHash";
import { copyItem, copyProps } from "../copy/pages";
import { AgentLine } from "../components/AgentLine";
import { useDocDrawer } from "../components/DocDrawer";
import { identity } from "../auth/identity";
import ui from "../components/ui.module.css";
import { MessageText } from "../components/ArtifactLink";
import { Clamp } from "../components/Clamp";
import styles from "./Epic.module.css";
import { Icon } from "../components/Icon";
import { ContextualWork } from "../components/ContextualWork";
import { pendingWork } from "../components/PendingNavigation";

// Epic page (design §4.2): crumb, id + status chip, Georgia 38 title, the owner's words verbatim,
// a directive callout when the thread carries an owner steer, tabs Overview/Work/Documents/Thread,
// a 744/336 gap-64 split with At a glance / Assigned seat / Records on demand, and a 'Steer this
// epic' action that opens the composer with kind=steer.

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
    .reduce(
      (acc, n) => {
        const [p, t] = n.criteria.split("/").map(Number);
        return { passed: acc.passed + (p || 0), total: acc.total + (t || 0) };
      },
      { passed: 0, total: 0 },
    );
}

/** Lines to show of the brief before "Show all": its first paragraph (human #33). */
function briefLines(text: string): number {
  const first = text.trim().split(/\n\s*\n/)[0] ?? "";
  return Math.max(2, Math.min(6, Math.ceil(first.length / 90)));
}

/** Human #23: every epic-page control carries a VISIBLE one-line gloss — what it does and who is
 *  woken — from the copy contract (the same text copyProps puts in the tooltip / aria-describedby). */
function Gloss({ k }: { k: string }): React.JSX.Element {
  return (
    <p className={styles.gloss} data-testid={`gloss-${k}`}>
      {copyItem("epic", k).text}
    </p>
  );
}

const KANBAN: [string, string[]][] = [
  ["Backlog", ["drafted", "designed", "signed_off", "blocked"]],
  ["Ready", ["ready"]],
  ["In progress", ["in_progress"]],
  ["In review", ["in_review"]],
  ["Done", ["done", "partial"]],
];

export function EpicPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const [tab, setTab] = useState<"overview" | "work" | "documents" | "thread">("thread");
  const [composerKind, setComposerKind] = useState<"note" | "steer">("note");
  const [order, setOrder] = useState<"newest" | "oldest">("newest");
  const [statusOpen, setStatusOpen] = useState(false);

  // Round 2 #13: a Find hit on an epic message lands at /epic/:id#m-…; the hash picks the Thread
  // tab (the hook that scrolls lives inside it) and the message is fetched even outside the window.
  const { hash } = useLocation();
  const include = hash.startsWith("#m-") ? hash.slice(1) : null;
  useEffect(() => {
    if (include) setTab("thread");
  }, [include]);
  const page = useQuery({ queryKey: ["epic", id, include], queryFn: () => getEpicPage(id, include) });
  const summary = useQuery({ queryKey: ["epics", "summary", "", ""], queryFn: () => getEpicsSummary() });

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
  // Human #32 (2026-09-10): title ≠ words. The heading is the epic's short title; the owner's words
  // render ONCE as a quoted block under it (omitted only when they are the same text).
  const heading = data.title ?? epic.title;
  const showWords = words.trim() !== heading.trim();
  const stories = epic.children;
  const directive = [...data.thread].reverse().find((m) => m.kind === "steer") ?? null;
  const row = summary.data?.find((r: EpicSummaryRow) => r.id === id) ?? null;
  const totals = tallyTotals(epic);
  const workCount = flatten(epic).filter((n) => n.kind !== "epic").length;

  const tabs = [
    { key: "overview", label: "Overview", copy: copyProps("epic", "overview") },
    { key: "work", label: "Work", count: workCount, copy: copyProps("epic", "work") },
    { key: "documents", label: "Documents", count: data.docs.length, copy: copyProps("epic", "documents") },
    { key: "thread", label: "Thread", count: data.thread.length, copy: copyProps("epic", "thread") },
  ];

  function steer() {
    setComposerKind("steer");
    setTab("thread");
  }

  return (
    <div>
      <nav className={styles.crumb} aria-label="Breadcrumb">
        <Link to="/epics">Epics</Link>
        <span aria-hidden="true"> › </span>
        <span className={styles.crumbHere}>{epic.title}</span>
      </nav>

      {/* Astra #36 (1): meta line (id + ONE 24px status badge) → Georgia 38/44 short title → the
          owner's words in a 3px-accent callout, two-line preview with Show all. The header is the
          same 744/336 grid as the body so the rail column (the Steer control) starts beside the
          title row, not below the words. */}
      <div className={styles.head}>
        <div className={styles.idline}>
          <span className={ui.idMono}>{epic.id}</span>
          <span className={styles.badge} data-testid="epic-status-badge">
            <StatusChip status={epic.status} />
          </span>
        </div>
        <h1 className={styles.title} {...copyProps("epic", "title")}>{heading}</h1>
        <details className={styles.steerWrap}><summary>Actions</summary>
          <button type="button" className={styles.steer} onClick={steer} {...copyProps("epic", "steer")}>
            Steer this epic
          </button>
          <Gloss k="steer" />
        </details>

        {showWords ? (
          <details><summary>Original request</summary><figure className={styles.words} data-testid="owner-words">
            <figcaption className={styles.wordsLabel}>Owner&rsquo;s words · original request</figcaption>
            <Clamp className={styles.wordsText} text={words} lines={2} testId="owner-words-text" />
          </figure></details>
        ) : null}
      </div>

      <ContextualWork ticketId={id} />
      <details id="work-details"><summary>Brief, latest steer and process</summary>
      {/* Human #33: the description is the architect's brief — a quiet card, first paragraph
          shown, "Show all" expands; never an alert. */}
      {data.description?.trim() ? (
        <section className={`${ui.card} ${styles.brief}`} data-testid="architect-brief" {...copyProps("epic", "directive")}>
          <div className={ui.sectionLabel}>Architect&rsquo;s brief</div>
          <Clamp className={styles.briefText} text={data.description} lines={briefLines(data.description)} />
        </section>
      ) : null}

      {directive ? (
        <section className={`${ui.card} ${styles.brief}`} data-testid="directive">
          <div className={ui.sectionLabel}>Latest steer · {directive.by}</div>
          <Clamp className={styles.briefText} text={directive.text} lines={3} />
        </section>
      ) : null}

      {/* Astra #36 (4): the strip keeps its step chips; its "Next:" sentence was a duplicate of
          the Status history fold in the rail, so the epic page drops it. */}
      <ProcessStrip status={epic.status} ariaLabel="Epic process" showNext={false} />
      </details>

      <div className={styles.layout}>
        <div className={styles.mainCol}>
          <Tabs tabs={tabs} active={tab} onChange={(k) => setTab(k as typeof tab)} />

          {tab === "overview" ? (
            <OverviewTab
              epicId={id}
              storyCount={stories.length}
              totals={totals}
              openGates={data.open_gates.length}
              docs={data.docs}
              criteria={data.criteria}
            />
          ) : null}

          {tab === "work" ? <WorkTab epicId={id} epic={epic} stories={stories} /> : null}

          {tab === "documents" ? <DocumentsTab docs={data.docs} /> : null}

          <div hidden={tab !== "thread"}>
            <ThreadTab
              epicId={id}
              thread={data.thread}
              order={order}
              onToggleOrder={() => setOrder((o) => (o === "newest" ? "oldest" : "newest"))}
              composerKind={composerKind}
            />
          </div>
        </div>

        <details className={styles.rail}><summary>Actions & work details</summary><aside aria-label="Epic details">
          {/* Astra #36 (4): status = the one badge beside the id; a 40px outlined "Change status"
              button reveals the control; the lifecycle text lives in a "Status history" fold. */}
          <section className={ui.card} id="epic-status">
            <div className={ui.sectionLabel}>Status</div>
            <button
              type="button"
              className={ui.button}
              aria-expanded={statusOpen}
              aria-controls="epic-status-control"
              data-testid="change-status-toggle"
              onClick={() => setStatusOpen((o) => !o)}
              {...copyProps("epic", "change-status")}
            >
              {statusOpen ? "Hide status control" : "Change status"}
            </button>
            {statusOpen ? (
              <div id="epic-status-control" className={styles.statusControl} data-testid="epic-status-control">
                <StatusControl ticketId={id} currentStatus={epic.status as TicketStatus} />
              </div>
            ) : null}
            <Gloss k="change-status" />
            <details className={ui.fold} data-testid="status-history">
              <summary>Status history</summary>
              <p className={styles.lifecycle}>
                Now <strong>{glossLabel("ticket_status", epic.status)}</strong>
                {glossMeaning("ticket_status", epic.status) ? ` — ${glossMeaning("ticket_status", epic.status)}` : ""}
              </p>
              <p className={styles.lifecycle}>
                <strong>Next:</strong> {nextActionFor(epic.status)}
              </p>
              <p className={ui.empty}>
                <Link to="/library/history">Open the full history <Icon name="forward" /></Link>
              </p>
            </details>
          </section>

          {data.answerable_gates.length > 0 ? (
            <section className={ui.card} data-testid="epic-answer-gates" {...copyProps("epic", "answer-decision")}>
              <div className={ui.sectionLabel}>Answer a decision ({data.answerable_gates.length})</div>
              {data.answerable_gates.filter((g) => g.gate !== "design_signoff").map((g) => (
                <GateForm key={`${g.ticket_id}:${g.gate}`} gate={g} />
              ))}
              <Gloss k="answer-decision" />
            </section>
          ) : null}

          <section className={ui.card} {...copyProps("epic", "raise-decision")}>
            <div className={ui.sectionLabel}>Raise a decision</div>
            <GateOpenControl ticketId={id} />
            <Gloss k="raise-decision" />
          </section>

          <section className={ui.card} {...copyProps("epic", "assign-spawn")}>
            <div className={ui.sectionLabel}>Assign or spawn a seat</div>
            <AssignControl ticketId={id} currentAssignee={epic.assignee ?? null} seatChoice={data.seat_choice ?? null} />
            <Gloss k="assign-spawn" />
            <SpawnArchitect epicId={id} assignedSeats={row?.assigned_seats ?? []} gloss={<Gloss k="spawn-architect" />} />
          </section>

          <section className={ui.card} data-testid="epic-ask-role">
            <div className={ui.sectionLabel}>Ask a role</div>
            <AskRoleControl ticketId={id} />
            <Gloss k="ask-role" />
          </section>

          <section className={ui.card}>
            <div className={ui.sectionLabel}>At a glance</div>
            <div className={ui.metaRow}>
              <span>Open gates</span>
              <span>{data.open_gates.length}</span>
            </div>
            <div className={ui.metaRow}>
              <span>Criteria</span>
              <span>
                {totals.total === 0 ? "None defined" : `${totals.passed} of ${totals.total} passed`}
              </span>
            </div>
            <div className={ui.metaRow}>
              <span>Work</span>
              <span>{workCount} tickets</span>
            </div>
            <div className={ui.metaRow}>
              <span>Design</span>
              <DocLink id={epic.id === id ? findDesign(data.docs) : null} />
            </div>
          </section>

          <section className={ui.card} {...copyProps("epic", "assigned-seats")}>
            <div className={ui.sectionLabel}>Assigned seat</div>
            {row && row.assigned_seats.length > 0 ? (
              <>
                {row.assigned_seats.map((s) => (
                  <AssignedSeatRow key={s} seatId={s} epicId={id} />
                ))}
                <div className={ui.metaRow}>
                  <span>Presence</span>
                  <span>{row.waiting_reason.presence ?? "—"}</span>
                </div>
                <div className={ui.metaRow}>
                  <span>Latest status</span>
                  <span>{row.latest_status ?? "—"}</span>
                </div>
              </>
            ) : (
              <p className={ui.empty}>No seat is assigned to this epic directly.</p>
            )}
            <Gloss k="assigned-seats" />
          </section>

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Records on demand</div>
            <details className={ui.fold}>
              <summary>Ticket details</summary>
              <div className={ui.metaRow}>
                <span>Id</span>
                <span className={ui.idMono}>{epic.id}</span>
              </div>
              <div className={ui.metaRow}>
                <span>Kind</span>
                <span>{epic.kind}</span>
              </div>
              <div className={ui.metaRow}>
                <span>Status</span>
                <span>{epic.status}</span>
              </div>
            </details>
            <details className={ui.fold}>
              <summary>Activity history</summary>
              <p className={ui.empty}>
                <Link to="/library/history">Open the full history <Icon name="forward" /></Link>
              </p>
            </details>
            <details className={ui.fold}>
              <summary>Links &amp; artifacts</summary>
              <p className={ui.empty}>
                <Link to={`/library/links?epic=${encodeURIComponent(id)}`}>Open links <Icon name="forward" /></Link>
              </p>
            </details>
          </section>
        </aside></details>
      </div>
    </div>
  );
}

/** Human #24: an assigned seat is a link to its row on Seats (/seats#<seat-id>, the id Seats.tsx
 *  puts on the <tr> and reads back from the hash), with the row's two actions inline — Message
 *  lands on that row with the composer open (?message=<seat-id>), Resume is the same
 *  POST /v1/sessions/resume Seats.tsx sends. The seat's own ticket is the tail of its id
 *  (role.<ticket>); the board's hint is shown verbatim either way. */
function AssignedSeatRow({ seatId, epicId }: { seatId: string; epicId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const [hint, setHint] = useState<string | null>(null);
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false });
  const caps = capsQ.data as PoolCapabilities | undefined;
  const canResume = !!(caps?.resume_parked || caps?.resume_closed);
  const dot = seatId.indexOf(".");
  const seatTicket = dot > 0 ? seatId.slice(dot + 1) : epicId;
  const anchor = `/seats#${encodeURIComponent(seatId)}`;

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
        <Link to={anchor} className={`${ui.idMono} ${styles.seatLink}`} data-testid="assigned-seat-link">
          {seatId}
        </Link>
        <div className={styles.seatActions}>
          <Link
            to={`/seats?message=${encodeURIComponent(seatId)}#${encodeURIComponent(seatId)}`}
            className={styles.seatAction}
            data-testid="assigned-seat-message"
            {...copyProps("seats", "message")}
          >
            Message
          </Link>
          {canResume ? (
            <button
              type="button"
              className={styles.seatAction}
              data-testid="assigned-seat-resume"
              disabled={resume.isPending}
              onClick={() => resume.mutate()}
              {...copyProps("seats", "resume")}
            >
              {resume.isPending ? "Resuming…" : "Resume"}
            </button>
          ) : null}
        </div>
      </div>
      {hint ? (
        <p className={styles.gloss} role="status" data-testid="assigned-seat-hint">
          {hint}
        </p>
      ) : null}
      {err ? (
        <p className={styles.seatError} role="alert" data-testid="assigned-seat-error">
          {err.hint ?? err.message}
        </p>
      ) : null}
    </div>
  );
}

function findDesign(docs: { id: string; doc_type: string }[]): string | null {
  return docs.find((d) => d.doc_type === "design")?.id ?? null;
}

function DocLink({ id }: { id: string | null }): React.JSX.Element {
  const drawer = useDocDrawer();
  if (!id) return <span>Not linked</span>;
  return (
    <button type="button" className={styles.docLink} onClick={() => drawer.openDoc(id)}>
      {id}
    </button>
  );
}

function OverviewTab({
  epicId,
  storyCount,
  totals,
  openGates,
  docs,
  criteria,
}: {
  epicId: string;
  storyCount: number;
  totals: { passed: number; total: number };
  openGates: number;
  docs: { id: string; doc_type: string; title: string }[];
  criteria: CriterionView[];
}): React.JSX.Element {
  const drawer = useDocDrawer();
  const design = docs.find((d) => d.doc_type === "design");
  return (
    <div className={styles.overview}>
      <p className={styles.pulse}>
        {storyCount === 0
          ? "No stories yet — this epic is still being shaped."
          : `${storyCount} ${storyCount === 1 ? "story" : "stories"} · ` +
            `${totals.total === 0 ? "no criteria yet" : `${totals.passed} of ${totals.total} criteria passed`} · ` +
            `${openGates} open ${openGates === 1 ? "gate" : "gates"}`}
      </p>
      {design ? (
        <p className={ui.empty}>
          Design:{" "}
          <button type="button" className={styles.docLink} onClick={() => drawer.openDoc(design.id)}>
            {design.title}
          </button>
        </p>
      ) : null}

      {/* The epic's OWN acceptance criteria, with the same verdict + reword + add controls as a
          ticket (design §16 epic "criteria list with add/verdict"), not just a tally. */}
      <div className={ui.sectionLabel}>Acceptance criteria ({criteria.length})</div>
      {criteria.length === 0 ? (
        <p className={ui.empty}>No acceptance criteria on the epic itself.</p>
      ) : (
        <div className={styles.epicCriteria}>
          {criteria.map((c) => (
            <CriterionCard
              key={c.id}
              criterion={c}
              ticketId={epicId}
              ruling={
                c.verdict === "pending" && c.evidence_ref ? { evidenceVersion: c.evidence_version ?? null } : undefined
              }
              canReword={c.verdict === "pending"}
              onOpenEvidence={(docId) => drawer.openDoc(docId)}
            />
          ))}
        </div>
      )}
      <details className={styles.addCrit}>
        <summary className={styles.addCritSummary}>Add an acceptance criterion</summary>
        <AddCriterion ticketId={epicId} />
      </details>
    </div>
  );
}

function WorkTab({
  epicId,
  epic,
  stories,
}: {
  epicId: string;
  epic: EpicTreeNode;
  stories: EpicTreeNode[];
}): React.JSX.Element {
  const [status, setStatus] = useState("");
  const [workType, setWorkType] = useState("");
  const [assignee, setAssignee] = useState("");
  const [q, setQ] = useState("");

  // q needs the board's search — resolve to matching ids via the tickets table (epic-scoped).
  const search = useQuery({
    queryKey: ["tickets", "table", epicId, "q", q],
    queryFn: () => getTicketsTable({ epic: epicId, q }),
    enabled: q.trim().length > 0,
  });
  const qHits = useMemo(
    () => (q.trim() ? new Set((search.data?.rows ?? []).map((r) => r.id)) : null),
    [q, search.data],
  );

  const all = flatten(epic).filter((n) => n.kind !== "epic");
  // Astra #36 (3): the search box narrows rows by their title / id text at once (no round trip);
  // the board's search adds description/tag hits when it answers.
  const needle = q.trim().toLowerCase();
  const textHit = (n: EpicTreeNode) =>
    !needle || n.title.toLowerCase().includes(needle) || n.id.toLowerCase().includes(needle) || !!qHits?.has(n.id);
  const match = (n: EpicTreeNode) =>
    (!status || n.status === status) &&
    (!workType || n.work_type === workType) &&
    (!assignee || (n.assignee ?? "").includes(assignee)) &&
    textHit(n);
  const filtered = all.filter(match);
  const filterCount = [status, workType, assignee].filter(Boolean).length;

  if (stories.length === 0) {
    return <p className={ui.empty}>This epic has no stories yet.</p>;
  }

  return (
    <div>
      {/* Astra #36 (3): a 40px search input, then a 40px "Filters" disclosure holding the
          status / work-type / assignee controls, above the rows. */}
      <div className={styles.workTools}>
        <input
          className={`${ui.input} ${styles.workSearch}`}
          type="search"
          aria-label="Search words"
          placeholder="Search by title or id…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          data-testid="work-search"
        />
        <details className={styles.filters} data-testid="work-filters-fold">
          <summary className={styles.filtersSummary}>
            Filters{filterCount > 0 ? ` (${filterCount})` : ""}
          </summary>
          <form className={styles.filterBar} onSubmit={(e) => e.preventDefault()} data-testid="work-filters">
            <select className={ui.select} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">any status</option>
              {["drafted", "designed", "signed_off", "ready", "in_progress", "in_review", "blocked", "done", "partial", "dropped"].map(
                (s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </option>
                ),
              )}
            </select>
            <select className={ui.select} aria-label="Work type" value={workType} onChange={(e) => setWorkType(e.target.value)}>
              <option value="">any work type</option>
              {["feature", "bug", "rnd", "creative"].map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
            <input
              className={ui.input}
              aria-label="Assignee contains"
              placeholder="assignee contains…"
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            />
          </form>
        </details>
      </div>

      <div className={styles.tree} data-testid="work-tree">
        <div className={styles.treeHead} aria-hidden="true">
          <span>Ticket</span>
          <span>Role</span>
          <span>Status</span>
          <span className={styles.treeHeadRight}>Criteria</span>
        </div>
        {stories.filter(match).length === 0 && filtered.length === 0 ? (
          <p className={ui.empty}>No tickets match these filters.</p>
        ) : (
          stories.map((s) => <TreeNode key={s.id} node={s} match={match} depth={0} />)
        )}
      </div>

      <div className={styles.kanban} data-testid="kanban">
        {KANBAN.map(([label, states]) => {
          const cards = filtered.filter((n) => states.includes(n.status));
          return (
            <div key={label} className={styles.kanbanCol}>
              <div className={styles.kanbanHead}>
                {label} <span className={styles.kanbanCount}>{cards.length}</span>
              </div>
              {cards.map((n) => (
                <Link key={n.id} to={`/ticket/${encodeURIComponent(n.id)}`} className={styles.kanbanCard}>
                  {/* Name first (§15): the story title leads; its id is secondary, in mono after. */}
                  <span className={styles.kanbanTitle}>{n.title}</span>
                  <span className={ui.idMono}>{n.id}</span>
                </Link>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TreeNode({
  node,
  match,
  depth,
}: {
  node: EpicTreeNode;
  match: (n: EpicTreeNode) => boolean;
  depth: number;
}): React.JSX.Element | null {
  const selfShown = match(node);
  const kids = node.children.map((k) => <TreeNode key={k.id} node={k} match={match} depth={depth + 1} />).filter(Boolean);
  if (!selfShown && kids.length === 0) return null;
  return (
    <>
      {selfShown ? (
        <div className={styles.treeRow} style={{ paddingLeft: 16 + depth * 20 }} data-testid="work-row">
          {/* Astra #36 (3): title first and wrapping; the id UNDER it in Consolas 12/18, one line. */}
          <Link to={`/ticket/${encodeURIComponent(node.id)}`} className={styles.treeLink}>
            <span className={styles.treeTitle}>{node.title}</span>
            <span className={styles.treeId}>{node.id}</span>
          </Link>
          <span className={styles.treeRole}>{roleOf(node.assignee)}</span>
          <span className={styles.treeStatus}>
            <StatusChip status={node.status} />
          </span>
          <span className={styles.treeTally}>{node.criteria}</span>
        </div>
      ) : null}
      {kids}
    </>
  );
}

function DocumentsTab({
  docs,
}: {
  docs: { id: string; doc_type: string; title: string }[];
}): React.JSX.Element {
  const drawer = useDocDrawer();
  if (docs.length === 0) return <p className={ui.empty}>No documents are linked to this epic yet.</p>;
  return (
    <ul className={styles.docList}>
      {docs.map((d) => (
        <li key={d.id}>
          <button type="button" className={styles.docRow} onClick={() => drawer.openDoc(d.id)}>
            <span className={ui.tag}>{d.doc_type.replace(/_/g, " ")}</span>
            <span className={styles.docTitle}>{d.title}</span>
            <span className={ui.idMono}>{d.id}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ThreadTab({
  epicId,
  thread,
  order,
  onToggleOrder,
  composerKind,
}: {
  epicId: string;
  thread: MessageView[];
  order: "newest" | "oldest";
  onToggleOrder: () => void;
  composerKind: "note" | "steer";
}): React.JSX.Element {
  const ordered = order === "newest" ? [...thread].reverse() : thread;
  const [reply, setReply] = useState<{ id: string; by: string } | null>(null);
  const [expanded, setExpanded] = useState(false);
  useScrollToHash(thread.length);
  return (
    <div className={styles.thread}>
      <div className={expanded ? styles.expandedComposer : undefined}>
      <Composer
        ticketId={epicId}
        kinds={reply ? ["answer", "note", "question", "steer", "status", "finding", "deviation"] : composerKind === "steer" ? ["steer", "note", "question", "status", "finding", "deviation", "answer"] : ["note", "question", "steer", "status", "finding", "deviation", "answer"]}
        showTo to={reply?.by} replyTo={reply?.id} replyToBy={reply?.by} onCancelReply={() => setReply(null)}
        expand={{ expanded, onToggle: () => setExpanded((x) => !x) }}
        placeholder={composerKind === "steer" ? "Steer this epic — this posts as a steer" : undefined}
      />
      </div>
      <div className={styles.threadHead}>
        <span className={ui.sectionLabel}>Conversation</span>
        <button type="button" className={styles.orderToggle} onClick={onToggleOrder} data-testid="order-toggle">
          {order === "newest" ? "Newest first" : "Oldest first"}
        </button>
      </div>
      {ordered.length === 0 ? (
        <p className={ui.empty}>No messages on this epic yet.</p>
      ) : (
        <ul className={styles.messages} data-testid="thread" tabIndex={0} aria-label="Conversation messages">
          {ordered.map((m) => (
            <li key={m.id} id={m.id} className={styles.message}>
              <AgentLine by={m.by} kind={m.kind} to={m.to} viewer={identity()} at={m.at} />
              <MessageText className={styles.messageText} text={m.text} />
              <button className={ui.button} onClick={() => { if (!pendingWork()) setReply({ id: m.id, by: m.by }); }}><Icon name="reply" /> Reply</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
