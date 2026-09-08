import { useSearchParams } from "react-router";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getEpicsSummary } from "../api/endpoints";
import type { EpicSummaryRow } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { StatusChip } from "../components/StatusChip";
import ui from "../components/ui.module.css";
import styles from "./Epics.module.css";

// Epics destination (design §4.2, criterion c-63b8ab97ad): a calm portfolio, one row per epic,
// with the status WORD, a criteria tally as words ("N of M passed" / "None defined" — no bar for
// 0/0), the date and the waiting reason. status/q filters are bound to the query string (parity
// with the legacy /ui page: ?status=&q=), so a filtered view is a shareable URL.
const STATUS_OPTIONS = [
  "open",
  "drafted",
  "designed",
  "signed_off",
  "ready",
  "in_progress",
  "in_review",
  "blocked",
  "done",
  "partial",
  "dropped",
];

function tally(row: EpicSummaryRow): { text: string; pct: number | null } {
  const { passed, total } = row.criteria;
  if (total === 0) return { text: "None defined", pct: null };
  return { text: `${passed} of ${total} passed`, pct: Math.round((100 * passed) / total) };
}

export function EpicsPage(): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const q = params.get("q") ?? "";

  const epics = useQuery({
    queryKey: ["epics", "summary", status, q],
    queryFn: () => getEpicsSummary({ status: status || null, q: q || null }),
  });

  function set(key: string, value: string) {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    setParams(p, { replace: true });
  }

  return (
    <>
      <PageHeader title="Epics" subtitle="Every epic on the board and its pulse." />

      <form className={styles.filters} role="search" onSubmit={(e) => e.preventDefault()}>
        <select
          className={ui.select}
          aria-label="Filter by status"
          value={status}
          onChange={(e) => set("status", e.target.value)}
        >
          <option value="">any status</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <input
          className={ui.input}
          type="search"
          aria-label="Search epic titles and descriptions"
          placeholder="Search words in epic titles / descriptions"
          value={q}
          onChange={(e) => set("q", e.target.value)}
        />
      </form>

      {epics.isPending ? (
        <p className={ui.empty}>Loading epics…</p>
      ) : epics.isError ? (
        <p className={ui.banner} role="alert">
          Could not load epics: {(epics.error as Error).message}
        </p>
      ) : epics.data.length === 0 ? (
        <p className={ui.empty}>No epics match this filter. Adjust the status or search above.</p>
      ) : (
        <ul className={styles.list} data-testid="epic-list">
          {epics.data.map((row) => {
            const t = tally(row);
            return (
              <li key={row.id}>
                <Link className={styles.row} to={`/epic/${encodeURIComponent(row.id)}`}>
                  <div className={styles.main}>
                    {/* Name first (§15): the epic's title leads; the id is secondary, in mono after. */}
                    <div className={styles.titleLine}>
                      <div className={styles.title}>{row.title}</div>
                      <StatusChip status={row.status} />
                    </div>
                    <span className={ui.idMono}>{row.id}</span>
                    {row.waiting_reason.reason ? (
                      <div className={styles.reason} data-testid="waiting-reason">
                        {row.waiting_reason.reason}
                      </div>
                    ) : null}
                  </div>
                  <div className={styles.meta}>
                    <div className={styles.tally}>{t.text}</div>
                    {t.pct !== null ? (
                      <div className={styles.bar} aria-hidden="true">
                        <span style={{ width: `${t.pct}%` }} />
                      </div>
                    ) : null}
                    <div className={styles.date}>{row.created_at.slice(0, 10)}</div>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
