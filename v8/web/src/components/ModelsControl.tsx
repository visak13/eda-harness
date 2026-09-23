import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { choiceFromTags, getTicket, setTicketTags, withChoiceTags } from "../api/endpoints";
import { getModels } from "../api/seats";
import type { ModelCatalog } from "../api/types";
import { BoardApiError } from "../api/client";
import { clampEffort, SeatPickHead, SeatPickRow, type Effort } from "./SeatPicks";
import ui from "./ui.module.css";
import styles from "./ModelsControl.module.css";

// S-UI (owner m-ec5a9b86c5 "the models is being printed here and taking up valuable space when in
// fact it could be an action in the menu where you could choose/switch models"): Actions → Models…
// on the epic page and on every story page. It shows each role's current model and effort (read from
// the EPIC's tags, the same rule the board's seat_choice uses) and switches them: Save rewrites the
// epic's `model:<role>=` / `seat-effort:<role>=` tags (PATCH /v1/tickets/{epic} tags; the owner or the
// architect may). Only later spawns read the tags — a seat already running keeps its model.

export function ModelsControl({ epicId }: { epicId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const modelsQ = useQuery({ queryKey: ["models"], queryFn: getModels, retry: false });
  const epicQ = useQuery({ queryKey: ["ticket-record", epicId], queryFn: () => getTicket(epicId), retry: false });
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [efforts, setEfforts] = useState<Record<string, Effort>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const catalog = modelsQ.data as ModelCatalog | undefined;
  const tags = epicQ.data?.tags ?? [];
  const current = catalog ? choiceFromTags(tags, catalog) : null;
  const roles = Object.keys(catalog?.roles ?? {});
  const roleModels = Object.fromEntries(roles.map((r) => [r, picks[r] ?? current?.roleModels[r] ?? ""]));
  const roleEfforts = Object.fromEntries(roles.map((r) =>
    [r, clampEffort(roleModels[r], efforts[r] ?? (current?.roleEfforts[r] as Effort | undefined) ?? "medium")]));
  const dirty = roles.some((r) => roleModels[r] !== current?.roleModels[r]
    || roleEfforts[r] !== clampEffort(current?.roleModels[r], (current?.roleEfforts[r] ?? "medium") as Effort));

  const save = useMutation({
    mutationFn: () => setTicketTags(epicId, withChoiceTags(tags, { roleModels, roleEfforts })),
    onSuccess: (res) => {
      setPicks({}); setEfforts({});
      setSaved(res.hint || "Saved. The next seat spawned for each role runs on these; running seats keep theirs.");
      void qc.invalidateQueries({ queryKey: ["ticket-record", epicId] });
      void qc.invalidateQueries({ queryKey: ["epic", epicId] });
    },
  });
  const err = (save.error ?? modelsQ.error ?? epicQ.error) as BoardApiError | Error | null;

  return (
    <div className={styles.models} data-testid="models-dialog" role="group" aria-label={`Models for ${epicId}`}>
      {modelsQ.isPending || epicQ.isPending ? <p className={ui.empty}>Loading models…</p> : null}
      {roles.length ? <SeatPickHead /> : null}
      {roles.map((r) => (
        <SeatPickRow key={r} role={r} testIdPrefix="models" options={catalog?.roles[r] ?? []}
          model={roleModels[r]} effort={roleEfforts[r]} disabled={save.isPending}
          onModel={(id) => { setSaved(null); setPicks((p) => ({ ...p, [r]: id })); }}
          onEffort={(e) => { setSaved(null); setEfforts((p) => ({ ...p, [r]: e })); }} />
      ))}
      <p className={styles.note}>
        Applies to the next seat spawned for each role on {epicId}; a seat already running keeps its model.
        Claude seats are capped at effort medium.
      </p>
      {err ? <p className={ui.banner} role="alert" data-testid="models-error">{(err as BoardApiError).hint ?? err.message}</p> : null}
      {saved ? <p className={styles.note} role="status" data-testid="models-saved">{saved}</p> : null}
      <div className={styles.actions}>
        <button type="button" className={ui.button} disabled={!dirty || save.isPending}
          onClick={() => { setPicks({}); setEfforts({}); }}>Reset</button>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!dirty || save.isPending || !catalog}
          onClick={() => save.mutate()} data-testid="models-save">
          {save.isPending ? "Saving…" : "Save models"}
        </button>
      </div>
    </div>
  );
}
