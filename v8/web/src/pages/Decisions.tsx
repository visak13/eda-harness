import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import type {
  ConversationRow,
  EpicSummaryRow,
  GateRow,
  PersonRow,
  QuestionRow,
  ResolvedRow,
  SignoffRow,
  ReplyRow,
  SeatRow,
} from "../api/types";
import {
  getConversations,
  getReplies,
  getDecisions,
  getEpicsSummary,
  getPeople,
  getResolved,
} from "../api/endpoints";
import { getSeats, getPoolCapabilities } from "../api/seats";
import type { PoolCapabilities } from "../api/types";
import { Composer } from "../components/Composer";
import { GateForm, useRetainedGates } from "../components/GateForm";
import { AgentLine } from "../components/AgentLine";
import { RulingDrawer } from "../components/RulingDrawer";
import { presenceOf } from "./presence";
import { Avatar } from "../components/Avatar";
import { identity } from "../auth/identity";
import { useViewerAliases } from "../auth/useViewer";
import { copyProps } from "../copy/pages";
import { MessageText } from "../components/ArtifactLink";
import styles from "./Decisions.module.css";
import { Icon } from "../components/Icon";
import { recallEpic, rememberEpic } from "../components/currentEpic";
import ui from "../components/ui.module.css";

// Decisions home (design §4.2 / §16.1 / §18.2, folded S5). The owner's one place to see what needs
// them: ONE featured sign-off, calm queues (Sign-offs / Questions / Gates / Resolved), their
// conversations, and — on the right — who is alive, the people, and each epic's pulse. Live feed
// events refresh the queues live, drafts included (S19: a held refresh froze the page); a half-typed
// reply survives because the composer keeps its own state and persists it per ticket/reply.

type Tab = "signoffs" | "questions" | "gates" | "resolved";

export function DecisionsPage(): React.JSX.Element {
  const [tab, setTab] = useState<Tab>("signoffs");
  const [ruling, setRuling] = useState<{ signoff: SignoffRow; k: number; n: number } | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  const decisions = useQuery({ queryKey: ["me", "decisions"], queryFn: getDecisions, retry: false });
  const resolved = useQuery({ queryKey: ["me", "resolved"], queryFn: () => getResolved(30), retry: false });
  const people = useQuery({ queryKey: ["me", "people"], queryFn: getPeople, retry: false });
  const conversations = useQuery({ queryKey: ["me", "conversations"], queryFn: getConversations, retry: false });
  const replies = useQuery({ queryKey: ["me", "replies"], queryFn: () => getReplies(30), retry: false });
  const epics = useQuery({ queryKey: ["epics", "summary"], queryFn: () => getEpicsSummary(), retry: false });

  // S-UI (owner m-ec5a9b86c5 "the decisions page is a mess with questions from all epics"): one epic
  // at a time. ?epic=<id> (the rail's Needs you link carries the epic in view), else the last epic seen
  // this session, else all; "All epics" is a choice in the filter, not the default.
  const [params, setParams] = useSearchParams();
  const epicParam = params.get("epic");
  const epicFilter = epicParam ?? recallEpic() ?? ALL;
  const inEpic = (epicId: string | null | undefined) => epicFilter === ALL || epicId === epicFilter;
  function chooseEpic(next: string) {
    if (next !== ALL) rememberEpic(next);
    setParams((old) => { const q = new URLSearchParams(old); q.set("epic", next); return q; }, { replace: true });
  }

  const d = decisions.data;
  // §18.2: "Waiting on you shows only items that need a human act". A question whose asker seat is
  // closed/dead/reaped cannot receive the answer, so it is not one — it stays visible under the
  // conversations' "Closed seats" row instead (acceptance finding: the tab counted it, 2026-09-08).
  const liveQuestions = useMemo(
    () => (d?.questions ?? []).filter((q) => !["dead", "reaped", "closed", "done"].includes(q.asker?.seat_state ?? ""))
      .filter((q) => epicFilter === ALL || q.epic_id === undefined || q.epic_id === epicFilter),
    [d?.questions, epicFilter],
  );
  const signoffs = (d?.signoffs ?? []).filter((s) => inEpic(s.ticket.epic_id));
  const gates = (d?.gates ?? []).filter((g) => inEpic(g.epic));
  const resolvedRows = (resolved.data ?? []).filter((r) => epicFilter === ALL || r.epic_id === undefined || r.epic_id === epicFilter);
  const replyRows = (replies.data ?? []).filter((r) => epicFilter === ALL || r.epic_id === undefined || r.epic_id === epicFilter);
  const convoRows = (conversations.data ?? []).filter((c) => inEpic(c.epic_id ?? c.ticket_id));
  const counts = { signoffs: signoffs.length, questions: liveQuestions.length, gates: gates.length };
  const epicOptions = useMemo(() => {
    const rows = (epics.data ?? []).filter((e) => !["done", "dropped", "partial"].includes(e.status) || e.id === epicFilter);
    return rows.map((e) => ({ id: e.id, title: e.title }));
  }, [epics.data, epicFilter]);

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
    { key: "resolved", label: "Resolved", count: resolved.data ? resolvedRows.length : undefined },
  ];

  return (
    <div className={styles.grid} data-testid="decisions">
      <div className={styles.main}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>Decisions</h1>
          <label className={styles.epicFilter}>
            <span className={styles.epicFilterLabel}>Epic</span>
            <select className={ui.select} value={epicFilter} onChange={(e) => chooseEpic(e.target.value)} data-testid="decisions-epic-filter">
              <option value={ALL}>All epics</option>
              {epicFilter !== ALL && !epicOptions.some((e) => e.id === epicFilter)
                ? <option value={epicFilter}>{titleFor(epicFilter)}</option> : null}
              {epicOptions.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}
            </select>
          </label>
        </div>

        <NeedsYou questions={liveQuestions} gates={gates} titleFor={titleFor}
          scope={epicFilter === ALL ? "any epic" : titleFor(epicFilter)} />

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
          <SignoffsTab signoffs={signoffs} onOpen={openRuling} />
        ) : tab === "questions" ? (
          <QuestionsTab questions={liveQuestions} titleFor={titleFor} />
        ) : tab === "gates" ? (
          <GatesTab gates={gates} />
        ) : (
          <ResolvedTab rows={resolvedRows} titleFor={titleFor} />
        )}

        <Replies rows={replyRows} />
        <Conversations rows={convoRows} people={people.data ?? []} />
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

/** The board's excerpt is the first 300 chars of raw markdown; the card shows it as prose. */
function plainExcerpt(md: string): string {
  return md
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[*_`>]+/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
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
          {/* Plate folio-home: tag · epic (one line) · ticket id; the QUESTION the owner answers as the
              Georgia title; a two-line plain excerpt; the document line; seat + button in the foot.
              The epic's full words and the raw markdown excerpt used to fill the card (spacing pass,
              human report 2026-09-10). */}
          <div className={styles.featuredCrumb}>
            <span className={styles.featuredTag}>{featured.ticket.quick ? "Quick task" : "Owner sign-off"}</span>
            <span className={styles.featuredEpic} title={featured.ticket.epic_title}>
              {featured.ticket.epic_title}
            </span>
            <span className={styles.featuredId}>{featured.ticket.id}</span>
          </div>
          <h2 className={styles.featuredTitle}>{featured.criterion.text}</h2>
          {featured.excerpt ? <p className={styles.featuredExcerpt}>{plainExcerpt(featured.excerpt)}</p> : null}
          <div className={styles.docRef}>
            <span className={styles.docRefTitle}>{featured.doc?.title ?? featured.ticket.title}</span>
            {featured.doc ? (
              <span>
                {" "}
                · {featured.doc.doc_type} v{featured.doc.version}
              </span>
            ) : null}
          </div>
          <div className={styles.featuredFoot}>
            <span className={styles.featuredSeat}>
              <span className={styles.featuredSeatName}>{featured.ticket.assignee ?? "the assignee"}</span>
              <span className={styles.featuredSeatNote}>Evidence attached · your verdict is pending</span>
            </span>
            <button
              className={styles.reviewBtn}
              type="button"
              data-testid="review-evidence"
              {...copyProps("decisions", "signoffs")}
              onClick={(e) => onOpen(featured, 1, n, e.currentTarget)}
            >
              Review evidence
            </button>
          </div>
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
                  <span>{s.ticket.quick ? s.criterion.text : (s.doc?.title ?? s.ticket.title)}</span>
                  <span className={styles.moreTicket}>{s.ticket.quick ? `Quick task · ${s.ticket.title}` : s.ticket.title}</span>
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
  return (
    <div className={styles.question} data-testid="question">
      {/* Framed agent text (§15, c-cccc3183db): name-first, role word, id in mono, and a reader-
          relative tag — a question in the owner's own inbox is "Waiting on you". */}
      <div className={styles.qMeta}>
        <AgentLine by={String(q.created_by)} kind={String(q.kind)} to={q.to} viewer={identity()} />
        {q.asker?.note ? <span className={styles.qNote}>{q.asker.note}</span> : null}
      </div>
      {/* "Why you see it" (design §16.2, promise #21): the board's routing reason, verbatim. */}
      {q.why ? (
        <p className={styles.qWhy} data-testid="why">
          Why you see it: {q.why}
        </p>
      ) : null}
      <MessageText className={styles.qText} text={q.text} />
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
function GatesTab({ gates: open }: { gates: GateRow[] }): React.JSX.Element {
  const gates = useRetainedGates(open);
  if (gates.length === 0) {
    return <p className={styles.calm}>No open gates. Nothing is waiting on your ruling.</p>;
  }
  return (
    <div className={styles.gates}>
      {gates.map(({ gate: g, closed, onDismiss }) => (
        <GateForm key={`${g.ticket_id}:${g.gate}`} gate={g} closed={closed} onDismiss={onDismiss} />
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

// ------------------------------------------------------------------ Replies to you
// A person who wrote from the UI must find the reply where they look (human report m-3d3a36455f,
// 2026-09-10): every answer addressed to the viewer, or replying to what they wrote, with their own
// words quoted above it and a way into the thread.
function Replies({ rows }: { rows: ReplyRow[] }): React.JSX.Element | null {
  if (rows.length === 0) return null;
  return (
    <section className={styles.convos} aria-label="Replies to you" data-testid="replies">
      <div className={styles.convosHead}>
        <h2 className={styles.sectionTitle}>Replies to you ({rows.length})</h2>
      </div>
      <ul className={styles.convoList}>
        {rows.map((r) => (
          <ReplyRowView key={r.id} r={r} />
        ))}
      </ul>
    </section>
  );
}

function ReplyRowView({ r }: { r: ReplyRow }): React.JSX.Element {
  const [replying, setReplying] = useState(false); // round 2 #16: answer in place, threaded
  return (
    <li className={styles.replyRow} data-testid="reply-row">
      <AgentLine by={r.created_by} kind={r.kind} to={identity()} viewer={identity()} at={r.at} />
      {r.in_reply_to ? (
        <blockquote className={styles.replyQuote}>
          <span className={styles.replyQuoteWho}>you wrote:</span> {r.in_reply_to.text}
        </blockquote>
      ) : null}
      <MessageText className={styles.replyText} text={r.text} />
      <Link className={styles.replyTicket} to={`/${r.ticket_id.startsWith("epic-") ? "epic" : "ticket"}/${encodeURIComponent(r.ticket_id)}#${r.id}`}>
        {r.ticket_title}
      </Link>
      {replying ? (
        <Composer
          ticketId={r.ticket_id}
          kinds={["answer", "note"]}
          to={r.created_by}
          replyTo={r.id}
          replyToBy={r.created_by}
          onCancelReply={() => setReplying(false)}
          placeholder={`Reply to @${r.created_by}`}
          onSent={() => setReplying(false)}
        />
      ) : (
        <button type="button" className={styles.replyBtn} onClick={() => setReplying(true)} data-testid="reply-to-reply">
          Reply
        </button>
      )}
    </li>
  );
}

// ------------------------------------------------------------------ Conversations
function Conversations({ rows, people }: { rows: ConversationRow[]; people: PersonRow[] }): React.JSX.Element {
  const [byCounterpart, setByCounterpart] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [composing, setComposing] = useState(false);
  // "New conversation" posts on a ticket the viewer picks (adversary finding #6, 2026-09-10) — it
  // used to post silently on whichever row happened to be first.
  const [newTicket, setNewTicket] = useState<string>("");
  const composeTicket = newTicket || rows[0]?.ticket_id || "";

  // Round 2 #10: the viewer is excluded from /v1/me/people by design, so a conversation the viewer
  // spoke last on was filed under "Closed seats". The viewer's own aliases count as live.
  const viewerIds = useViewerAliases();
  const liveIds = useMemo(() => new Set([...people.map((p) => p.id), ...viewerIds]), [people, viewerIds]);
  // A conversation's counterpart is the last message's sender. It is "live" if that id is in the
  // reachable people list (a live seat or a human) or is the viewer; otherwise its seat has closed.
  const isLive = (c: ConversationRow) => (c.last ? liveIds.has(c.last.by) : true);
  const live = rows.filter(isLive);
  const closed = rows.filter((c) => !isLive(c));

  const label = (c: ConversationRow) => (c.unread ? "you were paged" : "on your ticket");
  // "By counterpart" groups the live rows by who last spoke (adversary finding #7: the toggle
  // changed nothing before); "By ticket" is one flat list in the board's order.
  const groups: [string, ConversationRow[]][] = byCounterpart
    ? Array.from(
        live.reduce((m, c) => {
          const k = c.last?.by ?? "thread";
          m.set(k, [...(m.get(k) ?? []), c]);
          return m;
        }, new Map<string, ConversationRow[]>()),
      )
    : [["all", live]];

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
          <button type="button" className={styles.linkBtn} onClick={() => setComposing((v) => !v)} data-testid="new-conversation" {...copyProps("decisions", "new-conversation")}>
            New conversation
          </button>
        </div>
      </div>

      {composing ? (
        <div className={styles.newConvo}>
          <label className={styles.newConvoLabel}>
            On ticket
            <select
              className={styles.newConvoSelect}
              value={composeTicket}
              data-testid="new-conversation-ticket"
              onChange={(e) => setNewTicket(e.target.value)}
            >
              {rows.map((r) => (
                <option key={r.ticket_id} value={r.ticket_id}>
                  {r.title} · {r.ticket_id}
                </option>
              ))}
            </select>
          </label>
          {composeTicket ? <Composer ticketId={composeTicket} kinds={["note", "question"]} showTo onSent={() => setComposing(false)} /> : <p>Select a conversation ticket before composing.</p>}
        </div>
      ) : null}

      {live.length === 0 && closed.length === 0 ? (
        <p className={styles.calm}>No conversations yet.</p>
      ) : (
        groups.map(([who, items]) => (
          <div key={who} data-testid="convo-group">
            {byCounterpart ? <div className={styles.convoGroup}>{who}</div> : null}
            <ul className={styles.convoList}>
              {items.map((c) => (
                <li key={c.ticket_id} className={styles.convoRow}>
                  {c.unread ? <span className={styles.unreadDot} role="img" aria-label="unread" /> : null}
                  {/* The row IS the way into the thread (adversary finding #7): it links to the ticket. */}
                  <Link className={styles.convoTitle} to={`/ticket/${encodeURIComponent(c.ticket_id)}`} data-testid="convo-link">
                    {c.title}
                  </Link>
                  <span className={styles.convoWhy}>{label(c)}</span>
                  {c.last ? (
                    <span className={styles.convoLast}>
                      {byCounterpart ? "" : `${c.last.by}: `}
                      {c.last.text}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))
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
  // Alive seats only — working/idle/parked. Closed/dead seats (and remote seats of unknown
  // availability) live on the Seats page, not in "now" (human report m-3d3a36455f, 2026-09-10).
  const seats = (seatsQ.data?.seats ?? []).filter((s) => s.state === "alive" || s.state === "parked" || s.state === "stalled");
  return (
    <section className={styles.railCard} data-testid="seats-now">
      <h2 className={styles.sectionTitle}>Seats, now</h2>
      <p className={styles.railHint}>Shell alive ≠ work progressing</p>
      {seatsQ.isError ? (
        <p className={styles.calm}>Seats are unavailable right now.</p>
      ) : seats.length === 0 ? (
        <p className={styles.calm}>No seat is working right now.</p>
      ) : (
        <ul className={styles.seatsNowList}>
          {seats.map((s) => (
            <SeatNowCard key={s.id} seat={s} caps={caps} />
          ))}
        </ul>
      )}
    </section>
  );
}

// One seat in the 336px rail (plate folio-home "Seats, now"): name, role, presence word, the ticket
// on one line, the latest status clamped to three lines. Same /v1/seats source and the same 60s
// presence rule as the Seats page (presenceOf), so it cannot drift — but a CARD, not the page's
// five-column table, which in this rail became a column of single words (human report "spacing
// broken", 2026-09-10).
function SeatNowCard({ seat, caps }: { seat: SeatRow; caps: PoolCapabilities | undefined }): React.JSX.Element {
  const presence = presenceOf(seat, caps, Date.now());
  return (
    <li className={styles.seatNow} data-testid="seat-row" data-seat={seat.id} data-presence={presence.kind}>
      <div className={styles.seatNowHead}>
        <Avatar id={seat.id} size={22} />
        <span className={styles.seatNowName}>{seat.handle}</span>
        <span className={styles.seatNowRole}>{seat.role}</span>
        <span className={styles.seatNowState}>
          <span className={`${styles.seatNowDot} ${styles[presence.dot] ?? ""}`} aria-hidden="true" />
          <span data-testid="seat-state">{presence.word}</span>
        </span>
      </div>
      {seat.ticket_id ? (
        <Link className={styles.seatNowTicket} to={`/ticket/${encodeURIComponent(seat.ticket_id)}`} title={seat.ticket_title ?? seat.ticket_id}>
          {seat.ticket_title ? (
            <>
              {seat.ticket_title} <span className={styles.seatNowTicketId}>{seat.ticket_id}</span>
            </>
          ) : (
            seat.ticket_id
          )}
        </Link>
      ) : null}
      {seat.latest_status ? (
        <p className={styles.seatNowStatus} data-testid="latest-status">{seat.latest_status.text}</p>
      ) : (
        <p className={styles.seatNowStatus} data-testid="no-status">Last work update unavailable</p>
      )}
      <Link className={styles.seatNowOpen} to="/seats">
        Open seat <Icon name="forward" />
      </Link>
    </li>
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
            <Avatar id={p.id} size={24} className={styles.personAvatar} />
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

// ------------------------------------------------------------------ Needs you (S-UI)
const ALL = "all";

function threadLink(ticketId: string, epicId: string | null | undefined, messageId?: string): string {
  const base = ticketId === epicId ? `/epic/${encodeURIComponent(ticketId)}` : `/ticket/${encodeURIComponent(ticketId)}`;
  return messageId ? `${base}#${encodeURIComponent(messageId)}` : base;
}

/** First on the page: the open asks and gates addressed to the viewer, for the chosen epic — each
 *  one line with a jump to where it lives. The tabs below keep the full reply / ruling forms. */
function NeedsYou({ questions, gates, titleFor, scope }: {
  questions: QuestionRow[]; gates: GateRow[]; titleFor: (id: string) => string; scope: string;
}): React.JSX.Element {
  const n = questions.length + gates.length;
  return (
    <section className={styles.needsYou} aria-label="Needs you" data-testid="needs-you">
      <h2 className={styles.needsYouTitle}>Needs you <span className={styles.tabCount}>{n}</span></h2>
      {n === 0 ? <p className={styles.calm} data-testid="needs-you-empty">Nothing on {scope} is waiting on you.</p> : (
        <ul className={styles.needsYouList}>
          {questions.map((q) => (
            <li key={q.id} className={styles.needsYouRow} data-testid="needs-you-ask" data-ask={q.id}>
              <span className={styles.needsYouKind}>{String(q.kind)}</span>
              <span className={styles.needsYouText}>
                <span className={styles.needsYouWhere}>{titleFor(q.ticket_id)} · from {String(q.created_by)}</span>
                <span className={styles.needsYouExcerpt}>{q.text.replace(/\s+/g, " ").slice(0, 160)}</span>
              </span>
              <Link className={styles.linkBtn} to={threadLink(q.ticket_id, q.epic_id, q.id)}>Open</Link>
            </li>
          ))}
          {gates.map((g) => (
            <li key={`${g.ticket_id}:${g.gate}`} className={styles.needsYouRow} data-testid="needs-you-gate">
              <span className={styles.needsYouKind}>gate</span>
              <span className={styles.needsYouText}>
                <span className={styles.needsYouWhere}>{titleFor(g.ticket_id)} · opened by {g.by}</span>
                <span className={styles.needsYouExcerpt}>{g.gate.replaceAll("_", " ")}{g.note ? ` — ${g.note}` : ""}</span>
              </span>
              <Link className={styles.linkBtn} to={threadLink(g.ticket_id, g.epic)}>Open</Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
