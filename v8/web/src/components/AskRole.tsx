import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { sendMessage } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import { copyProps } from "../copy/pages";
import styles from "./AskRole.module.css";

// "Ask a role" (promise #17, epic page): a question on the epic thread addressed to a ROLE, so the
// human need not know the seat's id. The board resolves `to=<role>` to that role's seat on this
// epic (its architect / engineer / …) and wakes it; the sent confirmation is the board's own
// resolution note (envelope hint), shown verbatim. Posting invalidates the epic page so the
// thread shows the question at once.

export const ASK_ROLES = ["architect", "engineer", "reviewer", "qa", "coordinator", "owner"] as const;
export type AskRole = (typeof ASK_ROLES)[number];

export function AskRoleControl({ ticketId }: { ticketId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<AskRole>("architect");
  const [text, setText] = useState("");
  const [sent, setSent] = useState<string | null>(null);

  const ask = useMutation({
    mutationFn: () => sendMessage({ ticket_id: ticketId, kind: "question", to: role, text: text.trim() }),
    onSuccess: (res) => {
      setSent(res.hint || `Question sent to the ${role} on ${ticketId}.`);
      setText("");
      void qc.invalidateQueries({ queryKey: ["epic", ticketId] });
    },
  });
  const err = ask.error as BoardApiError | undefined;

  return (
    <div className={styles.control} data-testid="ask-role">
      <button
        type="button"
        className={styles.toggle}
        data-testid="ask-role-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        {...copyProps("epic", "ask-role")}
      >
        Ask a role
      </button>

      {open ? (
        <form
          className={styles.form}
          data-testid="ask-role-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) ask.mutate();
          }}
        >
          <label className={styles.label} htmlFor="ask-role-role">
            Role
          </label>
          <select
            id="ask-role-role"
            className={styles.select}
            value={role}
            onChange={(e) => setRole(e.target.value as AskRole)}
          >
            {ASK_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <label className={styles.label} htmlFor="ask-role-text">
            Question
          </label>
          <textarea
            id="ask-role-text"
            className={styles.text}
            rows={3}
            value={text}
            placeholder={`Ask the ${role} of this epic…`}
            onChange={(e) => setText(e.target.value)}
          />
          <p className={styles.wake} data-testid="ask-role-wake">
            Wakes the epic&rsquo;s {role} seat ({role}.{ticketId}); the question posts on the epic thread.
          </p>
          <button type="submit" className={styles.send} data-testid="ask-role-send" disabled={!text.trim() || ask.isPending}>
            {ask.isPending ? "Sending…" : `Ask the ${role}`}
          </button>
        </form>
      ) : null}

      {sent ? (
        <p className={styles.sent} role="status" data-testid="ask-role-sent">
          {sent}
        </p>
      ) : null}
      {err ? (
        <p className={styles.error} role="alert" data-testid="ask-role-error">
          {err.hint ?? err.message}
        </p>
      ) : null}
    </div>
  );
}
