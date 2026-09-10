import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getEpicPage, getEpicsSummary, getTicketsTable } from "../api/endpoints";
import type { CriterionView, EpicSummaryRow, EpicTreeNode, MessageView, TicketStatus } from "../api/types";
import { StatusChip } from "../components/StatusChip";
import { ProcessStrip } from "../components/ProcessStrip";
import { StatusControl } from "../components/StatusControl";
import { GateOpenControl } from "../components/GateOpenControl";
import { GateForm } from "../components/GateForm";
import { AssignControl } from "../components/AssignControl";
import { CriterionCard } from "../components/CriterionCard";
import { AddCriterion } from "../components/CriterionControls";
import { Tabs } from "../components/Tabs";
import { Composer } from "../components/Composer";
import { AgentLine } from "../components/AgentLine";
import { useDocDrawer } from "../components/DocDrawer";
import { identity } from "../auth/identity";
import ui from "../components/ui.module.css";
import styles from "./Epic.module.css";

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

const KANBAN: [string, string[]][] = [
  ["Backlog", ["drafted", "designed", "signed_off", "blocked"]],
  ["Ready", ["ready"]],
  ["In progress", ["in_progress"]],
  ["In review", ["in_review"]],
  ["Done", ["done", "partial"]],
];

export function EpicPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const [tab, setTab] = useState<"overview" | "work" | "documents" | "thread">("overview");
  const [composerKind, setComposerKind] = useState<"note" | "steer">("note");
  const [order, setOrder] = useState<"newest" | "oldest">("newest");

  const page = useQuery({ queryKey: ["epic", id], queryFn: () => getEpicPage(id) });
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
  // The board titles an epic with the owner's words truncated; showing that line as the h1 AND the
  // full words under "Owner's words" repeats the same text twice (human report 2026-09-10). When the
  // title is a prefix of the words, the h1 carries the words in full and the figure is omitted.
  const titleIsTruncatedWords =
    words !== epic.title && words.startsWith(epic.title.replace(/[\u2026.]+$/, "").trimEnd());
  const heading = titleIsTruncatedWords ? words : epic.title;
  const stories = epic.children;
  const directive = [...data.thread].reverse().find((m) => m.kind === "steer") ?? null;
  const row = summary.data?.find((r: EpicSummaryRow) => r.id === id) ?? null;
  const totals = tallyTotals(epic);
  const workCount = flatten(epic).filter((n) => n.kind !== "epic").length;

  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "work", label: "Work", count: workCount },
    { key: "documents", label: "Documents", count: data.docs.length },
    { key: "thread", label: "Thread", count: data.thread.length },
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

      <div className={styles.head}>
        <div className={styles.idline}>
          <span className={ui.idMono}>{epic.id}</span>
          <StatusChip status={epic.status} />
        </div>
        <h1 className={styles.title}>{heading}</h1>
        <button type="button" className={styles.steer} onClick={steer}>
          Steer this epic
        </button>
      </div>

      {titleIsTruncatedWords ? null : (
      <figure className={styles.words}>
        <figcaption className={ui.sectionLabel}>Owner&rsquo;s words · original request</figcaption>
        <blockquote className={ui.quote}>{words}</blockquote>
      </figure>
      )}

      {directive ? (
        <div className={ui.directive} data-testid="directive">
          {directive.text}
        </div>
      ) : null}

      <ProcessStrip
        status={epic.status}
        ariaLabel="Epic process"
        nextAction={<a href="#epic-status">Change the epic&rsquo;s status →</a>}
      />

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

          {tab === "thread" ? (
            <ThreadTab
              epicId={id}
              thread={data.thread}
              order={order}
              onToggleOrder={() => setOrder((o) => (o === "newest" ? "oldest" : "newest"))}
              composerKind={composerKind}
            />
          ) : null}
        </div>

        <aside className={styles.rail} aria-label="Epic details">
          <section className={ui.card} id="epic-status">
            <div className={ui.sectionLabel}>Change status</div>
            <StatusControl ticketId={id} currentStatus={epic.status as TicketStatus} />
          </section>

          {data.answerable_gates.length > 0 ? (
            <section className={ui.card} data-testid="epic-answer-gates">
              <div className={ui.sectionLabel}>Answer a decision ({data.answerable_gates.length})</div>
              {data.answerable_gates.map((g) => (
                <GateForm key={`${g.ticket_id}:${g.gate}`} gate={g} />
              ))}
            </section>
          ) : null}

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Raise a decision</div>
            <GateOpenControl ticketId={id} />
          </section>

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Assign or spawn a seat</div>
            <AssignControl ticketId={id} currentAssignee={epic.assignee ?? null} />
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

          <section className={ui.card}>
            <div className={ui.sectionLabel}>Assigned seat</div>
            {row && row.assigned_seats.length > 0 ? (
              <>
                {row.assigned_seats.map((s) => (
                  <div key={s} className={styles.seat}>
                    <span className={ui.idMono}>{s}</span>
                  </div>
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
                <Link to="/library/history">Open the full history →</Link>
              </p>
            </details>
            <details className={ui.fold}>
              <summary>Links &amp; artifacts</summary>
              <p className={ui.empty}>
                <Link to={`/library/links?epic=${encodeURIComponent(id)}`}>Open links →</Link>
              </p>
            </details>
          </section>
        </aside>
      </div>
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
  const match = (n: EpicTreeNode) =>
    (!status || n.status === status) &&
    (!workType || n.work_type === workType) &&
    (!assignee || (n.assignee ?? "").includes(assignee)) &&
    (!qHits || qHits.has(n.id));
  const filtered = all.filter(match);

  if (stories.length === 0) {
    return <p className={ui.empty}>This epic has no stories yet.</p>;
  }

  return (
    <div>
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
        <input
          className={ui.input}
          aria-label="Search words"
          placeholder="words in title/description/tags"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </form>

      <div className={styles.tree} data-testid="work-tree">
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
        <div className={styles.treeRow} style={{ paddingLeft: depth * 20 }}>
          <Link to={`/ticket/${encodeURIComponent(node.id)}`} className={styles.treeLink}>
            <span className={styles.treeTitle}>{node.title}</span>
            <span className={ui.idMono}>{node.id}</span>
          </Link>
          <span className={styles.treeRole}>{roleOf(node.assignee)}</span>
          <StatusChip status={node.status} />
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
  return (
    <div className={styles.thread}>
      <Composer
        ticketId={epicId}
        kinds={composerKind === "steer" ? ["steer", "note"] : ["note", "steer"]}
        key={composerKind}
        placeholder={composerKind === "steer" ? "Steer this epic — this posts as a steer" : undefined}
      />
      <div className={styles.threadHead}>
        <span className={ui.sectionLabel}>Thread</span>
        <button type="button" className={styles.orderToggle} onClick={onToggleOrder} data-testid="order-toggle">
          {order === "newest" ? "Newest first" : "Oldest first"}
        </button>
      </div>
      {ordered.length === 0 ? (
        <p className={ui.empty}>No messages on this epic yet.</p>
      ) : (
        <ul className={styles.messages} data-testid="thread">
          {ordered.map((m) => (
            <li key={m.id} className={styles.message}>
              <AgentLine by={m.by} kind={m.kind} to={m.to} viewer={identity()} at={m.at} />
              <div className={styles.messageText}>{m.text}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
