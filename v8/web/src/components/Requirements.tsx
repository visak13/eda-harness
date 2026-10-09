import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { getEpicRequirements, type RequirementRow, type RequirementsList } from "../api/requirements";
import { Clamp } from "./Clamp";
import { usePersonName } from "./usePersonName";
import ui from "./ui.module.css";
import styles from "./Requirements.module.css";

// s-aa76c83998 (owner m-45541e67b1): the requirements people marked on this epic, shown where the owner works. Each
// row says its state in a WORD (never colour alone), quotes the marked words (clamped, one click for the rest) and,
// once linked, names the criterion or the design section that covers it. The open list is what holds the epic
// open; the board's own `blocked_reason` is shown verbatim.

function Linked({ r }: { r: RequirementRow }): React.JSX.Element | null {
  if (r.criterion) {
    return <p className={styles.note} data-testid="req-link">Covered by <span className={ui.idMono}>{r.criterion}</span></p>;
  }
  if (r.doc) {
    return (
      <p className={styles.note} data-testid="req-link">
        In the design: <Link className={styles.coverLink} to={{ pathname: `/doc/${encodeURIComponent(r.doc.id)}`, search: `?v=${r.doc.version}` }}>
          <span className={ui.idMono}>{r.doc.id} v{r.doc.version}</span> · {r.doc.heading}</Link>
      </p>
    );
  }
  return null;
}

function Item({ r }: { r: RequirementRow }): React.JSX.Element {
  const nameOf = usePersonName();
  const open = r.state === "open";
  return (
    <li className={styles.item} data-testid="req-row" data-req={r.id} data-state={r.state}>
      <div className={styles.head}>
        <span className={`${styles.state} ${open ? styles.open : styles.linked}`} data-testid="req-state"
          title={open ? "the architect has not linked it to a criterion or a design section yet" : "linked"}>{open ? "open" : "linked"}</span>
        <span className={ui.idMono}>{r.id}</span>
        <span className={styles.by}>{nameOf(r.by)} · {r.at.slice(0, 10)}</span>
      </div>
      <Clamp className={styles.words} text={r.text} lines={3} testId="req-words" />
      <Linked r={r} />
    </li>
  );
}

export function useEpicRequirements(epicId: string) {
  return useQuery({ queryKey: ["epic", epicId, "requirements"], queryFn: () => getEpicRequirements(epicId), retry: false });
}

function tally(rows: RequirementRow[]): string {
  const open = rows.filter((r) => r.state === "open").length;
  return `${rows.length} ${rows.length === 1 ? "requirement" : "requirements"} · ${open} open`;
}

/** The epic page's list: open requirements first, then the linked ones. */
export function RequirementsSection({ epicId }: { epicId: string }): React.JSX.Element {
  const q = useEpicRequirements(epicId);
  const rows = [...(q.data?.requirements ?? [])].sort((a, b) => Number(b.state === "open") - Number(a.state === "open"));
  return (
    <section data-testid="requirements" aria-labelledby="requirements-h">
      <div className={ui.sectionLabel} id="requirements-h">Requirements{q.data ? ` (${rows.length})` : ""}</div>
      {q.isPending ? <p className={ui.empty}>Loading the requirements…</p> : null}
      {q.isError ? <p className={ui.banner} role="alert">Could not load the requirements: {(q.error as Error).message}</p> : null}
      {q.data && rows.length === 0 ? <p className={ui.empty} data-testid="requirements-empty">No requirements marked. Use Mark as requirement on a quote.</p> : null}
      {rows.length > 0 ? (
        <>
          <p className={styles.tally} data-testid="requirements-tally">{tally(rows)}</p>
          <ul className={styles.list}>{rows.map((r) => <Item key={r.id} r={r} />)}</ul>
        </>
      ) : null}
    </section>
  );
}

/** How many requirements on this epic wait for the architect to link them. The header's Needs attention field says it. */
export function useOpenRequirements(epicId: string): number {
  const list: RequirementsList | undefined = useEpicRequirements(epicId).data;
  return list?.requirements.filter((r) => r.state === "open").length ?? 0;
}

/** Why the acceptance gate is not open: the board's `blocked_reason` without its ids. Nothing renders while nothing is open. */
export function GateHeldCaption({ epicId }: { epicId: string }): React.JSX.Element | null {
  const list: RequirementsList | undefined = useEpicRequirements(epicId).data;
  // the board names the requirement ids for agents; the person reads the count (an id wrapped mid-id, qa fail 12)
  const reason = list?.blocked_reason?.replace(/\s*\(req-[^)]*\)/g, "");
  if (!reason) return null;
  return (
    <div className={styles.gate} role="status" data-testid="gate-held" data-held="true">
      <strong>Acceptance waits on</strong> <span data-testid="gate-blocked-reason">{reason}</span>
    </div>
  );
}
