import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { patchTicket } from "../api/endpoints";
import { getPoolCapabilities, spawnSeat } from "../api/seats";
import { BoardApiError } from "../api/client";
import type { PoolCapabilities, SeatChoice } from "../api/types";
import styles from "./AssignControl.module.css";

/** Plain words for a seat choice (owner m-2d7ef9243d): "GPT-6 Astra, effort high" / "Claude, effort
 *  medium"; a Claude epic that asked for high shows the board's cap note verbatim. */
export function seatChoiceWords(c: SeatChoice | null | undefined): string {
  if (!c) return "Claude (the fleet default)";
  const model = c.model == null || c.model === "claude" ? "Claude" : c.model === "astra" ? "GPT-6 Astra" : c.model;
  const effort = c.effort ? `, effort ${c.effort}` : "";
  return `${model}${effort}${c.note ? ` — ${c.note}` : ""}`;
}

/** Read-only: which model + effort a spawn from here will run on (the epic's choice). */
export function SeatChoiceLabel({ choice }: { choice: SeatChoice | null | undefined }): React.JSX.Element {
  return (
    <p className={styles.note} data-testid="seat-choice">
      Seats spawned on this epic run on <strong>{seatChoiceWords(choice)}</strong>
      {choice ? "" : " — no choice recorded on this epic"}.
    </p>
  );
}

// Assign / spawn control (design §16): put a seat on the ticket without leaving the page. Two ways —
// name an existing participant as the assignee (a plain PATCH), or spawn a fresh engineer seat for
// this ticket through the pool. Spawn shows ONLY when the pool reports it can (capabilities), so the
// page never offers an action the environment can't perform; when it can't, it says why in plain
// words. Authorisation and idempotency are the board's — the control reports its hint verbatim.
export function AssignControl({
  ticketId,
  currentAssignee,
  seatChoice,
}: {
  ticketId: string;
  currentAssignee: string | null;
  /** The epic's seat choice, shown read-only above the spawn button (undefined = not shown). */
  seatChoice?: SeatChoice | null;
}): React.JSX.Element {
  const qc = useQueryClient();
  const [who, setWho] = useState("");
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false });
  const caps = capsQ.data as PoolCapabilities | undefined;

  // The control mounts on both the Ticket page (["ticket", id]) and the Epic page (["epic", id]);
  // refresh whichever owns this id so the seat rail updates in place after an assign/spawn.
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
    void qc.invalidateQueries({ queryKey: ["epic", ticketId] });
  };

  const assign = useMutation({
    mutationFn: (id: string) => patchTicket(ticketId, { assignee: id }),
    onSuccess: () => {
      setWho("");
      invalidate();
    },
  });
  const spawn = useMutation({
    mutationFn: () => spawnSeat("engineer", `engineer.${ticketId}`, ticketId),
    onSuccess: invalidate,
  });

  const err = (assign.error ?? spawn.error) as BoardApiError | undefined;

  return (
    <div className={styles.control} data-testid="assign-control">
      <p className={styles.current}>
        <span className={styles.currentLabel}>Assigned to</span>{" "}
        <span data-testid="assign-current">{currentAssignee ?? "no one yet"}</span>
      </p>

      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          if (who.trim()) assign.mutate(who.trim());
        }}
      >
        <label className={styles.label} htmlFor="assign-who">
          Assign an existing seat or person
        </label>
        <div className={styles.row}>
          <input
            id="assign-who"
            className={styles.input}
            value={who}
            onChange={(e) => setWho(e.target.value)}
            placeholder="participant id or @handle"
          />
          <button type="submit" className={styles.btn} disabled={!who.trim() || assign.isPending}>
            {assign.isPending ? "Assigning…" : "Assign"}
          </button>
        </div>
      </form>

      {seatChoice !== undefined ? <SeatChoiceLabel choice={seatChoice} /> : null}
      {caps?.spawn ? (
        <button
          type="button"
          className={styles.spawn}
          data-testid="spawn-seat"
          disabled={spawn.isPending}
          onClick={() => spawn.mutate()}
        >
          {spawn.isPending ? "Spawning…" : "Spawn a fresh engineer seat for this ticket"}
        </button>
      ) : (
        <p className={styles.note} data-testid="spawn-unavailable">
          {caps?.reason ?? "Spawning a seat isn't available here — assign an existing one instead."}
        </p>
      )}

      {err ? (
        <p className={styles.error} role="alert" data-testid="assign-error">
          {err.hint ?? err.message}
        </p>
      ) : null}
    </div>
  );
}
