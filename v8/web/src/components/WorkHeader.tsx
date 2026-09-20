import { Link, useSearchParams } from "react-router";
import { Avatar } from "./Avatar";
import { StatusChip } from "./StatusChip";
import { Drawer } from "./Drawer";
import { useDocDrawer } from "./DocDrawer";
import { Icon } from "./Icon";
import { identity } from "../auth/identity";
import { attentionLine, FilesViewer, HistoryViewer, useWorkContext } from "./ContextualWork";
import styles from "./WorkHeader.module.css";

// The one work header shared by the epic and the ticket page (design-a2e5369133 §WorkHeader,
// render revision3-clean-epic.png): topline breadcrumb + Actions ▾, the 32px title, one purpose
// line, the STATUS / OWNER / ASSIGNED / NEEDS ATTENTION grid, then the links row (Design tinted,
// Files & evidence, History, Work). The links open the source-bound viewers in the right drawer;
// `?view=` keeps them deep-linkable. Board facts come from the page payload first and from
// GET /v1/tickets/{id}/contextual when the board has it, so an older board still renders the header.

export interface WorkHeaderProps {
  ticketId: string;
  kind: "epic" | "ticket";
  title: string;
  /** One sentence under the title (the brief's first line, or the description). */
  purpose?: string | null;
  status: string;
  assignee: string | null;
  /** Page-side owner when the contextual route is missing. */
  owner?: string | null;
  designRef?: string | null;
  /** Breadcrumb: the epic this ticket belongs to (ticket pages). */
  epic?: { id: string; title: string } | null;
  /** The Actions ▾ control. */
  actions: React.ReactNode;
  /** The Work viewer body (stories/kanban/criteria/process for an epic; criteria/docs for a ticket). */
  work: React.ReactNode;
  /** Stops the design link from claiming "review requested" when the page knows better. */
  reviewRequested?: boolean;
}

function short(text: string | null | undefined): string | null {
  if (!text) return null;
  const line = text.trim().split(/\n/)[0] ?? "";
  return line.length > 180 ? `${line.slice(0, 177)}…` : line;
}

export function WorkHeader(p: WorkHeaderProps): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const { openDoc } = useDocDrawer();
  const ctx = useWorkContext(p.ticketId);
  const view = params.get("view");
  const drawerOpen = !params.get("doc") && !params.get("compose") && (view === "files" || view === "history" || view === "work");
  function choose(next: string | null) {
    setParams((old) => { const q = new URLSearchParams(old); if (next) q.set("view", next); else q.delete("view"); return q; }, { replace: next === null });
  }
  const data = ctx.data;
  const owner = data?.owner ?? p.owner ?? null;
  const assignee = data?.assignee ?? p.assignee;
  const designRef = data?.design_ref ?? p.designRef ?? null;
  const reviewRequested = p.reviewRequested ?? Boolean(data?.gates.some((g) => g.data.gate === "design_signoff"));
  const attention = data ? attentionLine(data) : "";
  const viewerTitle = view === "history" ? "History" : view === "work" ? "Work" : "Files & evidence";
  const crumbTitle = p.kind === "epic" ? p.title : p.epic?.title ?? p.epic?.id ?? "Epic";
  const crumbTo = p.kind === "epic" ? "/epics" : `/epic/${encodeURIComponent(p.epic?.id ?? "")}`;

  return (
    <header className={styles.header} data-testid="work-header">
      <div className={styles.topline}>
        <nav aria-label="Breadcrumb" className={styles.crumb}>
          <Link to="/epics">Epics</Link>
          <span aria-hidden="true">/</span>
          {p.kind === "epic" ? <span className={styles.here}>{crumbTitle}</span> : <>
            <Link to={crumbTo}>{crumbTitle}</Link>
            <span aria-hidden="true">/</span>
            <span className={styles.here}>{p.ticketId}</span>
          </>}
        </nav>
        {p.actions}
      </div>
      <h1 className={styles.title} data-testid="work-title">{p.title}</h1>
      {short(p.purpose) ? <p className={styles.purpose} data-testid="work-purpose">{short(p.purpose)}</p> : null}

      <dl className={styles.metadata} data-testid="work-metadata">
        <div>
          <dt className={styles.label}>Status</dt>
          <dd className={styles.value} data-testid="work-status"><StatusChip status={p.status} size="badge" /></dd>
        </div>
        <div>
          <dt className={styles.label}>Owner</dt>
          <dd className={styles.value} data-testid="work-owner">{owner ? <><Avatar id={owner} size={28} />{owner}</> : <span className={styles.muted}>Unknown</span>}</dd>
        </div>
        <div>
          <dt className={styles.label}>Assigned</dt>
          <dd className={styles.value} data-testid="work-assigned">{assignee ? <><Avatar id={assignee} size={28} />{assignee.includes(".") ? assignee.split(".")[0] : assignee}</> : <span className={styles.muted}>Unassigned</span>}</dd>
        </div>
        <div>
          <dt className={styles.label}>Needs attention</dt>
          <dd className={styles.value} data-testid="work-attention">
            {attention ? <span className={styles.coral}><Icon name="warning" size={18} />{attention}</span>
              : <span className={styles.muted}>{ctx.isError ? "Unknown on this board" : ctx.isPending ? "…" : "Nothing open"}</span>}
          </dd>
        </div>
      </dl>

      <div className={styles.links} data-testid="work-links">
        {designRef ? (
          <button type="button" className={`${styles.link} ${styles.design}`} onClick={() => openDoc(designRef)} data-testid="work-design">
            <Icon name="design" /> Design{reviewRequested ? " · review requested" : ""}
          </button>
        ) : null}
        <button type="button" className={styles.link} onClick={() => choose("files")} data-testid="work-files"><Icon name="files" /> Files &amp; evidence</button>
        <button type="button" className={styles.link} onClick={() => choose("history")} data-testid="work-history"><Icon name="history" /> History</button>
        <button type="button" className={styles.link} onClick={() => choose("work")} data-testid="work-work"><Icon name="work" /> Work</button>
      </div>

      <Drawer open={drawerOpen} title={<span className={styles.drawerTitle}>{viewerTitle}
        {view !== "work" ? <Link className={styles.openTab} target="_blank" to={`/records/${encodeURIComponent(p.ticketId)}?${new URLSearchParams({ view: view ?? "files", as: identity() })}`}>Open in tab <Icon name="external" size={16} /></Link> : null}
      </span>} onClose={() => choose(null)}>
        {view === "history" ? <HistoryViewer ticketId={p.ticketId} /> : view === "work" ? p.work : <FilesViewer ticketId={p.ticketId} />}
      </Drawer>
    </header>
  );
}
