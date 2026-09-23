import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createQuickTask } from "../api/endpoints";
import { getModels, getPoolCapabilities, modelLabel } from "../api/seats";
import { clampEffort, SeatPickHead, SeatPickRow, type Effort } from "./SeatPicks";
import type { ModelCatalog, PoolCapabilities } from "../api/types";
import { BoardApiError } from "../api/client";
import ui from "./ui.module.css";
import styles from "./NewEpicDialog.module.css";
import { useModalDialog } from "./useModalDialog";

// S-QUICK (design-34bf11cc07 §4.2, owner m-5b3db5cb0d "open a ticket and spawn an engg role for a small
// task of my own"): title, the owner's words and an engineer model from that role's catalog; ONE submit
// is ONE board call (POST /v1/quick-tasks) that creates the quick story, spawns engineer.<story> on the
// model and assigns it — so a down pool refuses before any ticket exists. The board's hint shows
// verbatim; success lands on the new story's page, where the seat's plan and criteria appear.

export function QuickTaskDialog({ open, onClose }: { open: boolean; onClose: () => void }): React.JSX.Element | null {
  const [title, setTitle] = useState("");
  const [words, setWords] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  // the ticket was opened but the pool refused the spawn: stay open, say so, link the ticket
  const [stranded, setStranded] = useState<{ id: string; hint: string } | null>(null);
  const panelRef = useRef<HTMLFormElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const modelsQ = useQuery({ queryKey: ["models"], queryFn: getModels, retry: false, enabled: open });
  const catalog = modelsQ.data as ModelCatalog | undefined;
  const options = catalog?.roles?.engineer ?? [];
  const model = picked && options.includes(picked) ? picked : (catalog?.defaults?.engineer ?? "");
  // S-UI: the engineer's effort beside its model (Claude capped at medium)
  const [effortPick, setEffortPick] = useState<Effort>("medium");
  const effort = clampEffort(model, effortPick);
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false, enabled: open });
  const caps = capsQ.data as PoolCapabilities | undefined;
  const canSpawn = Boolean(caps?.spawn);
  useModalDialog(open, panelRef, titleRef, busy, onClose);

  const create = useMutation({
    mutationFn: () => createQuickTask({ title, words, model: model || null, effort }),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ["seats"] });
      void qc.invalidateQueries({ queryKey: ["me", "summary"] });
      const id = res.value.ticket.id;
      setTitle(""); setWords(""); setPicked(null); setEffortPick("medium");
      if (!res.value.seat) { setStranded({ id, hint: res.hint }); return; }
      navigate(`/ticket/${encodeURIComponent(id)}`);
      onClose();
    },
    onSettled: () => { busy.current = false; },
  });
  const err = create.error as BoardApiError | undefined;

  if (!open) return null;
  const ready = !stranded && Boolean(title.trim()) && title.trim().length <= 80 && Boolean(words.trim()) && canSpawn;
  return createPortal(
    <div className={styles.scrim} onMouseDown={(e) => e.target === e.currentTarget && !busy.current && onClose()} data-testid="quick-task-scrim">
      <form
        className={styles.dialog}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Quick task"
        data-testid="quick-task-dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready && !busy.current) { busy.current = true; create.mutate(); }
        }}
      >
        <h2 className={styles.title}>Quick task</h2>
        <label className={ui.sectionLabel} htmlFor="quick-task-title">Title</label>
        <input id="quick-task-title" data-testid="quick-task-title" ref={titleRef} className={ui.input} maxLength={80}
          value={title} disabled={create.isPending} onChange={(e) => setTitle(e.target.value)} aria-describedby="quick-task-title-count" />
        <p id="quick-task-title-count" className={styles.muted}>{title.length}/80 — required</p>
        <label className={ui.sectionLabel} htmlFor="quick-task-words">Your words</label>
        <textarea id="quick-task-words" data-testid="quick-task-words" className={ui.textarea} rows={5} value={words}
          disabled={create.isPending} onChange={(e) => setWords(e.target.value)}
          placeholder="The small task, in your own words. The engineer plans from them verbatim." />
        <fieldset className={styles.roleModels} data-testid="quick-task-role-models">
          <legend className={ui.sectionLabel}>Engineer model and effort</legend>
          <SeatPickHead />
          <SeatPickRow role="engineer" testIdPrefix="quick-task" options={options} model={model} effort={effort}
            disabled={create.isPending} onModel={setPicked} onEffort={setEffortPick} />
        </fieldset>
        {modelsQ.isError ? (
          <p className={styles.muted} role="alert" data-testid="quick-task-models-error">
            Could not load the model catalog; the engineer runs on the board's default.
          </p>
        ) : null}
        <p className={styles.preview} data-testid="quick-task-preview">
          {canSpawn
            ? `Opens a quick task with your words verbatim, starts an engineer on ${model ? modelLabel(model) : "the default engineer model"} at effort ${effort} and assigns it. The engineer writes a plan and one or two criteria you check; it lands in Needs you when handed off.`
            : `The pool cannot start a seat from here${caps?.reason ? ` (${caps.reason})` : ""}, so no quick task is opened.`}
        </p>
        {err ? <p className={ui.banner} role="alert" data-testid="quick-task-error">{err.hint ?? err.message}</p> : null}
        {stranded ? (
          <p className={ui.banner} role="alert" data-testid="quick-task-stranded">
            {stranded.hint}{" "}
            <Link to={`/ticket/${encodeURIComponent(stranded.id)}`} onClick={() => { setStranded(null); onClose(); }}>Open the task</Link>
          </p>
        ) : null}
        <div className={styles.actions}>
          <button type="button" className={ui.button} onClick={onClose} disabled={create.isPending}>Cancel</button>
          <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!ready || create.isPending}
            data-testid="quick-task-create">
            {create.isPending ? "Starting…" : "Open and start the engineer"}
          </button>
        </div>
      </form>
    </div>, document.body,
  );
}
