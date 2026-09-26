import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getHarnesses, putHarnessSelection } from "../../api/admin";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done } from "./shared";
import { ModelsEditor } from "./Models";

// Seats & models (design §4.11): which harnesses seats run on — claude and codex both optional, at least one
// of them selected — and the Fable adversary risk notice with its one-time acknowledgement when codex is not
// selected. S12: the model catalog editor (Models.tsx) follows the harness choice.

const HARNESSES = ["claude", "codex", "pi"] as const;

/** The harness choice (also the setup wizard's harness step). `onSaved` runs after a successful save.
 * `installedOnly` (the wizard, t-08612be1b0): a harness whose CLI is not on this machine cannot be picked; the
 * row says how to get it instead. */
export function HarnessSelection({ onSaved, onRestartRequired, installedOnly = false }: { onSaved?: () => void; onRestartRequired?: (s: string[]) => void; installedOnly?: boolean }): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "harnesses", "selection"], queryFn: () => getHarnesses(false), retry: false });
  const [picked, setPicked] = useState<string[]>([]);
  const [ack, setAck] = useState(false);
  useEffect(() => { if (q.data) setPicked(q.data.selected); }, [q.data]);
  const save = useMutation({
    mutationFn: () => putHarnessSelection(picked, ack),
    onSuccess: ({ value }) => { onRestartRequired?.(value.restart_required); void qc.invalidateQueries({ queryKey: ["admin", "harnesses"] }); onSaved?.(); },
  });
  const noCodex = !picked.includes("codex");
  const neither = !picked.includes("claude") && !picked.includes("codex");
  const acked = Boolean(q.data?.fable_ack);
  const detected = new Map((q.data?.harnesses ?? []).map((h) => [h.harness, h]));
  // the board's own words (edp8.harness.FABLE_RISK_NOTICE); GET omits them while codex is selected
  const notice = q.data?.fable_notice ?? "Codex is not selected, so the adversary role runs on Fable (claude-fable-5-1). Fable's safety safeguards are strict: an adversarial or security review may be declined or softened. Review its findings before trusting a clean result.";
  return (
    <section className={styles.card} data-testid="harness-selection">
      <h2 className={styles.cardTitle}>Seat harnesses</h2>
      <AdminError error={q.error} testid="harness-selection-error" />
      <div className={styles.row}>
        {HARNESSES.map((h) => {
          const d = detected.get(h);
          // the wizard offers only what is installed; one already picked can still be unticked
          const locked = installedOnly && Boolean(d) && !d?.installed && !picked.includes(h);
          return (
            <label key={h} className={styles.row} data-testid={`pick-${h}`}>
              <input type="checkbox" checked={picked.includes(h)} disabled={locked} data-testid={`pick-${h}-input`}
                onChange={(e) => setPicked((p) => (e.target.checked ? [...p, h] : p.filter((x) => x !== h)))} />
              <strong>{h}</strong>
              <span className={styles.usage} data-testid={`pick-${h}-state`}>{d ? (d.installed ? `installed ${d.version ?? ""}`.trim()
                : installedOnly ? `not installed: Install it in Your tools (back one step), or run heronry prereqs install --only ${h}`
                  : "not found on this machine") : ""}</span>
            </label>
          );
        })}
      </div>
      {neither ? <p className={ui.banner} role="alert" data-testid="harness-neither">Select claude, codex or both: at least one is needed to run seats. Pi can run alongside them.</p> : null}
      {noCodex && !neither ? (
        <div className={styles.notice} data-testid="fable-notice">
          <strong>Adversary risk notice.</strong> {notice}
          {acked ? <p className={styles.usage} data-testid="fable-acked">Acknowledged{q.data?.fable_ack?.by ? ` by ${String(q.data.fable_ack.by)}` : ""}{q.data?.fable_ack?.at ? ` on ${String(q.data.fable_ack.at)}` : ""}.</p> : (
            <label className={styles.row}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="fable-ack" /> I understand; run the adversary on Fable.</label>
          )}
        </div>
      ) : null}
      <div className={styles.row}>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} data-testid="harness-selection-save"
          disabled={save.isPending || neither || (noCodex && !acked && !ack)} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save harnesses"}
        </button>
      </div>
      <AdminError error={save.error} testid="harness-selection-save-error" />
      <Done text={save.isSuccess ? save.data.hint : null} testid="harness-selection-saved" />
    </section>
  );
}

export function SeatsModelsTab({ onRestartRequired }: { onRestartRequired: (services: string[]) => void }): React.JSX.Element {
  return (
    <div className={styles.panel} data-testid="admin-models">
      <HarnessSelection onRestartRequired={onRestartRequired} />
      <ModelsEditor />
    </div>
  );
}
