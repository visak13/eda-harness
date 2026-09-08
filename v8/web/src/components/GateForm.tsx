import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { GateRow } from "../api/types";
import { answerGate } from "../api/decisions";
import { Term } from "./Term";
import styles from "./GateForm.module.css";

// One open gate the owner can answer (design §5, folded S7). The gate kind is FIXED (it is the
// gate that was opened); the owner writes a ruling and presses the button — Enter in the textarea
// inserts a newline and never submits (a gate answer is deliberate, not a stray keypress). On
// answer the board drops the gate and releases any signed_off story the gate held → it shows as
// ready. The wake of the opener is the board's job (after_gate_answer).
export interface GateFormProps {
  gate: GateRow;
  onAnswered?: () => void;
}

export function GateForm({ gate, onAnswered }: GateFormProps): React.JSX.Element {
  const qc = useQueryClient();
  const [answer, setAnswer] = useState("");

  const submit = useMutation({
    mutationFn: () => answerGate(gate.ticket_id, gate.gate, answer.trim()),
    onSuccess: () => {
      setAnswer("");
      void qc.invalidateQueries();
      onAnswered?.();
    },
  });

  return (
    <section className={styles.gate} data-testid="gate-form" aria-label={`Gate ${gate.gate}`}>
      <header className={styles.head}>
        <span className={styles.kind} data-testid="gate-kind">
          <Term category="gate" value={gate.gate} />
        </span>
        <span className={styles.crumb}>{gate.ticket_id}</span>
      </header>
      <div className={styles.meta}>
        opened by {gate.by}
        {gate.note ? <> — “{gate.note}”</> : null}
      </div>
      <label className={styles.label} htmlFor={`gate-${gate.ticket_id}-${gate.gate}`}>
        YOUR RULING
      </label>
      <textarea
        id={`gate-${gate.ticket_id}-${gate.gate}`}
        className={styles.ruling}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        rows={3}
        placeholder="Write your ruling. Enter for a newline; the button submits."
        data-testid="gate-answer"
      />
      {submit.error ? (
        <p className={styles.error} role="alert">
          {submit.error instanceof Error ? submit.error.message : "Failed"} — your ruling is kept.
        </p>
      ) : null}
      <button
        className={styles.submit}
        type="button"
        disabled={answer.trim().length === 0 || submit.isPending}
        onClick={() => submit.mutate()}
        data-testid="gate-submit"
      >
        Answer gate
      </button>
    </section>
  );
}
