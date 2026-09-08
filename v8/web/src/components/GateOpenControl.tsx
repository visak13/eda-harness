import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { openGate } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import { GATE_KINDS } from "../api/types";
import { label as glossLabel, meaning as glossMeaning } from "../copy/glossary";
import styles from "./GateOpenControl.module.css";

// Open-a-gate control (design §5, §16): raise a decision the owner must rule on, from the object it
// concerns. The gate kinds are the board's enum; each carries its glossary meaning so the person
// picks the right question. The other half of the loop — answering — is GateForm, mounted on
// Decisions and on the Ticket page's "Answer a decision" card. The board decides who may open and
// what it holds; its hint is shown verbatim.
export function GateOpenControl({
  ticketId,
  onOpened,
}: {
  ticketId: string;
  onOpened?: () => void;
}): React.JSX.Element {
  const qc = useQueryClient();
  const [gate, setGate] = useState<string>(GATE_KINDS[0]);
  const [note, setNote] = useState("");

  const open = useMutation({
    mutationFn: () => openGate(ticketId, gate, note.trim()),
    onSuccess: () => {
      setNote("");
      void qc.invalidateQueries();
      onOpened?.();
    },
  });

  return (
    <form
      className={styles.form}
      data-testid="gate-open"
      onSubmit={(e) => {
        e.preventDefault();
        open.mutate();
      }}
    >
      <label className={styles.label} htmlFor="gate-kind">
        Open a gate
      </label>
      <select
        id="gate-kind"
        className={styles.select}
        value={gate}
        onChange={(e) => setGate(e.target.value)}
        data-testid="gate-open-kind"
      >
        {GATE_KINDS.map((g) => (
          <option key={g} value={g}>
            {glossLabel("gate", g)}
          </option>
        ))}
      </select>
      <p className={styles.hint}>{glossMeaning("gate", gate)}</p>
      <textarea
        className={styles.textarea}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="What are you asking to be decided? (optional)"
        rows={2}
        aria-label="Gate note"
      />
      <button type="submit" className={styles.submit} disabled={open.isPending}>
        {open.isPending ? "Opening…" : `Open the ${glossLabel("gate", gate)} gate`}
      </button>
      {open.isError ? (
        <p className={styles.error} role="alert" data-testid="gate-open-error">
          {(open.error as BoardApiError).hint ?? (open.error as Error).message}
        </p>
      ) : null}
    </form>
  );
}
