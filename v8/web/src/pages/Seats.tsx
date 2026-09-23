import { useState } from "react";
import { Link, useLocation } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { PoolCapabilities, SeatRow, SeatsView } from "../api/types";
import { getSeats, getPoolCapabilities, resumeSeat } from "../api/seats";
import { api } from "../api/client";
import { label as glossLabel } from "../copy/glossary";
import { usePageFrame } from "../components/PageFrame";
import { Composer } from "../components/Composer";
import { Avatar } from "../components/Avatar";
import { useScrollToHash } from "../components/useScrollToHash";
import { copyProps } from "../copy/pages";
import { identity } from "../auth/identity";
import { useViewerAliases } from "../auth/useViewer";
import { AgentLine } from "../components/AgentLine";
import { presenceOf } from "./presence";
import { MessageText } from "../components/ArtifactLink";
import { SpawnSeatForm } from "../components/SpawnSeatForm";
import styles from "./Seats.module.css";

const FRAMING = "See who is available, read their latest status, and message or resume a seat.";

// A short, human "last heard" time: "Just now" under a minute, else the local clock time.
function clock(iso: string | null, now: number): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  if (now - t < 60_000) return "Just now";
  return new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

type TabKey = "all" | "alive" | "parked" | "closed";
const TAB_MATCH: Record<TabKey, (s: SeatRow) => boolean> = {
  all: () => true,
  alive: (s) => s.state === "alive" || s.state === "stalled",
  parked: (s) => s.state === "parked",
  closed: (s) => s.state === "dead", // an unknown/remote seat (state == null) is NOT closed
};

export function SeatsPage(): React.JSX.Element {
  usePageFrame(FRAMING, [
    { category: "concept", value: "seat" },
    { category: "concept", value: "wake" },
    { category: "concept", value: "presence" },
    { category: "concept", value: "alive" },
    { category: "role", value: "engineer" },
    { category: "role", value: "reviewer" },
    { category: "role", value: "architect" },
    { category: "role", value: "qa" },
  ]);
  const seatsQ = useQuery({ queryKey: ["seats"], queryFn: getSeats, retry: false });
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false });
  const [tab, setTab] = useState<TabKey>("all");
  // Find a seat by name / ticket / role: with a hundred closed seats the one you want (the human
  // looked for owner.epic-…) is otherwise buried (human report m-a398600978, 2026-09-10).
  const [find, setFind] = useState("");
  // Round 2 #13: /seats#<seat-id> (a Find hit) must show and scroll to that row whatever the tab
  // or filter says; the hashed seat is always in `shown`, and the hook scrolls once rows exist.
  const { hash } = useLocation();
  const hashed = hash ? decodeURIComponent(hash.slice(1)) : "";

  useScrollToHash(seatsQ.data ? (seatsQ.data as SeatsView).seats.length : 0);

  if (seatsQ.isLoading) return <FrameOnly>Loading seats…</FrameOnly>;
  if (seatsQ.error || !seatsQ.data) return <FrameOnly>Seats are unavailable right now.</FrameOnly>;

  const { seats, people } = seatsQ.data as SeatsView;
  const caps = capsQ.data as PoolCapabilities | undefined;
  const counts: Record<TabKey, number> = {
    all: seats.length,
    alive: seats.filter(TAB_MATCH.alive).length,
    parked: seats.filter(TAB_MATCH.parked).length,
    closed: seats.filter(TAB_MATCH.closed).length,
  };
  const needle = find.trim().toLowerCase();
  const shown = seats.filter(
    (r) =>
      r.id === hashed ||
      (TAB_MATCH[tab](r) &&
        (!needle ||
          [r.handle, r.id, r.role, r.ticket_id ?? "", r.ticket_title ?? ""].some((v) => v.toLowerCase().includes(needle)))),
  );

  return (
    <>
      <header className={styles.head}>
        <h1 className={styles.title}>The people behind the work.</h1>
        <p className={styles.subtitle} data-testid="seats-framing">
          {FRAMING}
        </p>
      </header>

      {/* S-ROLES: spawn any role on any ticket, shown only when the pool reports it can spawn */}
      {caps?.spawn ? <SpawnSeatForm /> : null}

      <div className={styles.tabsRow}>
        <div className={styles.tabs} role="tablist" aria-label="Seat states">
          {(["all", "alive", "parked", "closed"] as TabKey[]).map((k) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={tab === k}
              className={`${styles.tab} ${tab === k ? styles.tabActive : ""}`}
              onClick={() => setTab(k)}
            >
              {k === "all" ? "All seats" : k.charAt(0).toUpperCase() + k.slice(1)}
              <span className={styles.tabCount}>{counts[k]}</span>
            </button>
          ))}
        </div>
        <label className={styles.find}>
          <span className={styles.findLabel}>Find</span>
          <input
            type="search"
            className={styles.findInput}
            value={find}
            placeholder="seat, ticket or role"
            aria-label="Find a seat"
            data-testid="seat-find"
            onChange={(e) => setFind(e.target.value)}
          />
        </label>
      </div>

      {shown.length === 0 ? (
        <p className={styles.empty}>{needle ? `No seat matches “${find.trim()}”.` : "No seats in this group."}</p>
      ) : (
        <table className={styles.table} aria-label="Seats">
          {/* S17 c-7822cf388d: fixed column shares so the table fills the canvas at 1440 and every
              row lines up; below 1100px the rows stack as labelled cards (no horizontal scroll). */}
          <colgroup>
            <col className={styles.colSeat} />
            <col className={styles.colTicket} />
            <col className={styles.colStatus} />
            <col className={styles.colRefresh} />
            <col className={styles.colActions} />
          </colgroup>
          <thead>
            <tr>
              <th>Seat / shell state</th>
              <th>Assigned ticket</th>
              <th>Latest work status</th>
              <th>Last refresh</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((seat) => (
              <SeatTableRow key={seat.id} seat={seat} caps={caps} />
            ))}
          </tbody>
        </table>
      )}

      {people.length > 0 ? (
        <section className={styles.people} aria-label="People">
          <h2 className={styles.sectionLabel}>People</h2>
          <ul className={styles.peopleList}>
            {people.map((p) => (
              <li key={p.id} className={styles.person} data-testid="person-row">
                <span className={styles.personName}>
                  <Avatar id={p.id} size={24} />
                  {p.handle}
                </span>
                <span className={styles.personRole}>{glossLabel("role", p.role)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className={styles.footnote}>
        Shell alive ≠ work progressing. Latest work status is the seat's last report.
      </p>
      <p className={styles.footnote}>
        Resume continues the saved session on parked and closed seats. Messages to closed seats stay
        on the ticket for the next shell.
      </p>
    </>
  );
}

function FrameOnly({ children }: { children: React.ReactNode }): React.JSX.Element {
  usePageFrame(FRAMING);
  return (
    <>
      <header className={styles.head}>
        <h1 className={styles.title}>The people behind the work.</h1>
        <p className={styles.subtitle} data-testid="seats-framing">
          {FRAMING}
        </p>
      </header>
      <p className={styles.empty}>{children}</p>
    </>
  );
}

// One seat row — the presence rule + name-first identity + latest status framed as what the seat
// SAID, plus Message / Resume actions. Reused by the Decisions "Seats, now" block (design §4.2).
export function SeatTableRow({ seat, caps }: { seat: SeatRow; caps: PoolCapabilities | undefined }): React.JSX.Element {
  const now = Date.now();
  const presence = presenceOf(seat, caps, now);
  // Human #24: an Epic page "Message" lands here as /seats?message=<seat-id>#<seat-id> — the row
  // opens with its composer already showing.
  const { search } = useLocation();
  const [messaging, setMessaging] = useState(() => new URLSearchParams(search).get("message") === seat.id);
  const [reply, setReply] = useState<{ id: string; by: string } | null>(null); // round 2 #16
  const qc = useQueryClient();

  // "Closed" is ONLY a board-recorded dead seat. A seat with no mirrored session (state == null) is
  // remote — its availability is unknown, which is NOT death and must never be labelled Closed or
  // promise/deny a wake as if it were (c-c98b3e4319, §4.2: silence is never death).
  const isClosed = seat.state === "dead";
  const isUnknown = seat.state == null;
  const canResumeClosed = caps?.resume_closed === true;

  const resume = useMutation({
    mutationFn: () => resumeSeat(seat.id, seat.ticket_id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["seats"] }),
  });

  return (
    <>
      <tr id={seat.id} data-testid="seat-row" data-seat={seat.id} data-presence={presence.kind}>
        <td data-label="Seat">
          <div className={styles.seatName}>
            <Avatar id={seat.id} size={24} />
            {seat.handle}
          </div>
          <div className={styles.seatRole}>{glossLabel("role", seat.role)}</div>
          <div className={styles.stateLine}>
            <span className={`${styles.dot} ${styles[presence.dot]}`} aria-hidden="true" />
            <span data-testid="seat-state">{presence.word}</span>
          </div>
          {presence.detail ? <div className={styles.stateDetail}>{presence.detail}</div> : null}
        </td>

        <td data-label="Assigned ticket">
          {seat.ticket_id ? (
            <Link className={styles.ticketLink} to={`/ticket/${encodeURIComponent(seat.ticket_id)}`}>
              <span className={styles.ticketTitle}>{seat.ticket_title ?? seat.ticket_id}</span>
              <span className={styles.mono}>{seat.ticket_id}</span>
            </Link>
          ) : (
            <span className={styles.muted}>—</span>
          )}
        </td>

        <td data-label="Latest work status">
          {seat.latest_status ? (
            <div data-testid="latest-status">
              <div className={styles.statusText}>{seat.latest_status.text}</div>
              <div className={styles.statusMeta}>
                Status · {glossLabel("role", seat.latest_status.role ?? seat.role)} ·{" "}
                {clock(seat.latest_status.at, now)}
              </div>
            </div>
          ) : (
            <span className={styles.muted} data-testid="no-status">
              Last work update unavailable
            </span>
          )}
        </td>

        <td data-label="Last refresh">
          <div className={styles.refresh}>{clock(seat.last_output_at, now)}</div>
          {seat.last_output_at ? (
            <div className={styles.statusMeta}>Output: {clock(seat.last_output_at, now)}</div>
          ) : null}
        </td>

        <td data-label="Actions" className={styles.actionsCell}>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.action}
              data-testid="seat-message"
              {...copyProps("seats", "message")}
              aria-expanded={messaging}
              onClick={() => setMessaging((m) => !m)}
            >
              Message
            </button>
            {presence.showResume ? (
              <button
                type="button"
                className={styles.action}
                data-testid="seat-resume"
                {...copyProps("seats", "resume")}
                disabled={resume.isPending}
                onClick={() => resume.mutate()}
              >
                {resume.isPending ? "Resuming…" : "Resume"}
              </button>
            ) : isClosed && !canResumeClosed ? (
              <span className={styles.resumeNote} data-testid="no-resume-note">
                Closed; the owner shell can spawn a fresh seat.
              </span>
            ) : null}
          </div>
        </td>
      </tr>

      {messaging ? (
        <tr className={styles.messageRow}>
          <td colSpan={5}>
            <div className={styles.messagePanel}>
              <p className={styles.deliveryNote} data-testid="seat-delivery-note">
                {isClosed
                  ? "This seat is closed — your message waits on its ticket for the next shell; nobody is woken now."
                  : isUnknown
                  ? "This seat is remote and its availability is unknown — your message waits on its ticket; we can't promise a wake."
                  : `Sending will wake ${seat.handle} now.`}
              </p>
              {seat.ticket_id ? (
                <>
                  <SeatThread ticketId={seat.ticket_id} seat={seat} onReply={(m) => setReply(m)} />
                  <Composer
                    key={reply?.id ?? "new"}
                    ticketId={seat.ticket_id}
                    to={seat.handle}
                    kinds={reply ? ["answer", "note"] : ["note", "question"]}
                    replyTo={reply?.id ?? null}
                    replyToBy={reply?.by ?? null}
                    onCancelReply={() => setReply(null)}
                    placeholder={reply ? `Reply to @${reply.by}` : `Message ${seat.handle}…`}
                  />
                </>
              ) : (
                <p className={styles.muted}>
                  This seat has no assigned ticket to post on — reach it from its ticket thread instead.
                </p>
              )}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

// The conversation with ONE seat, both directions, shown where the human writes it (the Seats row)
// rather than only on the ticket thread (human report m-08822c1496, 2026-09-10). Read from
// /v1/messages on the seat's ticket; the feed's invalidation refreshes it when the seat answers.
function SeatThread({
  ticketId,
  seat,
  onReply,
}: {
  ticketId: string;
  seat: SeatRow;
  onReply?: (m: { id: string; by: string }) => void;
}): React.JSX.Element {
  const viewer = identity();
  const mine = useViewerAliases(); // round 2 #4: canonical id + handle, not the raw login string
  const q = useQuery({
    queryKey: ["messages", ticketId, seat.id],
    queryFn: () => api<RawMessage[]>(`/v1/messages?ticket_id=${encodeURIComponent(ticketId)}&limit=200`),
    retry: false,
  });
  const theirs = new Set([seat.id, seat.handle, `@${seat.handle}`]);
  const isMine = (v: string | null | undefined) => !!v && mine.has(v);
  const isTheirs = (v: string | null | undefined) => !!v && theirs.has(v);
  const rows = (q.data ?? []).filter(
    (m) => (isTheirs(m.created_by) && (isMine(m.to) || m.to == null)) || (isMine(m.created_by) && isTheirs(m.to)),
  );
  if (q.isError) return <p className={styles.muted}>The conversation could not be loaded.</p>;
  if (rows.length === 0) return <p className={styles.muted} data-testid="seat-thread-empty">No messages with {seat.handle} yet.</p>;
  return (
    <ul className={styles.seatThread} data-testid="seat-thread">
      {rows.map((m) => (
        <li key={m.id} className={styles.seatThreadRow}>
          <AgentLine by={m.created_by} kind={m.kind} to={m.to} viewer={viewer} at={m.created_at} />
          <MessageText className={styles.seatThreadText} text={m.text} />
          {onReply && !isMine(m.created_by) ? (
            <button type="button" className={styles.replyBtn} data-testid="seat-reply" onClick={() => onReply({ id: m.id, by: m.created_by })}>
              Reply
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

interface RawMessage {
  id: string;
  created_by: string;
  to: string | null;
  kind: string;
  text: string;
  created_at: string;
  reply_to: string | null;
}
