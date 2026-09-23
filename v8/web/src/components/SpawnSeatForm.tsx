import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getModels, modelLabel, spawnSeat } from "../api/seats";
import { BoardApiError } from "../api/client";
import type { ModelCatalog } from "../api/types";
import ui from "./ui.module.css";
import styles from "./SpawnSeatForm.module.css";

// S-ROLES (design-34bf11cc07 §4.1, owner m-bba708e10e): "Spawn seat" on the Seats page — any role of
// the models.json catalog, on any ticket, on a model from THAT role's catalog, without going through
// the architect (the owner may spawn an engineer when the architect's subscription is exhausted). The
// seat id is `<role>.<ticket>`; doing roles (engineer, sme) take the ticket as its assignee by default
// — a checker (qa, adversary) never becomes the assignee. Authorisation and idempotency are the
// board's; its hint and errors are shown verbatim.

const DOING_ROLES = new Set(["engineer", "sme"]);

export function SpawnSeatForm(): React.JSX.Element {
  const qc = useQueryClient();
  const modelsQ = useQuery({ queryKey: ["models"], queryFn: getModels, retry: false });
  const catalog = modelsQ.data as ModelCatalog | undefined;
  const roles = Object.keys(catalog?.roles ?? {});
  const [role, setRole] = useState("engineer");
  const [ticket, setTicket] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [assignPick, setAssignPick] = useState<boolean | null>(null);
  const activeRole = roles.includes(role) ? role : (roles[0] ?? role);
  const options = catalog?.roles[activeRole] ?? [];
  const model = picked && options.includes(picked) ? picked : (catalog?.defaults[activeRole] ?? "");
  const assign = assignPick ?? DOING_ROLES.has(activeRole);
  const ticketId = ticket.trim();
  const seatId = ticketId ? `${activeRole}.${ticketId}` : "";

  const spawn = useMutation({
    mutationFn: () => spawnSeat(activeRole, seatId, ticketId, { model, assign }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["seats"] });
      void qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
  });
  const err = spawn.error as BoardApiError | undefined;

  if (modelsQ.isError) {
    return <p className={styles.note} role="alert" data-testid="spawn-seat-unavailable">The model catalog could not be loaded, so Spawn seat is unavailable.</p>;
  }
  return (
    <form
      className={styles.form}
      aria-label="Spawn seat"
      data-testid="spawn-seat-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (ticketId && model && !spawn.isPending) spawn.mutate();
      }}
    >
      <h2 className={styles.heading}>Spawn seat</h2>
      <div className={styles.fields}>
        <label>
          Role
          <select className={ui.select} value={activeRole} data-testid="spawn-seat-role"
            onChange={(e) => { setRole(e.target.value); setPicked(null); setAssignPick(null); spawn.reset(); }}>
            {roles.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label>
          Ticket
          <input className={ui.input} value={ticket} placeholder="s-… or epic-…" data-testid="spawn-seat-ticket"
            onChange={(e) => { setTicket(e.target.value); spawn.reset(); }} />
        </label>
        <label>
          Model
          <select className={ui.select} value={model} data-testid="spawn-seat-model"
            onChange={(e) => setPicked(e.target.value)}>
            {options.map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
          </select>
        </label>
      </div>
      <label className={styles.check}>
        <input type="checkbox" checked={assign} data-testid="spawn-seat-assign" onChange={(e) => setAssignPick(e.target.checked)} />
        Make this seat the ticket's assignee
      </label>
      <p className={styles.note} data-testid="spawn-seat-preview">
        {seatId
          ? `Starts ${seatId} on ${modelLabel(model)}${assign ? ` and assigns ${ticketId} to it` : ""}.`
          : "Name the ticket the seat works on."}
      </p>
      {err ? <p className={styles.error} role="alert" data-testid="spawn-seat-error">{err.hint ?? err.message}</p> : null}
      {spawn.isSuccess ? (
        <p className={styles.note} role="status" data-testid="spawn-seat-done">
          {spawn.data.hint || `Spawned ${seatId}.`}
        </p>
      ) : null}
      <div>
        <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!ticketId || !model || spawn.isPending} data-testid="spawn-seat-submit">
          {spawn.isPending ? "Spawning…" : "Spawn seat"}
        </button>
      </div>
    </form>
  );
}
