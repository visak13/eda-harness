import { hideFromGuests, usePoolCapabilities } from "../auth/guest";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { patchTicket } from "../api/endpoints";
import { modelLabel, spawnSeat } from "../api/seats";
import { BoardApiError } from "../api/client";
import type { PoolCapabilities, SeatChoice } from "../api/types";
import styles from "./AssignControl.module.css";

/** Plain words for a seat choice (owner m-2d7ef9243d): "GPT-6 Astra, effort high" / "Claude, effort
 *  medium"; a Claude epic that asked for high shows the board's cap note verbatim. */
export function seatChoiceWords(c: SeatChoice | null | undefined): string {
  if (!c) return "Claude (the fleet default)";
  const model = c.model == null ? "Claude" : modelLabel(c.model);
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

/** S12-ui2 (qa m-da89ef8294): whether the pool can spawn a seat here (shares the capabilities query). The
 *  Actions label follows it, so the dialog never offers a spawn its body then says is unavailable. */
export function usePoolCanSpawn(): boolean {
  const capsQ = usePoolCapabilities();
  return !!(capsQ.data as PoolCapabilities | undefined)?.spawn;
}

export const assignLabel = (canSpawn: boolean): string => (canSpawn ? "Assign or spawn a seat" : "Assign a seat");

// Assign / spawn control (design §16): put a seat on the ticket without leaving the page. Two ways —
// name an existing participant as the assignee (a plain PATCH), or spawn a fresh engineer seat for
// this ticket through the pool. Spawn shows ONLY when the pool reports it can (capabilities), so the
// page never offers an action the environment can't perform; when it can't, it says why in plain
// words. Authorisation and idempotency are the board's — the control reports its hint verbatim.
function AssignControlView({
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
  const capsQ = usePoolCapabilities();
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
        <span data-testid="assign-current">{currentAssignee ?? "Unassigned"}</span>
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
      ) : caps?.reason ? (
        // the pool's own reason, when it gives one; no fallback sentence (the dialog is then titled "Assign a seat")
        <p className={styles.note} data-testid="spawn-unavailable">
          {caps.reason}
        </p>
      ) : null}

      {err ? (
        <p className={styles.error} role="alert" data-testid="assign-error">
          {err.hint ?? err.message}
        </p>
      ) : null}
    </div>
  );
}

/** e0cec S5: a guest never sees this control (the board refuses it). */
export const AssignControl = hideFromGuests(AssignControlView);
