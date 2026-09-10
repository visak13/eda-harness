import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getPoolCapabilities, spawnSeat } from "../api/seats";
import { BoardApiError } from "../api/client";
import type { PoolCapabilities } from "../api/types";
import { copyProps } from "../copy/pages";
import styles from "./AssignControl.module.css";

// "Spawn the architect" (promise #18, epic page): the same pool spawn AssignControl uses, with
// role=architect and participant architect.<epic>. Shows only when /v1/pool/capabilities reports
// spawn; the page does not know a seat's liveness (assigned_seats is assignees, not sessions), so
// the board decides whether a second architect is refused or replayed and its hint is shown
// verbatim, on success and on error. When an architect seat is already assigned the button says so.
export function SpawnArchitect({
  epicId,
  assignedSeats = [],
}: {
  epicId: string;
  assignedSeats?: string[];
}): React.JSX.Element | null {
  const qc = useQueryClient();
  const [hint, setHint] = useState<string | null>(null);
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false });
  const caps = capsQ.data as PoolCapabilities | undefined;
  const seatId = `architect.${epicId}`;
  const existing = assignedSeats.find((s) => s === seatId || s.startsWith("architect.")) ?? null;

  const spawn = useMutation({
    mutationFn: () => spawnSeat("architect", seatId, epicId),
    onSuccess: (res) => {
      setHint(res.hint || `Spawned ${seatId}.`);
      void qc.invalidateQueries({ queryKey: ["epic", epicId] });
      void qc.invalidateQueries({ queryKey: ["epics", "summary"] });
      void qc.invalidateQueries({ queryKey: ["seats"] });
    },
  });
  const err = spawn.error as BoardApiError | undefined;

  if (!caps?.spawn) return null;

  return (
    <div className={styles.control} data-testid="spawn-architect">
      <button
        type="button"
        className={styles.spawn}
        data-testid="spawn-architect-btn"
        disabled={spawn.isPending}
        onClick={() => spawn.mutate()}
        {...copyProps("epic", "spawn-architect")}
      >
        {spawn.isPending ? "Spawning…" : "Spawn the architect"}
      </button>
      {existing ? (
        <p className={styles.note} data-testid="spawn-architect-existing">
          {existing} already holds this epic — the board decides whether a second shell starts.
        </p>
      ) : null}
      {hint ? (
        <p className={styles.note} role="status" data-testid="spawn-architect-hint">
          {hint}
        </p>
      ) : null}
      {err ? (
        <p className={styles.error} role="alert" data-testid="spawn-architect-error">
          {err.hint ?? err.message}
        </p>
      ) : null}
    </div>
  );
}
