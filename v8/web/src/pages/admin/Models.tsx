import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAdminModels, getHarnesses, putAdminModels, testSpawnModel } from "../../api/admin";
import type { AdminModelsView, ModelEntry, ModelsCatalogIn } from "../../api/admin";
import { modelLabel } from "../../api/seats";
import { Avatar, ProviderIcon } from "../../components/Avatar";
import { EFFORTS } from "../../components/SeatPicks";
import { roleLabel } from "../../components/iconPaths";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done } from "./shared";

// Admin → Seats & models → Models (S12 s-32035a77da, design §4.14(a); contract m-62fc5b54f9). The catalog
// in the data dir: every entry names its harness and provider (no id-prefix routing), its context window
// and its effort cap. Only entries of the harnesses selected at init show (§4.11); hidden entries are kept
// on every save because PUT replaces the whole catalog. `role_models[role][0]` is the role's default.

const PROVIDERS = ["anthropic", "openai", "openrouter", "google", "groq", "mistral", "deepseek", "xai", "ollama"];

interface Draft { id: string; harness: string; provider: string; context_window: string; auto_compact: string; effort_cap: string }
const EMPTY: Draft = { id: "", harness: "", provider: "", context_window: "", auto_compact: "", effort_cap: "medium" };
const PROVIDER_RE = /^[A-Za-z0-9_-]+$/;

function draftOf(id: string, e: ModelEntry): Draft {
  const n = (v: unknown) => (typeof v === "number" ? String(v) : "");
  return { id, harness: e.harness, provider: e.provider ?? "", context_window: n(e.context_window), auto_compact: n(e.auto_compact), effort_cap: e.effort_cap ?? "medium" };
}

/** Harnesses that report their own window and compaction (model_catalog.HARNESS_WINDOWS): a blank field
 *  leaves the harness's number in force. */
const HARNESS_WINDOWS = new Set(["codex"]);
const HARNESS_NAME: Record<string, string> = { codex: "Codex" };

/** The entry a draft saves; keys the form does not edit are kept, a blank Codex number is left unset. */
function entryOf(d: Draft, prev?: ModelEntry): ModelEntry {
  const out: ModelEntry = { ...prev, harness: d.harness, provider: d.provider.trim(), context_window: Number(d.context_window), auto_compact: Number(d.auto_compact), effort_cap: d.effort_cap };
  if (HARNESS_WINDOWS.has(d.harness)) {
    if (!d.context_window.trim()) delete out.context_window;
    if (!d.auto_compact.trim()) delete out.auto_compact;
  }
  return out;
}

/** A window/compact cell: the row's own number, else "Codex default (N)" from the harness, else a dash. */
function tokens(own: unknown, harness: string, fallback: number | undefined): string {
  if (typeof own === "number") return own.toLocaleString("en-US");
  if (HARNESS_WINDOWS.has(harness) && typeof fallback === "number") return `${HARNESS_NAME[harness] ?? harness} default (${fallback.toLocaleString("en-US")})`;
  if (HARNESS_WINDOWS.has(harness)) return `${HARNESS_NAME[harness] ?? harness} default`;
  return "—";
}

/** The board's rules (model_catalog.validate), checked before the PUT so the form says what is missing. */
function draftProblem(d: Draft, clash: boolean): string | null {
  const id = d.id.trim();
  const w = Number(d.context_window);
  const c = Number(d.auto_compact);
  if (!id) return "Name the model id.";
  if (clash) return `${id} is already in the catalog; edit it instead.`;
  if (!PROVIDER_RE.test(d.provider.trim())) return "Name the provider: letters, digits, - or _ (e.g. openrouter).";
  const own = HARNESS_WINDOWS.has(d.harness);  // Codex: blank = the harness's own number
  const wSet = !own || d.context_window.trim() !== "";
  const cSet = !own || d.auto_compact.trim() !== "";
  if (wSet && (!Number.isInteger(w) || w <= 0)) return "Give the context window in tokens.";
  if (cSet && (!Number.isInteger(c) || c <= 0 || (wSet && c >= w))) return "Auto-compact must be a token count below the context window.";
  if (d.harness === "claude" && d.effort_cap === "high") return "Claude models are capped at medium or lower.";
  return null;
}

/** t-20f0718990: harnesses the board found NOT installed on this machine (from the live probe); a model
 *  on one of them cannot run, and says so in words wherever it appears. */
function useMissingHarnesses(): Set<string> {
  const q = useQuery({ queryKey: ["admin", "harnesses", "selection"], queryFn: () => getHarnesses(false), retry: false });
  return new Set((q.data?.harnesses ?? []).filter((h) => !h.installed).map((h) => h.harness));
}
const NOT_INSTALLED = "harness not installed: install it (Admin → Integrations → Seat harnesses)";

function catalogOf(v: AdminModelsView): ModelsCatalogIn {
  return { models: v.models, role_models: v.role_models, default_model: v.default_model };
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
  const missing = useMissingHarnesses();
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
  const [blocked, setBlocked] = useState<string | null>(null);
  const remove = (id: string) => {
    if (!data) return;
    const emptied = Object.entries(data.role_models).filter(([, ids]) => ids.length === 1 && ids[0] === id).map(([r]) => r);
    setBlocked(emptied.length ? `${id} is the only model of ${emptied.join(", ")}: add another model to that role before removing it.` : null);
    if (emptied.length) return;
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
            <table className={`${styles.table} ${styles.modelsTable}`} data-testid="models-table">
              <thead>
                <tr><th>Model</th><th>Harness</th><th>Provider</th><th>Window</th><th>Compact at</th><th>Effort cap</th><th>Roles</th><th /></tr>
              </thead>
              <tbody>
                {visible.map(([id, e]) => (
                  <tr key={id} data-testid={`model-row-${id}`}>
                    <td><span className={styles.row}><ProviderIcon harness={e.harness} /><strong>{modelLabel(id)}</strong>{modelLabel(id) !== id ? <code className={styles.usage}>{id}</code> : null}</span></td>
                    <td className={styles.num}>{e.harness}{missing.has(e.harness) ? <div className={styles.fieldNote} data-testid={`model-why-${id}`}>{NOT_INSTALLED}</div> : null}</td>
                    <td className={styles.num}>{e.provider || "—"}</td>
                    <td className={styles.num} data-testid={`model-window-${id}`}>{tokens(e.context_window || undefined, e.harness, data.harness_defaults?.[id]?.context_window)}</td>
                    <td className={styles.num} data-testid={`model-compact-${id}`}>{tokens(e.auto_compact, e.harness, data.harness_defaults?.[id]?.auto_compact)}</td>
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
                {!visible.length ? <tr><td colSpan={8} className={ui.empty}>No models for the selected harnesses.</td></tr> : null}
              </tbody>
            </table>
          </div>
        ) : null}
        {hidden > 0 ? <p className={styles.usage} data-testid="models-hidden">{hidden} model{hidden === 1 ? "" : "s"} of unselected harnesses {hidden === 1 ? "is" : "are"} hidden and kept.</p> : null}
        {draft ? (
          <ModelForm draft={draft} editing={editing} harnesses={selected} pending={save.isPending} taken={Object.keys(data?.models ?? {})}
            onChange={setDraft} onCancel={() => { setDraft(null); setEditing(null); save.reset(); }} onSubmit={submitDraft} />
        ) : null}
        {blocked ? <p className={ui.banner} role="alert" data-testid="models-remove-blocked">{blocked}</p> : null}
        <AdminError error={save.error} testid="models-save-error" />
        <Done text={lastDone} testid="models-saved" />
      </section>
      {data ? <RoleModels data={data} missing={missing} visibleIds={visible.map(([id]) => id)} onSave={(role_models) => save.mutate({ models: data.models, role_models }, { onSuccess: () => setLastDone("Saved the role models.") })} pending={save.isPending} /> : null}
      {data ? <TestSpawn data={data} missing={missing} visibleIds={visible.map(([id]) => id)} /> : null}
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
  const problem = draftProblem(draft, clash);
  const invalid = problem !== null || !draft.harness;
  const touched = Boolean(id || draft.provider || draft.context_window || draft.auto_compact);
  return (
    <form className={styles.notice} data-testid="model-form" onSubmit={(e) => { e.preventDefault(); if (!invalid) onSubmit(); }}>
      <strong>{editing ? `Edit ${editing}` : "Add a model"}</strong>
      <div className={styles.formGrid}>
        <label className={styles.formCell}>
          <span className={styles.usage}>Model id</span>
          <input className={ui.input} value={draft.id} onChange={set("id")} disabled={Boolean(editing)} placeholder="e.g. openrouter/qwen3-coder" data-testid="model-form-id" />
        </label>
        <label className={styles.formCell}>
          <span className={styles.usage}>Harness</span>
          <select className={ui.select} value={draft.harness} onChange={set("harness")} data-testid="model-form-harness">
            {harnesses.map((h) => <option key={h} value={h}>{h}</option>)}
          </select>
        </label>
        <label className={styles.formCell}>
          <span className={styles.usage}>Provider</span>
          <input className={ui.input} list="model-providers" value={draft.provider} onChange={set("provider")} placeholder="e.g. openrouter" data-testid="model-form-provider" />
          <datalist id="model-providers">{PROVIDERS.map((p) => <option key={p} value={p} />)}</datalist>
        </label>
        <label className={styles.formCell}>
          <span className={styles.usage}>Context window (tokens)</span>
          <input className={ui.input} type="number" min={1} value={draft.context_window} onChange={set("context_window")} placeholder={HARNESS_WINDOWS.has(draft.harness) ? `blank = ${HARNESS_NAME[draft.harness] ?? draft.harness} default` : "e.g. 262144"} data-testid="model-form-window" />
        </label>
        <label className={styles.formCell}>
          <span className={styles.usage}>Auto-compact at (tokens)</span>
          <input className={ui.input} type="number" min={1} value={draft.auto_compact} onChange={set("auto_compact")} placeholder={HARNESS_WINDOWS.has(draft.harness) ? `blank = ${HARNESS_NAME[draft.harness] ?? draft.harness} default` : "below the window, e.g. 180000"} data-testid="model-form-compact" />
        </label>
        <label className={styles.formCell}>
          <span className={styles.usage}>Effort cap</span>
          <select className={ui.select} value={draft.effort_cap} onChange={set("effort_cap")} data-testid="model-form-cap">
            {EFFORTS.map((e) => {
              const capped = e === "high" && draft.harness === "claude";
              return <option key={e} value={e} disabled={capped} title={capped ? "Claude models are capped at medium or lower" : undefined}>{e}{capped ? " (not for Claude)" : ""}</option>;
            })}
          </select>
          {draft.harness === "claude" ? <span className={styles.usage} data-testid="model-form-cap-why">high is greyed: Claude models are capped at medium or lower.</span> : null}
        </label>
      </div>
      {problem && (touched || clash) ? <p className={styles.fieldNote} data-testid={clash ? "model-form-clash" : "model-form-problem"}>{problem}</p> : null}
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
function RoleModels({ data, missing, visibleIds, onSave, pending }: {
  data: AdminModelsView; missing: Set<string>; visibleIds: string[]; onSave: (rm: Record<string, string[]>) => void; pending: boolean;
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
              <span className={`${styles.fieldKey} ${styles.capitalize}`}>{roleLabel(role)}</span>
              <label className={styles.row}>
                <span className={styles.usage}>Default</span>
                <select className={ui.select} value={ids[0] ?? ""} disabled={!ids.length} onChange={(e) => setDefault(role, e.target.value)} data-testid={`role-default-${role}`}>
                  {ids.map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
                </select>
              </label>
              {!ids.length ? <span className={styles.fieldNote}>Pick at least one model: the board refuses an empty role.</span> : null}
              {ids.some((id) => !visibleIds.includes(id)) ? <span className={styles.usage} data-testid={`role-hidden-${role}`}>also {ids.filter((id) => !visibleIds.includes(id)).map(modelLabel).join(", ")} (unselected harness)</span> : null}
            </div>
            <div className={styles.row}>
              {visibleIds.map((id) => (
                <label key={id} className={ids.includes(id) ? ui.chip + " " + ui.active : ui.chip} data-testid={`role-pick-${role}-${id}`}>
                  <input type="checkbox" checked={ids.includes(id)} onChange={(e) => toggle(role, id, e.target.checked)} data-testid={`role-pick-${role}-${id}-input`} />
                  {modelLabel(id)}
                  {missing.has(data.models[id]?.harness ?? "") ? <span className={styles.fieldNote}> ({NOT_INSTALLED.split(":")[0]})</span> : null}
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
function TestSpawn({ data, missing, visibleIds }: { data: AdminModelsView; missing: Set<string>; visibleIds: string[] }): React.JSX.Element {
  const [model, setModel] = useState("");
  const [role, setRole] = useState("");
  const [effort, setEffort] = useState("");
  const m = visibleIds.includes(model) ? model : visibleIds[0] ?? "";
  // the board runs a test only for a role whose catalog holds the model
  const roles = Object.keys(data.role_models).filter((x) => data.role_models[x]?.includes(m));
  const r = roles.includes(role) ? role : roles[0] ?? "";
  const run = useMutation({ mutationFn: () => testSpawnModel({ model: m, role: r, ...(effort ? { effort } : {}) }) });
  const harness = data.models[m]?.harness ?? "";
  const cap = data.models[m]?.effort_cap ?? null;
  const RANK: Record<string, number> = { low: 0, medium: 1, high: 2 };
  const overCap = (e: string) => cap !== null && (RANK[e] ?? 0) > (RANK[cap] ?? 2);
  const why = !m ? "No model to test: add one above."
    : missing.has(harness) ? `${m}: ${NOT_INSTALLED}.`
    : !r ? `Add ${m} to a role above first: a test runs as one of the roles that may use it.`
    : effort && overCap(effort) ? `Effort ${effort} is above this model's cap (${cap}).` : null;
  return (
    <section className={styles.card} data-testid="test-spawn">
      <h2 className={styles.cardTitle}>Test spawn</h2>
      <p className={styles.fieldDoc}>Runs a short stub prompt on a private seat of this model and shows its reply. No ticket is touched.</p>
      <div className={styles.row}>
        <select className={ui.select} value={m} onChange={(e) => { setModel(e.target.value); run.reset(); }} data-testid="test-spawn-model">
          {visibleIds.map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
        </select>
        <select className={ui.select} value={r} onChange={(e) => setRole(e.target.value)} data-testid="test-spawn-role">
          {roles.map((x) => <option key={x} value={x}>{roleLabel(x)}</option>)}
        </select>
        <select className={ui.select} value={effort} onChange={(e) => setEffort(e.target.value)} data-testid="test-spawn-effort">
          <option value="">default effort</option>
          {EFFORTS.map((e) => <option key={e} value={e} disabled={overCap(e)} title={overCap(e) ? `above this model's cap (${cap})` : undefined}>{e}{overCap(e) ? " (above cap)" : ""}</option>)}
        </select>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={Boolean(why) || run.isPending} title={why ?? undefined}
          aria-describedby={why ? "test-spawn-why" : undefined} onClick={() => run.mutate()} data-testid="test-spawn-run">
          {run.isPending ? "Running…" : "Test spawn"}
        </button>
      </div>
      {why ? <p id="test-spawn-why" className={styles.fieldNote} data-testid={m && !r && !missing.has(harness) ? "test-spawn-no-role" : "test-spawn-why"}>{why}</p> : null}
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
