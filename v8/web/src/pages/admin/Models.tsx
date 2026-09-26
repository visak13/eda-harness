import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAdminModels, putAdminModels, testSpawnModel } from "../../api/admin";
import type { AdminModelsView, ModelEntry, ModelsCatalogIn } from "../../api/admin";
import { modelLabel } from "../../api/seats";
import { Avatar, ProviderIcon } from "../../components/Avatar";
import { EFFORTS } from "../../components/SeatPicks";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done } from "./shared";

// Admin → Seats & models → Models (S12 s-32035a77da, design §4.14(a); contract m-62fc5b54f9). The catalog
// in the data dir: every entry names its harness and provider (no id-prefix routing), its context window
// and its effort cap. Only entries of the harnesses selected at init show (§4.11); hidden entries are kept
// on every save because PUT replaces the whole catalog. `role_models[role][0]` is the role's default.

const PROVIDERS = ["anthropic", "openai", "openrouter", "google", "groq", "mistral", "deepseek", "xai", "ollama"];

interface Draft { id: string; harness: string; provider: string; context_window: string; effort_cap: string }
const EMPTY: Draft = { id: "", harness: "", provider: "", context_window: "", effort_cap: "" };

function draftOf(id: string, e: ModelEntry): Draft {
  return { id, harness: e.harness, provider: e.provider ?? "", context_window: e.context_window ? String(e.context_window) : "", effort_cap: e.effort_cap ?? "" };
}

/** The entry a draft saves; fields the form does not edit (auto_compact, future keys) are kept. */
function entryOf(d: Draft, prev?: ModelEntry): ModelEntry {
  const cw = Number(d.context_window);
  return { ...prev, harness: d.harness, provider: d.provider.trim(), context_window: d.context_window.trim() && Number.isFinite(cw) ? cw : null, effort_cap: d.effort_cap || null };
}

function catalogOf(v: AdminModelsView): ModelsCatalogIn {
  return { models: v.models, role_models: v.role_models };
}

export function ModelsEditor(): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "models"], queryFn: getAdminModels, retry: false });
  const save = useMutation({
    mutationFn: (body: ModelsCatalogIn) => putAdminModels(body),
    onSuccess: ({ value }) => {
      qc.setQueryData(["admin", "models"], value);
      void qc.invalidateQueries({ queryKey: ["models"] }); // New Epic / Models… / Spawn seat read GET /v1/models
    },
  });
  const data = q.data;
  const selected = data?.selected ?? [];
  const visible = useMemo(() => Object.entries(data?.models ?? {}).filter(([, e]) => selected.includes(e.harness)), [data, selected]);
  const hidden = Object.keys(data?.models ?? {}).length - visible.length;
  const rolesOf = (id: string) => Object.entries(data?.role_models ?? {}).filter(([, ids]) => ids.includes(id)).map(([r, ids]) => (ids[0] === id ? `${r} (default)` : r));

  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [lastDone, setLastDone] = useState<string | null>(null);

  const submitDraft = () => {
    if (!data || !draft) return;
    const id = draft.id.trim();
    const body = catalogOf(data);
    const models = { ...body.models, [id]: entryOf(draft, body.models[editing ?? id]) };
    save.mutate({ models, role_models: body.role_models }, {
      onSuccess: () => { setLastDone(editing ? `Saved ${id}.` : `Added ${id}. Tick it under a role below to use it.`); setDraft(null); setEditing(null); },
    });
  };
  const remove = (id: string) => {
    if (!data) return;
    const models = { ...data.models };
    delete models[id];
    const role_models = Object.fromEntries(Object.entries(data.role_models).map(([r, ids]) => [r, ids.filter((x) => x !== id)]));
    save.mutate({ models, role_models }, { onSuccess: () => setLastDone(`Removed ${id}.`) });
  };

  return (
    <>
      <section className={styles.card} data-testid="models-editor">
        <div className={styles.cardHead}>
          <h2 className={styles.cardTitle}>Models</h2>
          <button type="button" className={`${ui.button} ${styles.small}`} data-testid="model-add" disabled={!data || !selected.length}
            onClick={() => { setEditing(null); setDraft({ ...EMPTY, harness: selected.includes("pi") ? "pi" : selected[0] ?? "" }); setLastDone(null); }}>
            Add a model
          </button>
        </div>
        <p className={styles.fieldDoc}>Each model names the harness that runs it and its provider. Only models of the selected harnesses ({selected.join(", ") || "none"}) are listed.</p>
        <AdminError error={q.error} testid="models-load-error" />
        {data?.warnings.length ? (
          <div className={ui.banner} role="status" data-testid="models-warnings">
            {data.warnings.map((w) => <div key={w}>{w}</div>)}
          </div>
        ) : null}
        {q.isLoading ? <p className={ui.empty}>Loading…</p> : null}
        {data ? (
          <div className={styles.tableWrap}>
            <table className={styles.table} data-testid="models-table">
              <thead>
                <tr><th>Model</th><th>Harness</th><th>Provider</th><th>Window</th><th>Effort cap</th><th>Roles</th><th /></tr>
              </thead>
              <tbody>
                {visible.map(([id, e]) => (
                  <tr key={id} data-testid={`model-row-${id}`}>
                    <td><span className={styles.row}><ProviderIcon harness={e.harness} /><strong>{modelLabel(id)}</strong>{modelLabel(id) !== id ? <code className={styles.usage}>{id}</code> : null}</span></td>
                    <td>{e.harness}</td>
                    <td>{e.provider || "—"}</td>
                    <td>{e.context_window ? e.context_window.toLocaleString() : "—"}</td>
                    <td>{e.effort_cap ?? "none"}</td>
                    <td className={styles.usage}>{rolesOf(id).join(", ") || "not in a role"}</td>
                    <td>
                      <div className={styles.actions}>
                        <button type="button" className={`${ui.button} ${styles.small}`} data-testid={`model-edit-${id}`}
                          onClick={() => { setEditing(id); setDraft(draftOf(id, e)); setLastDone(null); }}>Edit</button>
                        <button type="button" className={`${ui.button} ${styles.small}`} data-testid={`model-remove-${id}`} disabled={save.isPending}
                          onClick={() => remove(id)}>Remove</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!visible.length ? <tr><td colSpan={7} className={ui.empty}>No models for the selected harnesses.</td></tr> : null}
              </tbody>
            </table>
          </div>
        ) : null}
        {hidden > 0 ? <p className={styles.usage} data-testid="models-hidden">{hidden} model{hidden === 1 ? "" : "s"} of unselected harnesses {hidden === 1 ? "is" : "are"} hidden and kept.</p> : null}
        {draft ? (
          <ModelForm draft={draft} editing={editing} harnesses={selected} pending={save.isPending} taken={Object.keys(data?.models ?? {})}
            onChange={setDraft} onCancel={() => { setDraft(null); setEditing(null); save.reset(); }} onSubmit={submitDraft} />
        ) : null}
        <AdminError error={save.error} testid="models-save-error" />
        <Done text={lastDone} testid="models-saved" />
      </section>
      {data ? <RoleModels data={data} visibleIds={visible.map(([id]) => id)} onSave={(role_models) => save.mutate({ models: data.models, role_models }, { onSuccess: () => setLastDone("Saved the role models.") })} pending={save.isPending} /> : null}
      {data ? <TestSpawn data={data} visibleIds={visible.map(([id]) => id)} /> : null}
    </>
  );
}

function ModelForm({ draft, editing, harnesses, pending, taken, onChange, onCancel, onSubmit }: {
  draft: Draft; editing: string | null; harnesses: string[]; pending: boolean; taken: string[];
  onChange: (d: Draft) => void; onCancel: () => void; onSubmit: () => void;
}): React.JSX.Element {
  const set = (k: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => onChange({ ...draft, [k]: e.target.value });
  const id = draft.id.trim();
  const clash = !editing && taken.includes(id);
  const invalid = !id || !draft.harness || !draft.provider.trim() || clash;
  return (
    <form className={styles.notice} data-testid="model-form" onSubmit={(e) => { e.preventDefault(); if (!invalid) onSubmit(); }}>
      <strong>{editing ? `Edit ${editing}` : "Add a model"}</strong>
      <div className={styles.capGrid}>
        <label className={styles.capCell}>
          <span className={styles.usage}>Model id</span>
          <input className={`${ui.input} ${styles.wide}`} value={draft.id} onChange={set("id")} disabled={Boolean(editing)} placeholder="e.g. openrouter/qwen3-coder" data-testid="model-form-id" />
        </label>
        <label className={styles.capCell}>
          <span className={styles.usage}>Harness</span>
          <select className={`${ui.select} ${styles.wide}`} value={draft.harness} onChange={set("harness")} data-testid="model-form-harness">
            {harnesses.map((h) => <option key={h} value={h}>{h}</option>)}
          </select>
        </label>
        <label className={styles.capCell}>
          <span className={styles.usage}>Provider</span>
          <input className={`${ui.input} ${styles.wide}`} list="model-providers" value={draft.provider} onChange={set("provider")} placeholder="e.g. openrouter" data-testid="model-form-provider" />
          <datalist id="model-providers">{PROVIDERS.map((p) => <option key={p} value={p} />)}</datalist>
        </label>
        <label className={styles.capCell}>
          <span className={styles.usage}>Context window (tokens)</span>
          <input className={`${ui.input} ${styles.wide}`} type="number" min={1} value={draft.context_window} onChange={set("context_window")} placeholder="optional" data-testid="model-form-window" />
        </label>
        <label className={styles.capCell}>
          <span className={styles.usage}>Effort cap</span>
          <select className={`${ui.select} ${styles.wide}`} value={draft.effort_cap} onChange={set("effort_cap")} data-testid="model-form-cap">
            <option value="">none (high allowed)</option>
            {EFFORTS.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        </label>
      </div>
      {clash ? <p className={styles.fieldNote} data-testid="model-form-clash">{id} is already in the catalog; edit it instead.</p> : null}
      {draft.harness === "pi" ? <p className={styles.usage}>Pi runs any provider/model. The provider's API key comes from its secret setting in Admin → Settings.</p> : null}
      <div className={styles.row}>
        <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={invalid || pending} data-testid="model-form-save">
          {pending ? "Saving…" : editing ? "Save model" : "Add model"}
        </button>
        <button type="button" className={ui.button} onClick={onCancel} data-testid="model-form-cancel">Cancel</button>
      </div>
    </form>
  );
}

/** Per-role catalogs and defaults, edited together and saved in one PUT. */
function RoleModels({ data, visibleIds, onSave, pending }: {
  data: AdminModelsView; visibleIds: string[]; onSave: (rm: Record<string, string[]>) => void; pending: boolean;
}): React.JSX.Element {
  const [rm, setRm] = useState(data.role_models);
  useEffect(() => setRm(data.role_models), [data.role_models]);
  const dirty = JSON.stringify(rm) !== JSON.stringify(data.role_models);
  const toggle = (role: string, id: string, on: boolean) =>
    setRm((cur) => ({ ...cur, [role]: on ? [...(cur[role] ?? []), id] : (cur[role] ?? []).filter((x) => x !== id) }));
  const setDefault = (role: string, id: string) => setRm((cur) => ({ ...cur, [role]: [id, ...(cur[role] ?? []).filter((x) => x !== id)] }));
  return (
    <section className={styles.card} data-testid="role-models">
      <h2 className={styles.cardTitle}>Models per role</h2>
      <p className={styles.fieldDoc}>Tick the models each role may run on and pick its default. The New Epic dialog offers exactly these.</p>
      {Object.keys(rm).map((role) => {
        const ids = rm[role] ?? [];
        return (
          <div key={role} className={styles.field} data-testid={`role-models-${role}`}>
            <div className={styles.fieldHead}>
              <Avatar id={role} size={24} />
              <span className={`${styles.fieldKey} ${styles.capitalize}`}>{role}</span>
              <label className={styles.row}>
                <span className={styles.usage}>Default</span>
                <select className={ui.select} value={ids[0] ?? ""} disabled={!ids.length} onChange={(e) => setDefault(role, e.target.value)} data-testid={`role-default-${role}`}>
                  {ids.map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
                </select>
              </label>
              {!ids.length ? <span className={styles.fieldNote}>No model: this role runs on the board's fallback.</span> : null}
            </div>
            <div className={styles.row}>
              {visibleIds.map((id) => (
                <label key={id} className={ids.includes(id) ? ui.chip + " " + ui.active : ui.chip} data-testid={`role-pick-${role}-${id}`}>
                  <input type="checkbox" checked={ids.includes(id)} onChange={(e) => toggle(role, id, e.target.checked)} data-testid={`role-pick-${role}-${id}-input`} />
                  {modelLabel(id)}
                </label>
              ))}
            </div>
          </div>
        );
      })}
      <div className={styles.row}>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!dirty || pending} onClick={() => onSave(rm)} data-testid="role-models-save">
          {pending ? "Saving…" : "Save role models"}
        </button>
        {dirty ? <button type="button" className={ui.button} onClick={() => setRm(data.role_models)} data-testid="role-models-reset">Undo changes</button> : null}
      </div>
    </section>
  );
}

/** Run a stub prompt on a private seat of one model: proves the harness, provider and credential. */
function TestSpawn({ data, visibleIds }: { data: AdminModelsView; visibleIds: string[] }): React.JSX.Element {
  const roles = Object.keys(data.role_models);
  const [model, setModel] = useState("");
  const [role, setRole] = useState("");
  const [effort, setEffort] = useState("");
  const m = visibleIds.includes(model) ? model : visibleIds[0] ?? "";
  const r = roles.includes(role) ? role : roles[0] ?? "engineer";
  const run = useMutation({ mutationFn: () => testSpawnModel({ model: m, role: r, ...(effort ? { effort } : {}) }) });
  return (
    <section className={styles.card} data-testid="test-spawn">
      <h2 className={styles.cardTitle}>Test spawn</h2>
      <p className={styles.fieldDoc}>Runs a short stub prompt on a private seat of this model and shows its reply. No ticket is touched.</p>
      <div className={styles.row}>
        <select className={ui.select} value={m} onChange={(e) => { setModel(e.target.value); run.reset(); }} data-testid="test-spawn-model">
          {visibleIds.map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
        </select>
        <select className={ui.select} value={r} onChange={(e) => setRole(e.target.value)} data-testid="test-spawn-role">
          {roles.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
        <select className={ui.select} value={effort} onChange={(e) => setEffort(e.target.value)} data-testid="test-spawn-effort">
          <option value="">default effort</option>
          {EFFORTS.map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!m || run.isPending} onClick={() => run.mutate()} data-testid="test-spawn-run">
          {run.isPending ? "Running…" : "Test spawn"}
        </button>
      </div>
      {run.isPending ? <p className={ui.empty} role="status">Starting a private {data.models[m]?.harness ?? ""} seat and waiting for its reply…</p> : null}
      <AdminError error={run.error} testid="test-spawn-error" />
      {run.data ? (
        <div className={styles.secret} data-testid="test-spawn-result">
          <span className={styles.secretLabel}>{run.data.value.harness} · {run.data.value.provider} replied</span>
          <code className={styles.secretValue} data-testid="test-spawn-reply">{run.data.value.reply}</code>
        </div>
      ) : null}
    </section>
  );
}
