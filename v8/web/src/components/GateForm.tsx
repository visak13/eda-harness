import { useReducer, useRef, useState } from "react";
import { Link } from "react-router";
import { identity } from "../auth/identity";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { GateRow } from "../api/types";
import { answerGate } from "../api/endpoints";
import { useDirtyGuard } from "../live/useDraftGuard";
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
  /** The gate left the open list while this form held an unsent ruling (answered elsewhere). */
  closed?: boolean;
  onDismiss?: () => void;
}

// S22 (consult #3): a live refetch after the gate was answered in another tab dropped the gate from
// the list, which UNMOUNTED this form and lost the unsent ruling. Unsent rulings now live outside the
// component (this tab's memory, keyed by gate) and a page lists its gates through useRetainedGates,
// which keeps a gate that left the open list while its ruling was unsent — rendered `closed` with an
// "answered elsewhere" notice and the text intact until the owner dismisses it.
const unsent = new Map<string, string>();
const gateKey = (g: Pick<GateRow, "ticket_id" | "gate">) => `${g.ticket_id}:${g.gate}`;

export type RetainedGate = { gate: GateRow; closed: boolean; onDismiss?: () => void };

/** The page's open gates plus any gate answered elsewhere whose form still holds an unsent ruling. */
export function useRetainedGates(gates: GateRow[]): RetainedGate[] {
  const seen = useRef(new Map<string, GateRow>());
  const [, bump] = useReducer((n: number) => n + 1, 0);
  const live = new Set(gates.map(gateKey));
  for (const g of gates) seen.current.set(gateKey(g), g);
  const out: RetainedGate[] = gates.map((g) => ({ gate: g, closed: false }));
  for (const [k, g] of seen.current) {
    if (live.has(k)) continue;
    if (!unsent.get(k)?.trim()) { seen.current.delete(k); continue; }
    out.push({ gate: g, closed: true, onDismiss: () => { unsent.delete(k); seen.current.delete(k); bump(); } });
  }
  return out;
}

export function GateForm(props: GateFormProps): React.JSX.Element {
  const { gate } = props;
  if (gate.gate === "design_signoff") return <section className={styles.gate} data-testid="gate-form" aria-label="Gate design_signoff">
    <h3>Design review · {gate.ticket_id}</h3>
    <p>{gate.note}</p>
    <Link to={`/${gate.ticket_id === gate.epic ? "epic" : "ticket"}/${encodeURIComponent(gate.ticket_id)}?${new URLSearchParams({ as: identity(), ...(gate.event_id ? { request: gate.event_id } : {}) })}`}>
      Review design at source
    </Link>
  </section>;
  return <AcceptanceGateForm {...props} />;
}

function AcceptanceGateForm({ gate, onAnswered, closed, onDismiss }: GateFormProps): React.JSX.Element {
  const qc = useQueryClient();
  const [answer, setAnswerState] = useState(() => unsent.get(gateKey(gate)) ?? "");
  const setAnswer = (text: string) => {
    setAnswerState(text);
    if (text) unsent.set(gateKey(gate), text);
    else unsent.delete(gateKey(gate));
  };
  // §16.1: while a ruling is being typed the feed holds its events ("N new · refresh") instead of
  // refetching under the form — otherwise answering the gate elsewhere unmounted this form and the
  // draft with it (adversary finding #4, 2026-09-10).
  useDirtyGuard(`gate:${gate.ticket_id}:${gate.gate}`, answer.trim().length > 0, gate.ticket_id);

  const submit = useMutation({
    mutationFn: () => answerGate(gate.ticket_id, gate.gate, answer.trim()),
    onSuccess: () => {
      setAnswer("");
      void qc.invalidateQueries();
      onAnswered?.();
    },
  });

  return (
    <section className={styles.gate} data-testid="gate-form" data-closed={closed ? "true" : undefined} aria-label={`Gate ${gate.gate}`}>
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
      {closed ? (
        <p className={styles.closed} role="status" data-testid="gate-answered-elsewhere">
          Answered elsewhere — this gate is closed. Your unsent ruling is kept below; copy it before you dismiss it.
        </p>
      ) : null}
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
      {closed ? (
        <button className={styles.submit} type="button" onClick={() => { setAnswer(""); onDismiss?.(); }} data-testid="gate-dismiss">
          Dismiss
        </button>
      ) : (
        <button
          className={styles.submit}
          type="button"
          disabled={answer.trim().length === 0 || submit.isPending}
          onClick={() => submit.mutate()}
          data-testid="gate-submit"
        >
          Answer gate
        </button>
      )}
    </section>
  );
}
