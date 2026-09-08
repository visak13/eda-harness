import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { sendMessage, updateDoc } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import { ROLES } from "../api/types";
import { label as glossLabel } from "../copy/glossary";
import styles from "./DocControls.module.css";

// Doc controls (design §16): the two loop-closing actions the reader doesn't already carry —
// request a review (ask a role to look, as a question on the doc's scope thread) and publish a new
// version (PATCH the body; the board records it as a new version). Per-criterion Approve/Needs-work
// is SignoffPane and Comment is DocView's box — this fills the rest. Only shown when the doc's scope
// is a ticket/epic thread; a domain- or global-scoped doc has no thread to ask on. The board owns
// who may write; its plain-sentence hint is shown verbatim on refusal.
export function DocControls({
  docId,
  scope,
  version,
  scopeIsThread,
}: {
  docId: string;
  scope: string;
  version: number;
  scopeIsThread: boolean;
}): React.JSX.Element {
  return (
    <div className={styles.controls} data-testid="doc-controls">
      {scopeIsThread ? <RequestReview docId={docId} scope={scope} version={version} /> : null}
      <NewVersion docId={docId} />
    </div>
  );
}

function RequestReview({
  docId,
  scope,
  version,
}: {
  docId: string;
  scope: string;
  version: number;
}): React.JSX.Element {
  const qc = useQueryClient();
  const [role, setRole] = useState<string>("reviewer");
  const [note, setNote] = useState("");
  const [asked, setAsked] = useState(false);

  const ask = useMutation({
    mutationFn: () =>
      sendMessage({
        ticket_id: scope,
        kind: "question",
        to: role,
        text: `[doc ${docId} v${version}] Please review this document. ${note}`.trim(),
      }),
    onSuccess: () => {
      setNote("");
      setAsked(true);
      void qc.invalidateQueries();
    },
  });

  return (
    <form
      className={styles.block}
      data-testid="doc-request-review"
      onSubmit={(e) => {
        e.preventDefault();
        ask.mutate();
      }}
    >
      <label className={styles.label} htmlFor="review-role">
        Request a review
      </label>
      <div className={styles.row}>
        <select
          id="review-role"
          className={styles.select}
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            setAsked(false);
          }}
          data-testid="review-role"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {glossLabel("role", r)}
            </option>
          ))}
        </select>
        <button type="submit" className={styles.btn} disabled={ask.isPending}>
          {ask.isPending ? "Asking…" : "Ask for a review"}
        </button>
      </div>
      <input
        className={styles.input}
        value={note}
        onChange={(e) => {
          setNote(e.target.value);
          setAsked(false);
        }}
        placeholder="What should they look at? (optional)"
        aria-label="Review note"
      />
      {asked ? (
        <p className={styles.ok} data-testid="doc-review-asked">
          Asked {glossLabel("role", role)} to review — it&rsquo;s on the {scope} thread.
        </p>
      ) : null}
      {ask.isError ? (
        <p className={styles.error} role="alert" data-testid="doc-review-error">
          {(ask.error as BoardApiError).hint ?? (ask.error as Error).message}
        </p>
      ) : null}
    </form>
  );
}

function NewVersion({ docId }: { docId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");

  const save = useMutation({
    mutationFn: () => updateDoc(docId, { body_md: body }),
    onSuccess: () => {
      setBody("");
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["doc", docId] });
    },
  });

  if (!open) {
    return (
      <button
        type="button"
        className={styles.btn}
        data-testid="doc-new-version-open"
        onClick={() => setOpen(true)}
      >
        Publish a new version
      </button>
    );
  }

  return (
    <form
      className={styles.block}
      data-testid="doc-new-version"
      onSubmit={(e) => {
        e.preventDefault();
        if (body.trim()) save.mutate();
      }}
    >
      <label className={styles.label} htmlFor="new-version-body">
        New version (replaces the document body; the board keeps every version)
      </label>
      <textarea
        id="new-version-body"
        className={styles.textarea}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="The full Markdown for the new version"
        rows={8}
      />
      <div className={styles.row}>
        <button type="submit" className={styles.btn} disabled={!body.trim() || save.isPending}>
          {save.isPending ? "Publishing…" : "Publish new version"}
        </button>
        <button type="button" className={styles.cancel} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {save.isError ? (
        <p className={styles.error} role="alert" data-testid="doc-new-version-error">
          {(save.error as BoardApiError).hint ?? (save.error as Error).message}
        </p>
      ) : null}
    </form>
  );
}
