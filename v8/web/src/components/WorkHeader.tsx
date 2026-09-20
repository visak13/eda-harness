import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
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

// Legacy pre-R1 destinations (old Slack pings and bookmarks carry these): the tabbed epic/ticket
// used ?tab=/#hash; R1 replaced the tabs with the links-row viewers (epic c-bb6cf0d4d6 keeps the
// old navigation working). documents→the Files viewer, work/overview→the Work viewer, thread is the
// conversation itself (no viewer). A #m-<id> message anchor always wins — it scrolls to the message
// and never opens a viewer (the page owns that hash).
const LEGACY_VIEW: Record<string, string | null> = { documents: "files", work: "work", overview: "work", thread: null };

export function WorkHeader(p: WorkHeaderProps): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
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

  // Route request opens the source-bound review, never answers it (design-a2e5369133 §gate typed
  // review path; restores the ?request= handling 9734d1d dropped from ContextualWork). A deep link
  // /epic|ticket/<id>?request=<gate-id> (GateForm "Review design at source", an S5 notification)
  // matches the design_signoff gate and opens ?doc=<design_ref>; DocDrawer forwards ?request= to the
  // viewer so it renders the review surface, not a plain doc. It sets ?doc only, so the gate is untouched.
  const request = params.get("request");
  const openedRequest = useRef<string | null>(null);
  useEffect(() => {
    const gate = data?.gates.find((g) => g.id === request && g.data.gate === "design_signoff");
    if (request && gate && designRef && openedRequest.current !== request && !params.get("doc")) {
      openedRequest.current = request;
      setParams((old) => { const next = new URLSearchParams(old); next.set("doc", designRef); return next; }, { replace: true });
    }
  }, [request, data, designRef, params, setParams]);

  // Migrate a legacy ?tab=/#hash entry once (finding 9, epic c-bb6cf0d4d6): rewrite it to ?view=
  // (replace) so an old bookmark opens the matching viewer. A #m- message anchor wins — the tab is
  // dropped but no viewer opens and the anchor is kept so the page can scroll to the message.
  const migrated = useRef(false);
  useEffect(() => {
    if (migrated.current) return;
    const anchor = location.hash.startsWith("#m-");
    const tab = params.get("tab");
    const hashKey = anchor ? "" : location.hash.replace(/^#/, "");
    const key = tab && tab in LEGACY_VIEW ? tab : hashKey in LEGACY_VIEW ? hashKey : null;
    if (!tab && key === null) return;
    migrated.current = true;
    const nextView = anchor ? null : key ? LEGACY_VIEW[key] : null;
    const q = new URLSearchParams(params);
    q.delete("tab");
    if (nextView && !q.get("view")) q.set("view", nextView);
    const search = q.toString();
    navigate({ search: search ? `?${search}` : "", hash: anchor ? location.hash : "" }, { replace: true });
  }, [location.hash, params, navigate]);

  // Compact header on a phone (finding 19, epic c-63fdab92a4 / conversation-first): the metadata
  // grid and links row collapse behind a disclosure below 768px so the first message is in the first
  // viewport; open (and the disclosure UI hidden) at wider widths. Defaults open so jsdom, which has
  // no matchMedia, still renders the metadata for the unit tests.
  const [contextOpen, setContextOpen] = useState(true);
  useEffect(() => {
    const mq = window.matchMedia?.("(max-width: 767px)");
    if (!mq) return;
    const apply = () => setContextOpen(!mq.matches);
    apply();
    mq.addEventListener?.("change", apply);
    return () => mq.removeEventListener?.("change", apply);
  }, []);

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

      <details className={styles.context} open={contextOpen} onToggle={(e) => setContextOpen(e.currentTarget.open)}>
        <summary className={styles.contextSummary} data-testid="work-context-toggle">
          <StatusChip status={p.status} size="badge" />
          <span>{attention || "Details, files & history"}</span>
        </summary>
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
      </details>

      <Drawer open={drawerOpen} label={viewerTitle} title={<span className={styles.drawerTitle}>{viewerTitle}
        {view !== "work" ? <Link className={styles.openTab} target="_blank" to={`/records/${encodeURIComponent(p.ticketId)}?${new URLSearchParams({ view: view ?? "files", ...(params.get("category") ? { category: params.get("category")! } : {}), as: identity() })}`}>Open in tab <Icon name="external" size={16} /></Link> : null}
      </span>} onClose={() => choose(null)}>
        {view === "history" ? <HistoryViewer ticketId={p.ticketId} /> : view === "work" ? p.work : <FilesViewer ticketId={p.ticketId} />}
      </Drawer>
    </header>
  );
}
