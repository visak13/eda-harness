import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAdminSettings, putAdminSettings } from "../../api/admin";
import type { SettingRow, SettingValue } from "../../api/admin";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done, SettingField, formValue, toPut } from "./shared";
import { CapacityPanel } from "./Services";

// Admin → Settings (design §4.8): EVERY registry group rendered from GET /v1/admin/settings metadata — no
// field list lives in the SPA. Env-set values are read-only with the reason, secrets write-only and masked,
// each field carries its doc line; a save names the services to restart (the Admin restart banner).

export function SettingsTab({ onRestartRequired }: { onRestartRequired: (services: string[]) => void }): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "settings"], queryFn: getAdminSettings, retry: false });
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [cleared, setCleared] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const rows = useMemo(() => new Map((q.data?.groups ?? []).flatMap((g) => g.settings.map((s) => [s.key, s] as const))), [q.data]);
  useEffect(() => { setDraft({}); setCleared(new Set()); }, [q.data]);

  const save = useMutation({
    mutationFn: (values: Record<string, SettingValue>) => putAdminSettings(values),
    onSuccess: ({ value }) => {
      onRestartRequired(value.restart_required);
      void qc.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
  });

  const dirtyKeys = [...Object.keys(draft), ...cleared];
  function submit() {
    const values: Record<string, SettingValue> = {};
    for (const [k, v] of Object.entries(draft)) {
      const s = rows.get(k);
      if (!s) continue;
      if (s.secret && v === "") continue; // untouched write-only field
      values[k] = toPut(s, v);
    }
    for (const k of cleared) values[k] = null;
    if (Object.keys(values).length) save.mutate(values);
  }

  const match = (s: SettingRow) => !filter || `${s.key} ${s.env} ${s.doc}`.toLowerCase().includes(filter.toLowerCase());
  const total = rows.size;

  return (
    <div className={styles.panel} data-testid="admin-settings">
      <div className={styles.cardHead}>
        <p className={ui.empty}>
          {total} settings from the registry{q.data ? <> · written to <code>{q.data.config_file}</code></> : null}. The environment wins over the file, so a value the environment sets is read-only here. Secrets are write-only.
        </p>
        <div className={styles.row}>
          <input className={ui.input} placeholder="Filter settings" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter settings" data-testid="settings-filter" />
          <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} data-testid="admin-settings-save"
            disabled={!dirtyKeys.length || save.isPending} onClick={submit}>
            {save.isPending ? "Saving…" : dirtyKeys.length ? `Save ${dirtyKeys.length} change${dirtyKeys.length > 1 ? "s" : ""}` : "Save"}
          </button>
        </div>
      </div>
      <AdminError error={q.error} testid="admin-settings-error" />
      <AdminError error={save.error} testid="admin-settings-save-error" />
      <Done text={save.isSuccess && !dirtyKeys.length ? (save.data.value.restart_required.length
        ? `Saved. Restart ${save.data.value.restart_required.join(", ")} to apply.` : "Saved; applies without a restart.") : null} testid="admin-settings-saved" />
      {(q.data?.groups ?? []).map((g) => {
        const shown = g.settings.filter(match);
        if (!shown.length) return null;
        return (
          <details className={styles.card} key={g.group} open={Boolean(filter) || undefined} data-testid={`settings-group-${g.group}`}>
            <summary className={styles.cardTitle}>{g.group} <span className={styles.usage}>({g.settings.length})</span></summary>
            {shown.map((s) => (
              <SettingField key={s.key} s={s}
                value={cleared.has(s.key) ? (s.type === "bool" ? false : "") : draft[s.key] ?? formValue(s)}
                onChange={(v) => { setCleared((c) => { const n = new Set(c); n.delete(s.key); return n; }); setDraft((d) => ({ ...d, [s.key]: v })); }}
                onReset={() => { setDraft((d) => { const n = { ...d }; delete n[s.key]; return n; }); setCleared((c) => new Set(c).add(s.key)); }} />
            ))}
          </details>
        );
      })}
      {q.data ? (
        <details className={styles.card} data-testid="settings-group-capacity">
          <summary className={styles.cardTitle}>Capacity</summary>
          <p className={styles.fieldDoc}>The pool's shell caps per capacity class (builder, planner; checker counts toward the total only) and per role, as on Services.</p>
          <CapacityPanel />
        </details>
      ) : null}
    </div>
  );
}
