import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { createEpic, type EpicSeatChoice } from "../api/endpoints";
import { getModels, getPoolCapabilities, modelLabel, spawnSeat } from "../api/seats";
import type { ModelCatalog, PoolCapabilities } from "../api/types";
import { BoardApiError } from "../api/client";
import ui from "./ui.module.css";
import styles from "./NewEpicDialog.module.css";

// Human #22 (2026-09-10): the header "New epic" button was a plate artifact with no handler. It now
// opens this dialog — the owner card's step 1 without a shell: the words go to the board VERBATIM
// (POST /v1/tickets kind=epic; the board keeps them in `words` and derives the short title, ruling
// #32), then, ONLY when the box is ticked and the pool can spawn, role=architect is spawned on the
// new epic (POST /v1/sessions/spawn). The preview says exactly what will happen and who is woken
// before the reader confirms; the board's hints show verbatim; success navigates to the epic's page.
//
// Owner m-2d7ef9243d / m-3238155d2e (2026-09-17): the owner chooses the seat MODEL and EFFORT for
// every seat of the epic HERE, before any launch — sent as seat-model:/seat-effort: tags on the epic
// (edp8/seat_choice.py) so every later spawn inherits them — and creating an epic never forces a
// spawn: the box is UNTICKED by default. Claude effort is capped at medium fleet-wide (ruling
// 2026-08-04): a Claude seat asked for high runs at medium, and the dialog says so.
//
// S-ROLES (design-34bf11cc07 §4.1, owner m-bba708e10e): the model is chosen PER ROLE — one select per
// role of the models.json catalog (GET /v1/models), prefilled with each role's default, sent as
// `model:<role>=<id>` tags. A GPT id runs on the codex seat, a Claude id on the Claude seat.

export const EFFORTS = ["low", "medium", "high"] as const;
export type Effort = (typeof EFFORTS)[number];

export function NewEpicDialog({ open, onClose }: { open: boolean; onClose: () => void }): React.JSX.Element | null {
  const [words, setWords] = useState("");
  const [title, setTitle] = useState("");
  const committed = useRef<{ id: string; hint: string; choice: EpicSeatChoice } | null>(null);
  const busy = useRef(false);
  const panelRef = useRef<HTMLFormElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const [spawn, setSpawn] = useState(false);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [effort, setEffort] = useState<Effort>("medium");
  const modelsQ = useQuery({ queryKey: ["models"], queryFn: getModels, retry: false, enabled: open });
  const catalog = modelsQ.data as ModelCatalog | undefined;
  const roles = Object.keys(catalog?.roles ?? {});
  // every catalog role's pick: the owner's choice, else the role's default (first catalog entry)
  const roleModels: Record<string, string> = Object.fromEntries(
    roles.map((r) => [r, picks[r] ?? catalog?.defaults[r] ?? ""]));
  const effectiveEffort: Effort = effort;
  const anyClaude = Object.values(roleModels).some((m) => m.startsWith("claude"));
  const [done, setDone] = useState<{ id: string; hint: string; spawnHint: string | null } | null>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const titleRef = useRef<HTMLInputElement>(null);
  const capsQ = useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false, enabled: open });
  const caps = capsQ.data as PoolCapabilities | undefined;
  const canSpawn = Boolean(caps?.spawn);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    const siblings = Array.from(document.body.children).filter((el): el is HTMLElement => el instanceof HTMLElement && !el.contains(panelRef.current));
    const previousInert = siblings.map((el) => el.inert);
    siblings.forEach((el) => { el.inert = true; });
    document.body.style.overflow = "hidden";
    titleRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); if (!busy.current) closeRef.current(); }
      if (e.key !== "Tab") return;
      const items = Array.from(panelRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])') ?? []);
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      siblings.forEach((el, i) => { el.inert = previousInert[i]; });
      document.body.style.overflow = previousOverflow;
      opener?.focus();
    };
  }, [open]);

  const create = useMutation({
    mutationFn: async () => {
      const choice = committed.current?.choice ?? { roleModels, effort: effectiveEffort };
      if (!committed.current) {
        const made = await createEpic(words, choice, title);
        committed.current = { id: made.value.id, hint: made.hint, choice };
      }
      const made = committed.current;
      setDone({ id: made.id, hint: made.hint, spawnHint: null });
      let spawnHint: string | null = null;
      if (spawn && canSpawn) {
        // the same choice rides the spawn body, so the architect runs on it even on a board that
        // stored the tags but resolves nothing (belt and braces; the board's resolution is the same)
        const res = await spawnSeat("architect", `architect.${made.id}`, made.id,
          { model: choice.roleModels.architect ?? null, effort: choice.effort });
        spawnHint = res.hint || `Spawned architect.${made.id}.`;
      }
      return { id: made.id, hint: made.hint, spawnHint };
    },
    onSuccess: (res) => {
      setDone(res);
      void qc.invalidateQueries({ queryKey: ["epics", "summary"] });
      void qc.invalidateQueries({ queryKey: ["me", "summary"] });
      void qc.invalidateQueries({ queryKey: ["seats"] });
      setWords(""); setTitle(""); setSpawn(false); setDone(null); setPicks({});
      committed.current = null;
      navigate(`/epic/${encodeURIComponent(res.id)}`);
      onClose();
    },
    onSettled: () => { busy.current = false; },
  });
  const err = create.error as BoardApiError | undefined;

  if (!open) return null;
  const text = words.trim();
  return createPortal(
    <div className={styles.scrim} onMouseDown={(e) => e.target === e.currentTarget && !busy.current && onClose()} data-testid="new-epic-scrim">
      <form
        className={styles.dialog}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="New epic"
        data-testid="new-epic-dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (text && title.trim() && title.trim().length <= 80 && !busy.current) { busy.current = true; create.mutate(); }
        }}
      >
        <h2 className={styles.title}>New epic</h2>
        <label className={ui.sectionLabel} htmlFor="new-epic-title">Title</label>
        <input id="new-epic-title" data-testid="new-epic-title" ref={titleRef} className={ui.input} maxLength={80} value={title} disabled={create.isPending || Boolean(done)} onChange={(e) => setTitle(e.target.value)} aria-describedby="new-epic-title-count" />
        <p id="new-epic-title-count" className={styles.muted}>{title.length}/80 — required</p>
        <label className={ui.sectionLabel} htmlFor="new-epic-words">
          Your words
        </label>
        <textarea
          id="new-epic-words"
          disabled={create.isPending || Boolean(done)}
          className={ui.textarea}
          rows={5}
          value={words}
          onChange={(e) => setWords(e.target.value)}
          placeholder="What you want, in your own words. They are kept verbatim, separately from your title."
          data-testid="new-epic-words"
        />
        <fieldset className={styles.roleModels} data-testid="new-epic-role-models">
          <legend className={ui.sectionLabel}>Model per role</legend>
          {modelsQ.isError ? (
            <p className={styles.muted} role="alert" data-testid="new-epic-models-error">
              Could not load the model catalog; every seat runs on its role's default.
            </p>
          ) : null}
          {roles.map((r) => (
            <label key={r}>
              {r}
              <select
                className={ui.select}
                disabled={create.isPending || Boolean(done)}
                value={roleModels[r]}
                onChange={(e) => setPicks((p) => ({ ...p, [r]: e.target.value }))}
                data-testid={`new-epic-model-${r}`}
              >
                {(catalog?.roles[r] ?? []).map((id) => (
                  <option key={id} value={id}>
                    {modelLabel(id)}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </fieldset>
        <div className={styles.choice} data-testid="new-epic-choice">
          <label>
            Effort
            <select
              className={ui.select}
              disabled={create.isPending || Boolean(done)}
              value={effectiveEffort}
              onChange={(e) => setEffort(e.target.value as Effort)}
              data-testid="new-epic-effort"
            >
              {EFFORTS.map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </label>
        </div>
        {anyClaude && effectiveEffort === "high" ? (
          <p className={styles.muted} data-testid="new-epic-effort-cap">
            Claude seats are capped at effort medium fleet-wide; high applies to the GPT seats only.
          </p>
        ) : null}
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={spawn}
            disabled={!canSpawn || create.isPending || Boolean(done)}
            onChange={(e) => setSpawn(e.target.checked)}
            data-testid="new-epic-spawn"
          />
          Spawn the architect
          {!canSpawn ? <span className={styles.muted}> — {caps?.reason ?? "the pool cannot spawn from here"}</span> : null}
        </label>
        <p className={styles.preview} data-testid="new-epic-preview">
          Creates the epic with your words verbatim and your explicit title. Each role's seats run on
          the model chosen above at effort {effectiveEffort}, unless a spawn names its own model.
          {spawn && canSpawn
            ? " Then spawns role=architect on it (wakes a new architect shell on that model), which designs it and comes back to you with questions on Decisions."
            : " No seat is woken now; spawn the architect later from the epic page."}
        </p>
        {err ? (
          <p className={ui.banner} role="alert" data-testid="new-epic-error">
            {err.hint ?? err.message}
          </p>
        ) : null}
        {done ? (
          <p className={styles.muted} role="status">
            Epic created. {err ? "The architect could not start. Retry uses this same epic." : done.hint} <Link to={`/epic/${encodeURIComponent(done.id)}`} aria-disabled={create.isPending} onClick={(e) => { if (busy.current) { e.preventDefault(); return; } committed.current = null; setDone(null); setTitle(""); setWords(""); setSpawn(false); onClose(); }}>Open existing epic</Link>
          </p>
        ) : null}
        <div className={styles.actions}>
          <button type="button" className={ui.button} onClick={onClose} disabled={create.isPending}>
            {done ? "Close" : "Cancel"}
          </button>
          <button
            type="submit"
            className={`${ui.button} ${ui.buttonPrimary}`}
            disabled={!text || !title.trim() || title.trim().length > 80 || create.isPending || (Boolean(done) && !canSpawn)}
            data-testid="new-epic-create"
          >
            {create.isPending ? "Saving…" : done ? "Retry architect" : spawn && canSpawn ? "Create and spawn the architect" : "Create the epic"}
          </button>
        </div>
      </form>
    </div>, document.body,
  );
}
