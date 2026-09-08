import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createCriterion, rewordCriterion } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import { CHECKS } from "../api/types";
import { label as glossLabel, meaning as glossMeaning } from "../copy/glossary";
import styles from "./CriterionControls.module.css";

// Criterion controls (design §16): add a new acceptance criterion, or reword an existing one, from
// the ticket page. The board owns who may write and derives checked_by from the ticket — the
// control names the check kind (with its glossary meaning) and reports the board's hint verbatim.
// Rewording reuses the same PATCH route the verdict path uses; there is no second write of the rule.

export function AddCriterion({ ticketId }: { ticketId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [check, setCheck] = useState<string>("command");

  const add = useMutation({
    mutationFn: () => createCriterion({ ticket_id: ticketId, text: text.trim(), check }),
    onSuccess: () => {
      setText("");
      void qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
  });

  return (
    <form
      className={styles.form}
      data-testid="add-criterion"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) add.mutate();
      }}
    >
      <label className={styles.label} htmlFor="crit-text">
        New acceptance criterion
      </label>
      <textarea
        id="crit-text"
        className={styles.textarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="What must be true for this to be done?"
        rows={2}
      />
      <div className={styles.row}>
        <label className={styles.checkLabel} htmlFor="crit-check">
          Checked by
        </label>
        <select
          id="crit-check"
          className={styles.select}
          value={check}
          onChange={(e) => setCheck(e.target.value)}
          data-testid="add-criterion-check"
        >
          {CHECKS.map((c) => (
            <option key={c} value={c}>
              {glossLabel("check", c)}
            </option>
          ))}
        </select>
      </div>
      <p className={styles.hint}>{glossMeaning("check", check)}</p>
      <button type="submit" className={styles.submit} disabled={!text.trim() || add.isPending}>
        {add.isPending ? "Adding…" : "Add criterion"}
      </button>
      {add.isError ? (
        <p className={styles.error} role="alert" data-testid="add-criterion-error">
          {(add.error as BoardApiError).hint ?? (add.error as Error).message}
        </p>
      ) : null}
    </form>
  );
}

// Inline reword of one existing criterion (a small edit affordance the CriterionCard opens).
export function RewordCriterion({
  criterionId,
  ticketId,
  current,
  onDone,
}: {
  criterionId: string;
  ticketId: string;
  current: string;
  onDone: () => void;
}): React.JSX.Element {
  const qc = useQueryClient();
  const [text, setText] = useState(current);

  const save = useMutation({
    mutationFn: () => rewordCriterion(criterionId, text.trim()),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
      onDone();
    },
  });

  return (
    <form
      className={styles.form}
      data-testid="reword-criterion"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim() && text.trim() !== current) save.mutate();
        else onDone();
      }}
    >
      <label className={styles.label} htmlFor={`reword-${criterionId}`}>
        Reword this criterion
      </label>
      <textarea
        id={`reword-${criterionId}`}
        className={styles.textarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
      />
      <div className={styles.row}>
        <button type="submit" className={styles.submit} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save wording"}
        </button>
        <button type="button" className={styles.cancel} onClick={onDone}>
          Cancel
        </button>
      </div>
      {save.isError ? (
        <p className={styles.error} role="alert" data-testid="reword-criterion-error">
          {(save.error as BoardApiError).hint ?? (save.error as Error).message}
        </p>
      ) : null}
    </form>
  );
}
