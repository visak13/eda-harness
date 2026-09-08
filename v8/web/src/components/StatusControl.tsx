import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getTicketTransitions, patchTicket } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import type { TicketStatus, TicketTransition } from "../api/types";
import { label as glossLabel, meaning as glossMeaning } from "../copy/glossary";
import styles from "./StatusControl.module.css";

// The status control (design §16, "close every loop"): change a ticket's status from the page it
// lives on. The legal set and each blocked move's reason come from the SERVER
// (GET /v1/tickets/{id}/transitions → board.legal_transitions → the one _guard_transition), so the
// control can never offer a move the board would refuse, nor drift from enforcement. Each target
// carries a one-line consequence — the glossary meaning of the status it moves to — so the person
// sees what the move DOES before they make it. A blocked move stays visible but disabled, wearing
// the board's own reason; nothing is hidden, so the loop is legible even when you can't close it.
export function StatusControl({
  ticketId,
  currentStatus,
}: {
  ticketId: string;
  currentStatus: TicketStatus;
}): React.JSX.Element {
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<TicketStatus | null>(null);

  const q = useQuery({
    queryKey: ["ticket", ticketId, "transitions"],
    queryFn: () => getTicketTransitions(ticketId),
  });

  const move = useMutation({
    mutationFn: (to: TicketStatus) => patchTicket(ticketId, { status: to }),
    onSuccess: () => {
      setChosen(null);
      void qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
  });

  if (q.isPending) return <p className={styles.loading}>Loading the moves you can make…</p>;
  if (q.isError) {
    return (
      <p className={styles.error} role="alert">
        Could not load the status moves: {(q.error as Error).message}
      </p>
    );
  }

  const transitions = q.data.transitions;
  const currentLabel = glossLabel("ticket_status", currentStatus);

  return (
    <section className={styles.control} data-testid="status-control" aria-label="Change status">
      <div className={styles.now}>
        <span className={styles.nowLabel}>Now</span>
        <span className={styles.nowStatus} data-testid="status-now">
          {currentLabel}
        </span>
      </div>

      {transitions.length === 0 ? (
        <p className={styles.terminal} data-testid="status-terminal">
          This is a terminal status — there is nowhere further to move it.
        </p>
      ) : (
        <ul className={styles.moves}>
          {transitions.map((t) => (
            <MoveRow
              key={t.to}
              t={t}
              pending={move.isPending && chosen === t.to}
              onPick={() => {
                setChosen(t.to);
                move.mutate(t.to);
              }}
            />
          ))}
        </ul>
      )}

      {move.isError ? (
        <p className={styles.error} role="alert" data-testid="status-move-error">
          {(move.error as BoardApiError).hint ?? (move.error as Error).message}
        </p>
      ) : null}
    </section>
  );
}

function MoveRow({
  t,
  pending,
  onPick,
}: {
  t: TicketTransition;
  pending: boolean;
  onPick: () => void;
}): React.JSX.Element {
  const targetLabel = glossLabel("ticket_status", t.to);
  const consequence = glossMeaning("ticket_status", t.to);
  return (
    <li className={styles.move} data-testid="status-move" data-to={t.to} data-allowed={t.allowed}>
      <button
        type="button"
        className={styles.moveBtn}
        disabled={!t.allowed || pending}
        aria-disabled={!t.allowed}
        onClick={onPick}
        data-testid={`status-move-${t.to}`}
      >
        {pending ? `Moving to ${targetLabel}…` : `Move to ${targetLabel}`}
      </button>
      <p className={styles.consequence}>{consequence}</p>
      {!t.allowed && t.reason ? (
        <p className={styles.reason} data-testid="status-move-reason">
          {t.reason}
        </p>
      ) : null}
    </li>
  );
}
