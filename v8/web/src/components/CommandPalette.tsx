import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EpicSummaryRow, SeatsView } from "../api/types";
import { getEpicsSummary } from "../api/endpoints";
import styles from "./CommandPalette.module.css";

// Find (Ctrl-K / the sidebar "Find" button): a command palette over GET /v1/find — the board's own
// search (FTS5 exact words ∪ the semantic index, fused) over tickets, docs, messages and criteria —
// plus seats matched by handle on the client. Human defect #12 (m-783e725c2f, 2026-09-10): the
// sidebar control was a plate artifact with no handler. Results are grouped by type, each row
// carries the type word, the title (or the hit's snippet) and its epic; Enter opens the row's
// destination; Esc closes; Tab is trapped inside the dialog; the opener gets focus back.

export interface FindHit {
  type: "ticket" | "doc" | "message" | "criterion";
  id: string;
  score: number;
  snippet: string;
  title?: string;
  status?: string;
  ticket_id?: string;
  epic_id?: string;
  scope?: string | null;
}

export interface PaletteRow {
  key: string;
  group: string; // "Epics" | "Tickets" | "Documents" | "Messages" | "Criteria" | "Seats"
  typeWord: string;
  title: string;
  epic: string | null;
  to: string; // router destination (may carry a #anchor)
}

const GROUP_ORDER = ["Epics", "Tickets", "Documents", "Messages", "Criteria", "Seats"];

function stripMarks(s: string): string {
  return s.replace(/[\[\]]/g, "");
}

/** Destination and display row for one /v1/find hit. Exported for the unit test. */
export function rowFor(h: FindHit, epicTitle: (id: string | undefined) => string | null): PaletteRow | null {
  const epic = h.epic_id ? (epicTitle(h.epic_id) ?? h.epic_id) : null;
  switch (h.type) {
    case "ticket": {
      const isEpic = h.id.startsWith("epic-") || h.epic_id === h.id;
      return {
        key: `ticket:${h.id}`,
        group: isEpic ? "Epics" : "Tickets",
        typeWord: isEpic ? "Epic" : "Ticket",
        title: h.title ?? stripMarks(h.snippet) ?? h.id,
        epic: isEpic ? null : epic,
        to: isEpic ? `/epic/${encodeURIComponent(h.id)}` : `/ticket/${encodeURIComponent(h.id)}`,
      };
    }
    case "doc":
      return {
        key: `doc:${h.id}`,
        group: "Documents",
        typeWord: "Document",
        title: h.title ?? stripMarks(h.snippet),
        epic,
        to: `/doc/${encodeURIComponent(h.id)}`,
      };
    case "message":
      if (!h.ticket_id) return null;
      return {
        key: `message:${h.id}`,
        group: "Messages",
        typeWord: "Message",
        title: stripMarks(h.snippet) || h.id,
        epic,
        to: `/${h.ticket_id.startsWith("epic-") ? "epic" : "ticket"}/${encodeURIComponent(h.ticket_id)}#${h.id}`,
      };
    case "criterion":
      if (!h.ticket_id) return null;
      return {
        key: `criterion:${h.id}`,
        group: "Criteria",
        typeWord: "Criterion",
        title: stripMarks(h.snippet) || h.id,
        epic,
        to: `/ticket/${encodeURIComponent(h.ticket_id)}#${h.id}`,
      };
    default:
      return null;
  }
}

export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}): React.JSX.Element | null {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setDebounced("");
    setIndex(0);
    inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 120);
    return () => clearTimeout(t);
  }, [q]);

  const hits = useQuery({
    queryKey: ["find", debounced],
    queryFn: () => api<FindHit[]>(`/v1/find?q=${encodeURIComponent(debounced)}&k=20`),
    enabled: open && debounced.length >= 2,
    retry: false,
  });
  const epics = useQuery({ queryKey: ["epics", "summary", {}], queryFn: () => getEpicsSummary(), enabled: open, retry: false });
  const seats = useQuery({ queryKey: ["seats"], queryFn: () => api<SeatsView>("/v1/seats"), enabled: open, retry: false });

  const rows = useMemo<PaletteRow[]>(() => {
    const titles = new Map<string, string>((epics.data ?? []).map((e: EpicSummaryRow) => [e.id, e.title]));
    const epicTitle = (id: string | undefined) => (id ? (titles.get(id) ?? null) : null);
    const out: PaletteRow[] = [];
    for (const h of hits.data ?? []) {
      const r = rowFor(h, epicTitle);
      if (r) out.push(r);
    }
    const needle = debounced.toLowerCase();
    if (needle.length >= 2) {
      for (const s of seats.data?.seats ?? []) {
        if (
          s.handle.toLowerCase().includes(needle) ||
          s.id.toLowerCase().includes(needle) ||
          (s.ticket_title ?? "").toLowerCase().includes(needle)
        ) {
          out.push({
            key: `seat:${s.id}`,
            group: "Seats",
            typeWord: "Seat",
            title: s.handle,
            epic: s.ticket_title ?? s.ticket_id,
            to: `/seats#${s.id}`,
          });
        }
      }
      // An epic whose title contains the words, even when FTS ranked it out.
      for (const e of epics.data ?? []) {
        if (e.title.toLowerCase().includes(needle) && !out.some((r) => r.key === `ticket:${e.id}`)) {
          out.push({ key: `ticket:${e.id}`, group: "Epics", typeWord: "Epic", title: e.title, epic: null, to: `/epic/${encodeURIComponent(e.id)}` });
        }
      }
    }
    // Groups appear in the order the board ranked their best hit (the top result stays first so
    // Enter opens what the search meant); seats and title-matched epics trail the ranked hits.
    const firstSeen = new Map<string, number>();
    out.forEach((r, i) => {
      if (!firstSeen.has(r.group)) firstSeen.set(r.group, i);
    });
    return out
      .map((r, i) => ({ r, i }))
      .sort((a, b) => firstSeen.get(a.r.group)! - firstSeen.get(b.r.group)! || a.i - b.i)
      .map(({ r }) => r);
  }, [hits.data, seats.data, epics.data, debounced]);

  useEffect(() => setIndex(0), [rows.length, debounced]);

  function go(r: PaletteRow) {
    onClose();
    navigate(r.to);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setIndex((i) => (rows.length ? (i + 1) % rows.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setIndex((i) => (rows.length ? (i - 1 + rows.length) % rows.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const r = rows[index];
      if (r) go(r);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === "Tab") {
      // Focus trap: the dialog holds the input and the result buttons only.
      const nodes = dialogRef.current?.querySelectorAll<HTMLElement>("input, button, [href]") ?? [];
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  if (!open) return null;
  const groups = GROUP_ORDER.filter((g) => rows.some((r) => r.group === g));
  const activeId = rows[index] ? `find-opt-${rows[index].key}` : undefined;

  return (
    <>
      <div className={styles.scrim} onClick={onClose} data-testid="find-scrim" aria-hidden="true" />
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-label="Find" ref={dialogRef} onKeyDown={onKeyDown} data-testid="find-dialog">
        <label className={styles.inputWrap}>
          <span className={styles.srOnly}>Find tickets, epics, documents, messages and seats</span>
          <input
            ref={inputRef}
            className={styles.input}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Find a ticket, epic, document, message or seat…"
            role="combobox"
            aria-expanded={rows.length > 0}
            aria-controls="find-results"
            aria-activedescendant={activeId}
            aria-autocomplete="list"
            autoComplete="off"
            data-testid="find-input"
          />
        </label>
        <div id="find-results" role="listbox" aria-label="Results" className={styles.results}>
          {debounced.length < 2 ? (
            <p className={styles.hint}>Type at least two characters. Enter opens the highlighted result; Esc closes.</p>
          ) : hits.isPending && rows.length === 0 ? (
            <p className={styles.hint}>Searching…</p>
          ) : rows.length === 0 ? (
            <p className={styles.hint} data-testid="find-empty">
              Nothing on the board matches “{debounced}”.
            </p>
          ) : (
            groups.map((g) => (
              <div key={g} className={styles.group} role="group" aria-label={g}>
                <div className={styles.groupLabel} aria-hidden="true">
                  {g}
                </div>
                {rows
                  .map((r, i) => [r, i] as const)
                  .filter(([r]) => r.group === g)
                  .map(([r, i]) => (
                    <button
                      key={r.key}
                      id={`find-opt-${r.key}`}
                      type="button"
                      role="option"
                      aria-selected={i === index}
                      className={`${styles.row} ${i === index ? styles.active : ""}`}
                      onMouseEnter={() => setIndex(i)}
                      onClick={() => go(r)}
                      data-testid="find-row"
                      data-group={r.group}
                    >
                      <span className={styles.typeWord}>{r.typeWord}</span>
                      <span className={styles.title}>{r.title}</span>
                      {r.epic ? <span className={styles.epic}>{r.epic}</span> : null}
                    </button>
                  ))}
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
}
