import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createLink, sendMessage } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import { ROLES } from "../api/types";
import { label as glossLabel } from "../copy/glossary";
import styles from "./TicketAsks.module.css";

// Two more ticket controls (design §16): link a document to the ticket with a named relation, and
// ask a role a question on the ticket thread. Both are board writes with the standard envelope; the
// board owns who may write and its plain-sentence hint is shown verbatim. Reply itself is Composer.

const RELATIONS = ["evidence_for", "design_ref", "related", "supersedes"] as const;

export function LinkDocControl({ ticketId }: { ticketId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const [docId, setDocId] = useState("");
  const [relation, setRelation] = useState<string>(RELATIONS[0]);
  const [linked, setLinked] = useState(false);

  const link = useMutation({
    mutationFn: () => createLink({ from_id: ticketId, to_id: docId.trim(), relation }),
    onSuccess: () => {
      setDocId("");
      setLinked(true);
      void qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
  });

  return (
    <form
      className={styles.block}
      data-testid="link-doc"
      onSubmit={(e) => {
        e.preventDefault();
        if (docId.trim()) link.mutate();
      }}
    >
      <label className={styles.label} htmlFor="link-doc-id">
        Link a document
      </label>
      <div className={styles.row}>
        <input
          id="link-doc-id"
          className={styles.input}
          value={docId}
          onChange={(e) => {
            setDocId(e.target.value);
            setLinked(false);
          }}
          placeholder="document id"
        />
        <select
          className={styles.select}
          value={relation}
          onChange={(e) => setRelation(e.target.value)}
          aria-label="Relation"
          data-testid="link-relation"
        >
          {RELATIONS.map((r) => (
            <option key={r} value={r}>
              {r.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <button type="submit" className={styles.btn} disabled={!docId.trim() || link.isPending}>
          {link.isPending ? "Linking…" : "Link"}
        </button>
      </div>
      {linked ? (
        <p className={styles.ok} data-testid="link-doc-ok">
          Linked — it now shows under this ticket&rsquo;s documents.
        </p>
      ) : null}
      {link.isError ? (
        <p className={styles.error} role="alert" data-testid="link-doc-error">
          {(link.error as BoardApiError).hint ?? (link.error as Error).message}
        </p>
      ) : null}
    </form>
  );
}

export function AskRoleControl({ ticketId }: { ticketId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const [role, setRole] = useState<string>("architect");
  const [text, setText] = useState("");
  const [asked, setAsked] = useState(false);

  const ask = useMutation({
    mutationFn: () => sendMessage({ ticket_id: ticketId, kind: "question", to: role, text: text.trim() }),
    onSuccess: () => {
      setText("");
      setAsked(true);
      void qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
    },
  });

  return (
    <form
      className={styles.block}
      data-testid="ask-role"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) ask.mutate();
      }}
    >
      <label className={styles.label} htmlFor="ask-role-select">
        Ask a role
      </label>
      <div className={styles.row}>
        <select
          id="ask-role-select"
          className={styles.select}
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            setAsked(false);
          }}
          data-testid="ask-role-select"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {glossLabel("role", r)}
            </option>
          ))}
        </select>
      </div>
      <textarea
        className={styles.textarea}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setAsked(false);
        }}
        placeholder={`Ask the ${glossLabel("role", role)} a question — posts to this ticket`}
        aria-label="Question"
        rows={2}
      />
      <button type="submit" className={styles.btn} disabled={!text.trim() || ask.isPending}>
        {ask.isPending ? "Asking…" : `Ask the ${glossLabel("role", role)}`}
      </button>
      {asked ? (
        <p className={styles.ok} data-testid="ask-role-ok">
          Asked — it&rsquo;s on the thread and in their feed.
        </p>
      ) : null}
      {ask.isError ? (
        <p className={styles.error} role="alert" data-testid="ask-role-error">
          {(ask.error as BoardApiError).hint ?? (ask.error as Error).message}
        </p>
      ) : null}
    </form>
  );
}
