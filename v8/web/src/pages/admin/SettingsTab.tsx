import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAdminSettings, putAdminSettings } from "../../api/admin";
import type { SettingRow, SettingValue } from "../../api/admin";
import { PRODUCT_NAME } from "../../brand";
import { Icon } from "../../components/Icon";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, CopyButton, Done, SettingField, Toggle, formValue, toPut } from "./shared";

// Admin → Settings (design §4.8): the registry's groups rendered from GET /v1/admin/settings metadata — no
// field list lives in the SPA. t-5dd0cc18ea (owner m-b9c54cb63b): plain words first. Basic settings show by
// default and "Show advanced" adds the rest (internal keys never reach the SPA); each field renders by its
// registry type and choices; the config path sits behind "Show where". Capacity lives on Services only.

export function SettingsTab({ onRestartRequired }: { onRestartRequired: (services: string[]) => void }): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "settings"], queryFn: getAdminSettings, retry: false });
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [cleared, setCleared] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [where, setWhere] = useState(false);
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

  const inTier = (s: SettingRow) => advanced || s.tier === "basic";
  const match = (s: SettingRow) => !filter || `${s.label ?? ""} ${s.help ?? ""} ${s.key} ${s.env} ${s.doc}`.toLowerCase().includes(filter.toLowerCase());
  const shownCount = [...rows.values()].filter(inTier).length;

  return (
    <div className={styles.panel} data-testid="admin-settings">
      <div className={styles.cardHead}>
        <div>
          <p className={ui.empty} data-testid="settings-header">
            Saved in your {PRODUCT_NAME} config file. A value set by the environment is locked here.{" "}
            <button type="button" className={styles.linkButton} aria-expanded={where} onClick={() => setWhere((w) => !w)} data-testid="settings-show-where">
              {where ? "Hide where" : "Show where"}
            </button>
          </p>
          {where && q.data ? (
            <div className={styles.row} data-testid="settings-where">
              <code className={ui.idMono} data-testid="settings-config-path">{q.data.config_file}</code>
              <CopyButton text={q.data.config_file} testid="settings-config-path-copy" />
            </div>
          ) : null}
        </div>
        <div className={styles.row}>
          <Toggle checked={advanced} onChange={setAdvanced} label="Show advanced" testid="settings-show-advanced" />
          <input className={ui.input} placeholder="Filter settings" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter settings" data-testid="settings-filter" />
          <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} data-testid="admin-settings-save"
            disabled={!dirtyKeys.length || save.isPending} onClick={submit}>
            {save.isPending ? "Saving…" : dirtyKeys.length ? `Save ${dirtyKeys.length} change${dirtyKeys.length > 1 ? "s" : ""}` : "Save"}
          </button>
        </div>
      </div>
      <p className={styles.fieldDoc} data-testid="settings-count">
        {advanced ? `All ${shownCount} settings.` : `The ${shownCount} settings most people change. Turn on Show advanced for the rest.`}
      </p>
      <AdminError error={q.error} testid="admin-settings-error" />
      <AdminError error={save.error} testid="admin-settings-save-error" />
      <Done text={save.isSuccess && !dirtyKeys.length ? (save.data.value.restart_required.length
        ? `Saved. Restart ${save.data.value.restart_required.join(", ")} to apply.` : "Saved; applies without a restart.") : null} testid="admin-settings-saved" />
      {(q.data?.groups ?? []).map((g) => {
        const shown = g.settings.filter((s) => inTier(s) && match(s));
        if (!shown.length) return null;
        return (
          <details className={`${styles.card} ${styles.disclosure}`} key={g.group} open={Boolean(filter) || !advanced || undefined} data-testid={`settings-group-${g.group}`}>
            <summary className={styles.cardTitle}><Icon name="chevron" />{g.group} <span className={styles.usage}>({shown.length})</span></summary>
            {shown.map((s) => (
              <SettingField key={s.key} s={s}
                value={cleared.has(s.key) ? (s.type === "bool" ? false : "") : draft[s.key] ?? formValue(s)}
                onChange={(v) => { setCleared((c) => { const n = new Set(c); n.delete(s.key); return n; }); setDraft((d) => ({ ...d, [s.key]: v })); }}
                onReset={() => { setDraft((d) => { const n = { ...d }; delete n[s.key]; return n; }); setCleared((c) => new Set(c).add(s.key)); }} />
            ))}
          </details>
        );
      })}
    </div>
  );
}
