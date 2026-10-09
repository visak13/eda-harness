import { Link, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getPains } from "../api/endpoints";
import type { PainRow } from "../api/types";
import ui from "../components/ui.module.css";
import styles from "./Pains.module.css";

// e0cec S6 (design-b6a55eed13 §4.C): the Pains view — every pain in the board's one store, filtered by
// status (open / fixed / ticket, plus duplicate / invalid), each linked to the commit that fixed it or the
// ticket that owns the fix. The filter lives in the query string (?status=) so a link reopens it.
const STATUSES = ["open", "fixed", "ticket", "duplicate", "invalid"] as const;
const WORD: Record<string, string> = { open: "Open", fixed: "Fixed", ticket: "Ticketed", duplicate: "Duplicate", invalid: "Invalid" };

function chipClass(status: string): string {
  if (status === "fixed") return ui.done;
  if (status === "ticket") return ui.active;
  return "";
}

function Reference({ p }: { p: PainRow }): React.JSX.Element {
  if (p.status === "fixed" && p.fixed_commit) {
    const sha = p.fixed_commit.slice(0, 10);
    return p.commit_url
      ? <a href={p.commit_url} target="_blank" rel="noreferrer" aria-label={`commit ${p.fixed_commit}`}>{sha}</a>
      : <code title="no commit link yet: the fix is not on the pushed branch" data-testid="pain-commit-unlinked">{sha}</code>;
  }
  if (p.status === "ticket" && p.ticket_ref) {
    return <Link to={`/ticket/${encodeURIComponent(p.ticket_ref)}`}>{p.ticket_ref}</Link>;
  }
  if (p.status === "duplicate" && p.dup_of) return <span>of <code>{p.dup_of}</code></span>;
  return <span aria-label="no reference">—</span>;
}

export function PainsSection(): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "open";
  const q = useQuery({ queryKey: ["pains", status], queryFn: () => getPains(status) });

  function setStatus(value: string) {
    const p = new URLSearchParams(params);
    p.set("status", value);
    setParams(p, { replace: true });
  }

  return (
    <div data-testid="pains-view">
      <div className={styles.bar}>
        <label className={ui.sectionLabel} htmlFor="pains-status">Status</label>
        <select id="pains-status" data-testid="pains-status" className={ui.select} value={status}
          onChange={(e) => setStatus(e.target.value)}>
          <option value="all">All</option>
          {STATUSES.map((s) => <option key={s} value={s}>{WORD[s]}</option>)}
        </select>
        {q.data ? <span className={styles.count} data-testid="pains-count">{q.data.length} {q.data.length === 1 ? "pain" : "pains"}</span> : null}
      </div>
      {q.isPending ? <p className={ui.empty}>Loading…</p>
        : q.isError ? <p className={ui.banner} role="alert">{(q.error as Error).message}</p>
        : q.data.length === 0 ? <p className={ui.empty}>No {status === "all" ? "" : `${WORD[status]?.toLowerCase() ?? status} `}pains.</p>
        : (
          <table className={styles.table} tabIndex={0} aria-label="Pains (scroll horizontally)" data-testid="pains-table">
            <thead>
              <tr><th>Id</th><th>Severity</th><th>Area</th><th>Symptom</th><th>Status</th><th>Commit or ticket</th></tr>
            </thead>
            <tbody>
              {q.data.map((p) => (
                <tr key={p.id} data-testid="pain-row" data-status={p.status}>
                  <td className={ui.idMono}>{p.id}</td>
                  <td className={styles.sev}>{p.severity}</td>
                  <td>{p.area}</td>
                  <td className={styles.symptom}>{p.symptom}</td>
                  <td><span className={`${ui.chip} ${chipClass(p.status)}`} data-testid="pain-status">{WORD[p.status] ?? p.status}</span></td>
                  <td className={styles.ref}><Reference p={p} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  );
}
