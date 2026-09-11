import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { createEpic } from "../api/endpoints";
import { getPoolCapabilities, spawnSeat } from "../api/seats";
import type { PoolCapabilities } from "../api/types";
import { BoardApiError } from "../api/client";
import ui from "./ui.module.css";
import styles from "./NewEpicDialog.module.css";

// Human #22 (2026-09-10): the header "New epic" button was a plate artifact with no handler. It now
// opens this dialog — the owner card's step 1 without a shell: the words go to the board VERBATIM
// (POST /v1/tickets kind=epic; the board keeps them in `words` and derives the short title, ruling
// #32), then, when the box is ticked and the pool can spawn, role=architect is spawned on the new
// epic (POST /v1/sessions/spawn). The preview says exactly what will happen and who is woken before
// the reader confirms; the board's hints show verbatim; success navigates to the epic's page.
export function NewEpicDialog({ open, onClose }: { open: boolean; onClose: () => void }): React.JSX.Element | null {
  const [words, setWords] = useState("");
  const [spawn, setSpawn] = useState(true);
  const [done, setDone] = useState<{ id: string; hint: string; spawnHint: string | null } | null>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const textRef = useRef<HTMLTextAreaElement>(null);
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false, enabled: open });
  const caps = capsQ.data as PoolCapabilities | undefined;
  const canSpawn = Boolean(caps?.spawn);

  useEffect(() => {
    if (open) {
      setDone(null);
      textRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const create = useMutation({
    mutationFn: async () => {
      const text = words.trim();
      const made = await createEpic(text);
      let spawnHint: string | null = null;
      if (spawn && canSpawn) {
        const res = await spawnSeat("architect", `architect.${made.value.id}`, made.value.id);
        spawnHint = res.hint || `Spawned architect.${made.value.id}.`;
      }
      return { id: made.value.id, hint: made.hint, spawnHint };
    },
    onSuccess: (res) => {
      setDone(res);
      void qc.invalidateQueries({ queryKey: ["epics", "summary"] });
      void qc.invalidateQueries({ queryKey: ["me", "summary"] });
      void qc.invalidateQueries({ queryKey: ["seats"] });
      navigate(`/epic/${encodeURIComponent(res.id)}`);
      onClose();
    },
  });
  const err = create.error as BoardApiError | undefined;

  if (!open) return null;
  const text = words.trim();
  return (
    <div className={styles.scrim} onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="new-epic-scrim">
      <form
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="New epic"
        data-testid="new-epic-dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (text && !create.isPending) create.mutate();
        }}
      >
        <h2 className={styles.title}>New epic</h2>
        <label className={ui.sectionLabel} htmlFor="new-epic-words">
          Your words
        </label>
        <textarea
          id="new-epic-words"
          ref={textRef}
          className={ui.textarea}
          rows={5}
          value={words}
          onChange={(e) => setWords(e.target.value)}
          placeholder="What you want, in your own words. They are kept verbatim; the board derives a short title."
          data-testid="new-epic-words"
        />
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={spawn}
            disabled={!canSpawn}
            onChange={(e) => setSpawn(e.target.checked)}
            data-testid="new-epic-spawn"
          />
          Spawn the architect
          {!canSpawn ? <span className={styles.muted}> — {caps?.reason ?? "the pool cannot spawn from here"}</span> : null}
        </label>
        <p className={styles.preview} data-testid="new-epic-preview">
          Creates the epic with your words verbatim; the board derives a short title.
          {spawn && canSpawn
            ? " Then spawns role=architect on it (wakes a new architect shell), which designs it and comes back to you with questions on Decisions."
            : " No seat is woken; spawn the architect later from the epic page."}
        </p>
        {err ? (
          <p className={ui.banner} role="alert" data-testid="new-epic-error">
            {err.hint ?? err.message}
          </p>
        ) : null}
        {done ? (
          <p className={styles.muted} role="status">
            {done.hint} {done.spawnHint ?? ""}
          </p>
        ) : null}
        <div className={styles.actions}>
          <button type="button" className={ui.button} onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className={`${ui.button} ${ui.buttonPrimary}`}
            disabled={!text || create.isPending}
            data-testid="new-epic-create"
          >
            {create.isPending ? "Creating…" : spawn && canSpawn ? "Create and spawn the architect" : "Create the epic"}
          </button>
        </div>
      </form>
    </div>
  );
}
