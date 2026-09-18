import { NavLink, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getActivity, getLibrary, getTicketsTable } from "../api/endpoints";
import type { TicketsFilter } from "../api/endpoints";
import { StatusChip } from "../components/StatusChip";
import { useDocDrawer } from "../components/DocDrawer";
import { PageHeader } from "../components/PageHeader";
import ui from "../components/ui.module.css";
import { ArtifactLink } from "../components/ArtifactLink";
import styles from "./Library.module.css";

// Library destination (design §4.2/§12): sub-nav Documents / Artifacts / Links / Tickets /
// History over one workspace. Tickets is the cross-epic table with the seven legacy filters bound
// to the query string (parity test_tickets_page_filters); History is the day-grouped activity
// replay (parity /ui/activity). The legacy /ui/tickets and /ui/activity paths redirect here.
const SECTIONS = ["documents", "artifacts", "links", "tickets", "history"] as const;
type Section = (typeof SECTIONS)[number];

export function LibraryPage(): React.JSX.Element {
  const { section = "tickets" } = useParams();
  const active = (SECTIONS.includes(section as Section) ? section : "tickets") as Section;
  const [params] = useSearchParams();
  const suffix = params.toString() ? `?${params.toString()}` : "";

  return (
    <>
      <PageHeader title="Library" subtitle="Every record on the board, in one place." />
      <nav className={styles.subnav} aria-label="Library sections">
        {SECTIONS.map((s) => (
          <NavLink
            key={s}
            to={`/library/${s}${suffix}`}
            className={({ isActive }) => `${styles.subnavItem} ${isActive ? styles.subnavActive : ""}`}
          >
            {s[0].toUpperCase() + s.slice(1)}
          </NavLink>
        ))}
      </nav>

      {active === "documents" ? <DocumentsSection /> : null}
      {active === "artifacts" ? <ArtifactsSection /> : null}
      {active === "links" ? <LinksSection /> : null}
      {active === "tickets" ? <TicketsSection /> : null}
      {active === "history" ? <HistorySection /> : null}
    </>
  );
}

function useEpicParam(): string | null {
  const [params] = useSearchParams();
  return params.get("epic");
}

function DocumentsSection(): React.JSX.Element {
  const epic = useEpicParam();
  const drawer = useDocDrawer();
  const q = useQuery({ queryKey: ["library", "docs", epic], queryFn: () => getLibrary(epic) });
  if (q.isPending) return <p className={ui.empty}>Loading…</p>;
  if (q.isError) return <p className={ui.banner} role="alert">{(q.error as Error).message}</p>;
  if (q.data.docs.length === 0) return <p className={ui.empty}>No documents.</p>;
  return (
    <ul className={styles.rows}>
      {q.data.docs.map((d) => (
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

function ArtifactsSection(): React.JSX.Element {
  const epic = useEpicParam();
  const q = useQuery({ queryKey: ["library", "artifacts", epic], queryFn: () => getLibrary(epic) });
  if (q.isPending) return <p className={ui.empty}>Loading…</p>;
  if (q.isError) return <p className={ui.banner} role="alert">{(q.error as Error).message}</p>;
  if (q.data.artifacts.length === 0) return <p className={ui.empty}>No artifacts.</p>;
  return (
    <ul className={styles.rows}>
      {q.data.artifacts.map((a) => (
        <li key={a.id} className={styles.artRow}>
          <span className={ui.tag}>{a.form}</span>
          {/^\/v1\/artifacts\/[^/]+\/content/.test(a.uri) || a.form === "upload" ? (
            <ArtifactLink id={a.id} label={a.uri} />
          ) : (
            <a className={styles.artUri} href={a.uri} target="_blank" rel="noreferrer">
              {a.uri}
            </a>
          )}
          {a.note ? <span className={styles.artNote}>{a.note}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function LinksSection(): React.JSX.Element {
  const epic = useEpicParam();
  const q = useQuery({ queryKey: ["library", "links", epic], queryFn: () => getLibrary(epic) });
  if (q.isPending) return <p className={ui.empty}>Loading…</p>;
  if (q.isError) return <p className={ui.banner} role="alert">{(q.error as Error).message}</p>;
  if (q.data.links.length === 0) return <p className={ui.empty}>No links.</p>;
  return (
    <table className={styles.table} tabIndex={0} aria-label="Records (scroll horizontally)">
      <thead>
        <tr>
          <th>from</th>
          <th>relation</th>
          <th>to</th>
        </tr>
      </thead>
      <tbody>
        {q.data.links.map((lk) => (
          <tr key={lk.id}>
            <td className={ui.idMono}>{lk.from_id}</td>
            <td>
              <span className={ui.tag}>{lk.relation}</span>
            </td>
            <td className={ui.idMono}>{lk.to_id}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const TICKET_FILTERS: { key: keyof TicketsFilter; label: string; options?: string[] }[] = [
  { key: "epic", label: "epic" },
  {
    key: "status",
    label: "status",
    options: ["drafted", "designed", "signed_off", "ready", "in_progress", "in_review", "blocked", "done", "partial", "dropped"],
  },
  { key: "kind", label: "kind", options: ["epic", "story", "task"] },
  { key: "work_type", label: "work type", options: ["feature", "bug", "rnd", "creative"] },
  { key: "assignee", label: "assignee" },
  { key: "tag", label: "tag" },
  { key: "q", label: "q" },
];

function TicketsSection(): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const filter: TicketsFilter = Object.fromEntries(
    TICKET_FILTERS.map((f) => [f.key, params.get(f.key) ?? ""]),
  ) as TicketsFilter;
  const q = useQuery({
    queryKey: ["tickets", "table", "library", params.toString()],
    queryFn: () => getTicketsTable(filter),
  });

  function set(key: string, value: string) {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    setParams(p, { replace: true });
  }

  return (
    <div>
      <form className={styles.filterBar} onSubmit={(e) => e.preventDefault()} data-testid="ticket-filters">
        {TICKET_FILTERS.map((f) =>
          f.options ? (
            <select
              key={f.key}
              className={ui.select}
              aria-label={f.label}
              value={(filter[f.key] as string) ?? ""}
              onChange={(e) => set(f.key, e.target.value)}
            >
              <option value="">any {f.label}</option>
              {f.options.map((o) => (
                <option key={o} value={o}>
                  {o.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          ) : (
            <input
              key={f.key}
              className={ui.input}
              aria-label={f.label}
              placeholder={f.label}
              value={(filter[f.key] as string) ?? ""}
              onChange={(e) => set(f.key, e.target.value)}
            />
          ),
        )}
      </form>

      {q.isPending ? (
        <p className={ui.empty}>Loading…</p>
      ) : q.isError ? (
        <p className={ui.banner} role="alert">
          {(q.error as Error).message}
        </p>
      ) : q.data.rows.length === 0 ? (
        <p className={ui.empty}>No tickets match these filters.</p>
      ) : (
        <table className={styles.table} tabIndex={0} aria-label="Tickets (scroll horizontally)" data-testid="tickets-table">
          <thead>
            <tr>
              <th>id</th>
              <th>epic</th>
              <th>title</th>
              <th>kind</th>
              <th>status</th>
              <th>assignee</th>
              <th>criteria</th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((t) => (
              <tr key={t.id}>
                <td className={ui.idMono}>{t.id}</td>
                <td className={ui.idMono}>{t.epic_id ?? "—"}</td>
                <td>{t.title}</td>
                <td>
                  {t.kind}/{t.work_type}
                </td>
                <td>
                  <StatusChip status={t.status} />
                </td>
                <td>{t.assignee ?? "—"}</td>
                <td className={ui.idMono}>
                  {t.criteria.passed}/{t.criteria.total}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function HistorySection(): React.JSX.Element {
  const q = useQuery({ queryKey: ["activity"], queryFn: () => getActivity() });
  if (q.isPending) return <p className={ui.empty}>Loading…</p>;
  if (q.isError) return <p className={ui.banner} role="alert">{(q.error as Error).message}</p>;
  if (q.data.length === 0) return <p className={ui.empty}>No activity yet.</p>;
  return (
    <div className={styles.history}>
      {q.data.map((day) => (
        <section key={day.day}>
          <div className={ui.sectionLabel}>{day.day}</div>
          <ul className={styles.rows}>
            {day.events.map((e, i) => (
              <li key={`${e.subject_id}-${i}`} className={styles.event}>
                <span className={styles.eventTime}>{e.at.slice(11, 16)}</span>
                <span className={styles.eventLine}>{e.line}</span>
                <span className={ui.idMono}>{e.subject_id}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
