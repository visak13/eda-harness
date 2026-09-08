import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type {
  ConversationRow,
  EpicSummaryRow,
  GateRow,
  PersonRow,
  QuestionRow,
  ResolvedRow,
  SignoffRow,
} from "../api/types";
import {
  getConversations,
  getDecisions,
  getEpicsSummary,
  getPeople,
  getResolved,
} from "../api/decisions";
import { getSeats, getPoolCapabilities } from "../api/seats";
import type { PoolCapabilities } from "../api/types";
import { Composer } from "../components/Composer";
import { GateForm } from "../components/GateForm";
import { RulingDrawer } from "../components/RulingDrawer";
import { SeatTableRow } from "./Seats";
import { useDraftGuard } from "../live/useDraftGuard";
import styles from "./Decisions.module.css";

// Decisions home (design §4.2 / §16.1 / §18.2, folded S5). The owner's one place to see what needs
// them: ONE featured sign-off, calm queues (Sign-offs / Questions / Gates / Resolved), their
// conversations, and — on the right — who is alive, the people, and each epic's pulse. Live feed
// events refresh the queues, but a dirty composer HOLDS the refresh ("N new — refresh") so a
// half-typed reply is never wiped and the row being answered never jumps (useDraftGuard).

type Tab = "signoffs" | "questions" | "gates" | "resolved";

export function DecisionsPage(): React.JSX.Element {
  const [tab, setTab] = useState<Tab>("signoffs");
  const [ruling, setRuling] = useState<{ signoff: SignoffRow; k: number; n: number } | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const { pending, flush } = useDraftGuard();

  const decisions = useQuery({ queryKey: ["me", "decisions"], queryFn: getDecisions, retry: false });
  const resolved = useQuery({ queryKey: ["me", "resolved"], queryFn: () => getResolved(30), retry: false });
  const people = useQuery({ queryKey: ["me", "people"], queryFn: getPeople, retry: false });
  const conversations = useQuery({ queryKey: ["me", "conversations"], queryFn: getConversations, retry: false });
  const epics = useQuery({ queryKey: ["epics", "summary"], queryFn: getEpicsSummary, retry: false });

  const d = decisions.data;
  const counts = d?.counts ?? { signoffs: 0, questions: 0, gates: 0 };

  // A ticket-id → title map so the questions queue can name a ticket in the owner's words
  // (the inbox rows carry no title). Conversations and epics both supply id → title.
  const titleFor = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of conversations.data ?? []) m.set(c.ticket_id, c.title);
    for (const e of epics.data ?? []) m.set(e.id, e.title);
    return (id: string) => m.get(id) ?? id;
  }, [conversations.data, epics.data]);

  function openRuling(signoff: SignoffRow, k: number, n: number, opener: HTMLElement | null) {
    openerRef.current = opener;
    setRuling({ signoff, k, n });
  }

  const TABS: { key: Tab; label: string; count?: number }[] = [
    { key: "signoffs", label: "Sign-offs", count: counts.signoffs },
    { key: "questions", label: "Questions", count: counts.questions },
    { key: "gates", label: "Gates", count: counts.gates },
    { key: "resolved", label: "Resolved", count: resolved.data?.length },
  ];

  return (
    <div className={styles.grid} data-testid="decisions">
      <div className={styles.main}>
        <h1 className={styles.title}>Decisions</h1>

        {pending > 0 ? (
          <button className={styles.refresh} type="button" onClick={flush} data-testid="page-refresh" aria-live="polite">
            {pending} new — refresh
          </button>
        ) : null}

        <div className={styles.tabs} role="tablist" aria-label="Decisions queues">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={`${styles.tab} ${tab === t.key ? styles.tabActive : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {typeof t.count === "number" ? <span className={styles.tabCount}>{t.count}</span> : null}
            </button>
          ))}
        </div>

        {decisions.isError ? (
          <p className={styles.calm}>The board could not be reached. It will reappear when the connection returns.</p>
        ) : tab === "signoffs" ? (
          <SignoffsTab signoffs={d?.signoffs ?? []} onOpen={openRuling} />
        ) : tab === "questions" ? (
          <QuestionsTab questions={d?.questions ?? []} titleFor={titleFor} />
        ) : tab === "gates" ? (
          <GatesTab gates={d?.gates ?? []} />
        ) : (
          <ResolvedTab rows={resolved.data ?? []} titleFor={titleFor} />
        )}

        <Conversations rows={conversations.data ?? []} people={people.data ?? []} />
      </div>

      <aside className={styles.rail} aria-label="Status">
        <SeatsNow />
        <PeopleRow people={people.data ?? []} />
        <EpicPulse epics={epics.data ?? []} />
      </aside>

      <RulingDrawer
        signoff={ruling?.signoff ?? null}
        kOfN={ruling ? { k: ruling.k, n: ruling.n } : undefined}
        onClose={() => setRuling(null)}
        onRuled={() => setRuling(null)}
        returnFocusTo={openerRef.current}
      />
    </div>
  );
}

// ------------------------------------------------------------------ Sign-offs
function SignoffsTab({
  signoffs,
  onOpen,
}: {
  signoffs: SignoffRow[];
  onOpen: (s: SignoffRow, k: number, n: number, opener: HTMLElement | null) => void;
}): React.JSX.Element {
  if (signoffs.length === 0) {
    return <p className={styles.calm}>Nothing is waiting for your sign-off. A clear desk.</p>;
  }
  const [featured, ...rest] = signoffs;
  const n = signoffs.length;
  return (
    <div>
      <article className={styles.featured} data-testid="featured-signoff">
        <div className={styles.featuredTop} aria-hidden="true" />
        <div className={styles.featuredBody}>
          <div className={styles.featuredCrumb}>
            {featured.ticket.epic_title} · {featured.ticket.title}
          </div>
          <h2 className={styles.featuredTitle}>{featured.doc?.title ?? featured.ticket.title}</h2>
          <p className={styles.featuredExcerpt}>{featured.excerpt}</p>
          {featured.doc ? (
            <div className={styles.docRef}>
              {featured.doc.doc_type} · v{featured.doc.version}
            </div>
          ) : null}
          <button
            className={styles.reviewBtn}
            type="button"
            data-testid="review-evidence"
            onClick={(e) => onOpen(featured, 1, n, e.currentTarget)}
          >
            Review evidence
          </button>
        </div>
      </article>

      {rest.length > 0 ? (
        <div className={styles.moreDocs} data-testid="more-docs">
          <div className={styles.moreCount}>
            {rest.length} more {rest.length === 1 ? "document" : "documents"} awaiting your sign-off
          </div>
          <ul className={styles.moreList}>
            {rest.map((s, i) => (
              <li key={s.criterion.id}>
                <button
                  type="button"
                  className={styles.moreRow}
                  onClick={(e) => onOpen(s, i + 2, n, e.currentTarget)}
                >
                  <span>{s.doc?.title ?? s.ticket.title}</span>
                  <span className={styles.moreTicket}>{s.ticket.title}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ Questions
function QuestionsTab({
  questions,
  titleFor,
}: {
  questions: QuestionRow[];
  titleFor: (id: string) => string;
}): React.JSX.Element {
  if (questions.length === 0) {
    return <p className={styles.calm}>No questions in your inbox. Nobody is waiting on an answer.</p>;
  }
  // Group by ticket, preserving the board's oldest-first order.
  const groups = new Map<string, QuestionRow[]>();
  for (const q of questions) {
    const arr = groups.get(q.ticket_id) ?? [];
    arr.push(q);
    groups.set(q.ticket_id, arr);
  }
  return (
    <div className={styles.questions}>
      {[...groups.entries()].map(([ticketId, qs]) => (
        <section key={ticketId} className={styles.qGroup} aria-label={titleFor(ticketId)}>
          <h3 className={styles.qGroupTitle}>{titleFor(ticketId)}</h3>
          {qs.map((q) => (
            <QuestionRowView key={q.id} q={q} />
          ))}
        </section>
      ))}
    </div>
  );
}

function QuestionRowView({ q }: { q: QuestionRow }): React.JSX.Element {
  const [replying, setReplying] = useState(false);
  const askerRole = q.asker?.role ?? String(q.from_role ?? "");
  const askerName = String(q.created_by);
  return (
    <div className={styles.question} data-testid="question">
      <div className={styles.qMeta}>
        <span className={styles.qAsker}>
          {askerName} · {askerRole}
        </span>
        {q.asker?.note ? <span className={styles.qNote}>{q.asker.note}</span> : null}
      </div>
      <p className={styles.qText}>{q.text}</p>
      {replying ? (
        <Composer
          ticketId={q.ticket_id}
          kinds={["answer"]}
          to={q.created_by}
          replyTo={q.id}
          placeholder="Type your answer. Ctrl+Enter sends."
          onSent={() => setReplying(false)}
        />
      ) : (
        <button type="button" className={styles.replyBtn} onClick={() => setReplying(true)} data-testid="reply">
          Reply
        </button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Gates
function GatesTab({ gates }: { gates: GateRow[] }): React.JSX.Element {
  if (gates.length === 0) {
    return <p className={styles.calm}>No open gates. Nothing is waiting on your ruling.</p>;
  }
  return (
    <div className={styles.gates}>
      {gates.map((g) => (
        <GateForm key={`${g.ticket_id}:${g.gate}`} gate={g} />
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ Resolved
function ResolvedTab({
  rows,
  titleFor,
}: {
  rows: ResolvedRow[];
  titleFor: (id: string) => string;
}): React.JSX.Element {
  if (rows.length === 0) {
    return <p className={styles.calm}>Nothing resolved yet. Your decisions will collect here.</p>;
  }
  return (
    <ul className={styles.resolved} data-testid="resolved">
      {rows.map((r, i) => (
        <li key={`${r.ticket_id}:${i}`} className={styles.resolvedRow}>
          <span className={styles.resolvedWhat}>
            {r.kind === "verdict" ? `${r.verdict} · ${r.criterion}` : `${r.gate} gate · ${r.answer}`}
          </span>
          <span className={styles.resolvedTicket}>{titleFor(r.ticket_id)}</span>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------ Conversations
function Conversations({ rows, people }: { rows: ConversationRow[]; people: PersonRow[] }): React.JSX.Element {
  const [byCounterpart, setByCounterpart] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [composing, setComposing] = useState(false);

  const liveIds = useMemo(() => new Set(people.map((p) => p.id)), [people]);
  // A conversation's counterpart is the last message's sender. It is "live" if that id is in the
  // reachable people list (a live seat or a human); otherwise its seat has closed.
  const isLive = (c: ConversationRow) => (c.last ? liveIds.has(c.last.by) : true);
  const live = rows.filter(isLive);
  const closed = rows.filter((c) => !isLive(c));

  const label = (c: ConversationRow) => (c.unread ? "you were paged" : "on your ticket");

  return (
    <section className={styles.convos} aria-label="Your conversations" data-testid="conversations">
      <div className={styles.convosHead}>
        <h2 className={styles.sectionTitle}>Your conversations</h2>
        <div className={styles.convosControls}>
          <button
            type="button"
            className={styles.linkBtn}
            aria-pressed={byCounterpart}
            onClick={() => setByCounterpart((v) => !v)}
          >
            {byCounterpart ? "By ticket" : "By counterpart"}
          </button>
          <button type="button" className={styles.linkBtn} onClick={() => setComposing((v) => !v)} data-testid="new-conversation">
            New conversation
          </button>
        </div>
      </div>

      {composing ? (
        <Composer ticketId={rows[0]?.ticket_id ?? ""} kinds={["note", "question"]} showTo onSent={() => setComposing(false)} />
      ) : null}

      {live.length === 0 && closed.length === 0 ? (
        <p className={styles.calm}>No conversations yet.</p>
      ) : (
        <ul className={styles.convoList}>
          {live.map((c) => (
            <li key={c.ticket_id} className={styles.convoRow}>
              {c.unread ? <span className={styles.unreadDot} aria-label="unread" /> : null}
              <span className={styles.convoTitle}>{c.title}</span>
              <span className={styles.convoWhy}>{label(c)}</span>
              {c.last ? <span className={styles.convoLast}>{c.last.text}</span> : null}
            </li>
          ))}
        </ul>
      )}

      {closed.length > 0 ? (
        <div className={styles.closedSeats}>
          <button type="button" className={styles.linkBtn} onClick={() => setShowClosed((v) => !v)} data-testid="closed-seats">
            Closed seats ({closed.length})
          </button>
          {showClosed ? (
            <ul className={styles.convoList}>
              {closed.map((c) => (
                <li key={c.ticket_id} className={`${styles.convoRow} ${styles.convoClosed}`}>
                  <span className={styles.convoTitle}>{c.title}</span>
                  {c.unread ? (
                    <span className={styles.convoFlag} data-testid="dead-seat-flag">
                      seat closed before answering; ask the owner shell to respawn
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------ right rail
// "Seats, now" (design §4.2): the SAME row the Seats page uses (SeatTableRow), driven by the SAME
// /v1/seats source and the shared 60s presence rule — so this strip is honest by construction (the
// true latest status, or "Last work update unavailable" only when a seat has reported none) and can
// never drift from the Seats page. A 280px rail, so the wide row scrolls inside its own box.
function SeatsNow(): React.JSX.Element {
  const seatsQ = useQuery({ queryKey: ["seats"], queryFn: getSeats, retry: false });
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false });
  const caps = capsQ.data as PoolCapabilities | undefined;
  const seats = seatsQ.data?.seats ?? [];
  return (
    <section className={styles.railCard} data-testid="seats-now">
      <h2 className={styles.sectionTitle}>Seats, now</h2>
      <p className={styles.railHint}>Shell alive ≠ work progressing</p>
      {seatsQ.isError ? (
        <p className={styles.calm}>Seats are unavailable right now.</p>
      ) : seats.length === 0 ? (
        <p className={styles.calm}>No agent seats yet.</p>
      ) : (
        <div className={styles.seatsNowScroll}>
          <table className={styles.seatsNowTable}>
            <tbody>
              {seats.map((s) => (
                <SeatTableRow key={s.id} seat={s} caps={caps} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PeopleRow({ people }: { people: PersonRow[] }): React.JSX.Element {
  const humans = people.filter((p) => p.type === "human");
  if (humans.length === 0) return <></>;
  return (
    <section className={styles.railCard} data-testid="people-row">
      <h2 className={styles.sectionTitle}>People</h2>
      <ul className={styles.peopleList}>
        {humans.map((p) => (
          <li key={p.id} className={styles.personChip}>
            <span className={styles.personAvatar} aria-hidden="true">
              {p.handle.slice(0, 1).toUpperCase()}
            </span>
            {p.handle}
          </li>
        ))}
      </ul>
    </section>
  );
}

function EpicPulse({ epics }: { epics: EpicSummaryRow[] }): React.JSX.Element {
  return (
    <section className={styles.railCard} data-testid="epic-pulse">
      <h2 className={styles.sectionTitle}>Epic pulse</h2>
      {epics.length === 0 ? (
        <p className={styles.calm}>No epics on the board.</p>
      ) : (
        <ul className={styles.pulseList}>
          {epics.map((e) => (
            <li key={e.id} className={styles.pulseRow}>
              <div className={styles.pulseTop}>
                <span className={styles.pulseStatus} data-status={e.status}>
                  {e.status.replace(/_/g, " ")}
                </span>
                <span className={styles.pulseTitle}>{e.title}</span>
              </div>
              <div className={styles.pulseReason}>{e.waiting_reason.reason}</div>
              <div className={styles.pulseCriteria}>
                {e.criteria.total === 0
                  ? "None defined"
                  : `${e.criteria.passed} of ${e.criteria.total} criteria passed`}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
