import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, postJson } from "../../api/client";
import type { ModelCatalog } from "../../api/types";
import { modelLabel } from "../../api/seats";
import type { CapacityClass, RoleDef, Templates, WorkflowDef } from "../../api/workflows";
import { Markdown } from "../../components/Markdown";
import ui from "../../components/ui.module.css";
import styles from "./Design.module.css";
import { DOC_TYPES, EFFORTS, FIELD_HELP, KINDS, NON_AGENT_ROLES, PERMISSION_HELP, ROLE_ID, roleLabel, spawnersOf } from "./model";

// S14 (§4.14(c)-(e)): one role at a time — its model/harness/effort from the S12 catalog, its card (a
// markdown editor with the board's own preview), its tool checklist and its permissions — plus Add role
// from a template. Every field carries a one-line explanation (FIELD_HELP).

export interface RolePanelProps {
  wf: WorkflowDef;
  savedRef: string;
  editable: boolean;
  templates: Templates | undefined;
  catalog: ModelCatalog | undefined;
  selected: string | null;
  onSelect: (id: string) => void;
  onChange: (wf: WorkflowDef) => void;
  errorRoles: Set<string>;
  focusField?: string | null;
}

export function RolePanel(p: RolePanelProps): React.JSX.Element {
  const { wf, editable, selected, onSelect } = p;
  const role = wf.roles.find((r) => r.id === selected) ?? wf.roles.find((r) => !r.human) ?? wf.roles[0];
  const [adding, setAdding] = useState(false);
  return (
    <div className={styles.card} data-testid="design-roles">
      <div className={styles.spread}>
        <h2 className={styles.cardTitle}>Roles</h2>
        {editable ? <button type="button" className={ui.button} data-testid="role-add-open" onClick={() => setAdding((a) => !a)}>{adding ? "Close" : "Add role"}</button> : null}
      </div>
      {adding && editable ? <AddRole {...p} onDone={(id) => { setAdding(false); onSelect(id); }} /> : null}
      <div className={styles.roleChips} role="tablist" aria-label="Roles">
        {wf.roles.map((r) => (
          <button key={r.id} type="button" role="tab" aria-selected={r.id === role?.id}
            className={`${styles.roleChip} ${r.id === role?.id ? styles.roleChipActive : ""} ${p.errorRoles.has(r.id) ? styles.roleChipErr : ""}`}
            data-testid={`role-chip-${r.id}`} onClick={() => onSelect(r.id)}>
            {roleLabel(r)}{r.human ? " · human" : ""}
          </button>
        ))}
      </div>
      {role ? <RoleForm key={role.id} {...p} role={role} /> : null}
    </div>
  );
}

function Help({ k }: { k: string }): React.JSX.Element {
  return <span className={styles.help}>{FIELD_HELP[k]}</span>;
}

function RoleForm({ wf, savedRef, editable, templates, catalog, role, onChange, focusField }: RolePanelProps & { role: RoleDef }): React.JSX.Element {
  const set = (patch: Partial<RoleDef>) =>
    onChange({ ...wf, roles: wf.roles.map((r) => (r.id === role.id ? { ...r, ...patch } : r)) });
  const toggleIn = (list: string[] | null | undefined, v: string, on: boolean) =>
    on ? [...new Set([...(list ?? []), v])] : (list ?? []).filter((x) => x !== v);
  const setSpawnedBy = (spawner: string, on: boolean) =>
    onChange({ ...wf, roles: wf.roles.map((r) => (r.id === spawner ? { ...r, may_spawn: toggleIn(r.may_spawn, role.id, on) } : r)) });
  const setPermission = (name: string, on: boolean) =>
    onChange({ ...wf, permissions: { ...wf.permissions, [name]: toggleIn(wf.permissions[name], role.id, on) } });
  const removeRole = () => onChange({
    ...wf,
    roles: wf.roles.filter((r) => r.id !== role.id).map((r) => ({ ...r, may_spawn: (r.may_spawn ?? []).filter((x) => x !== role.id) })),
    permissions: Object.fromEntries(Object.entries(wf.permissions).map(([k, v]) => [k, v.filter((x) => x !== role.id)])),
  });
  const kernel = new Set(templates?.kernel_tools ?? []);
  const needs = templates?.tool_needs ?? {};
  const models = catalog?.models ?? {};
  const cap = role.model ? models[role.model]?.effort_cap ?? null : null;
  const efforts = cap ? EFFORTS.slice(0, EFFORTS.indexOf(cap) + 1) : EFFORTS;
  const dis = !editable;
  const focusRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focusField) return;
    const el = focusRef.current?.querySelector<HTMLElement>(`[data-field="${focusField}"]`);
    if (el) {
      el.scrollIntoView?.({ block: "center" });
      el.classList.add(styles.flash);
      el.querySelector<HTMLElement>("input,textarea,select,button")?.focus();
      const t = setTimeout(() => el.classList.remove(styles.flash), 2400);
      return () => clearTimeout(t);
    }
  }, [focusField, role.id]);
  const spawners = spawnersOf(wf, role.id);
  const others = wf.roles.filter((r) => r.id !== role.id);
  return (
    <div ref={focusRef} className={styles.card} data-testid={`role-form-${role.id}`}>
      <div className={styles.grid}>
        <label className={styles.field} data-field="label">
          <span className={styles.fieldLabel}>Label</span>
          <input className={ui.input} value={role.label ?? ""} placeholder={role.id} disabled={dis}
            onChange={(e) => set({ label: e.target.value })} data-testid="role-label" />
          <Help k="label" />
        </label>
        {role.human ? (
          <p className={styles.muted}>A human role: people with this role act in the UI. It has no seat, model or card.</p>
        ) : (
          <>
            <label className={styles.field} data-field="model">
              <span className={styles.fieldLabel}>Model</span>
              <select className={ui.select} value={role.model ?? ""} disabled={dis} data-testid="role-model"
                onChange={(e) => {
                  const id = e.target.value || null;
                  set({ model: id, harness: id ? models[id]?.harness ?? null : null, effort: role.effort && id && models[id]?.effort_cap && EFFORTS.indexOf(role.effort) > EFFORTS.indexOf(models[id].effort_cap as string) ? models[id].effort_cap : role.effort });
                }}>
                <option value="">the epic's pick (catalog default)</option>
                {Object.keys(models).sort().map((id) => <option key={id} value={id}>{modelLabel(id)} · {models[id].harness}</option>)}
              </select>
              <span className={styles.help} data-testid="role-harness">Harness: {role.harness ?? (role.model ? models[role.model]?.harness : null) ?? "from the model"} · {FIELD_HELP.model}</span>
            </label>
            <label className={styles.field} data-field="effort">
              <span className={styles.fieldLabel}>Effort</span>
              <select className={ui.select} value={role.effort ?? ""} disabled={dis} data-testid="role-effort"
                onChange={(e) => set({ effort: e.target.value || null })}>
                <option value="">default</option>
                {efforts.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
              <Help k="effort" />
            </label>
            <label className={styles.field} data-field="capacity_class">
              <span className={styles.fieldLabel}>Capacity class</span>
              <select className={ui.select} value={role.capacity_class ?? ""} disabled={dis} data-testid="role-capacity"
                onChange={(e) => set({ capacity_class: (e.target.value || null) as CapacityClass | null })}>
                <option value="">none</option>
                {["builder", "planner", "checker"].map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <Help k="capacity_class" />
            </label>
            <label className={styles.field} data-field="max_concurrent">
              <span className={styles.fieldLabel}>Max concurrent seats</span>
              <input className={ui.input} type="number" value={role.max_concurrent ?? ""} disabled={dis} data-testid="role-max"
                onChange={(e) => set({ max_concurrent: e.target.value === "" ? null : Number(e.target.value) })} />
              <Help k="max_concurrent" />
            </label>
          </>
        )}
      </div>
      {role.human ? null : <CardEditor role={role} savedRef={savedRef} editable={editable} onChange={(card_md) => set({ card_md })} />}
      {role.human ? null : (
        <div className={styles.field} data-field="bundle">
          <span className={styles.fieldLabel}>Tools ({(role.bundle ?? []).length} ticked + {kernel.size} kernel)</span>
          <Help k="bundle" />
          <div className={styles.toolGrid} data-testid="role-tools">
            {(templates?.tools ?? []).map((t) => {
              const isKernel = kernel.has(t.name);
              const need = needs[t.name];
              return (
                <label key={t.name} className={styles.check} title={t.description}>
                  <input type="checkbox" disabled={dis || isKernel} checked={isKernel || (role.bundle ?? []).includes(t.name)}
                    data-testid={`role-tool-${t.name}`} onChange={(e) => set({ bundle: toggleIn(role.bundle, t.name, e.target.checked) })} />
                  <span className={styles.mono}>{t.name}</span>
                  {isKernel ? <span className={styles.badge}>kernel</span> : need ? <span className={styles.badge} title={`needs the ${need[0]} permission`}>needs {need[0]}</span> : null}
                </label>
              );
            })}
          </div>
        </div>
      )}
      <fieldset className={styles.field} data-field="permissions">
        <legend className={styles.fieldLabel}>Permissions</legend>
        <div className={styles.checks}>
          {!role.human ? (
            <label className={styles.check} data-field="spawnable">
              <input type="checkbox" checked={Boolean(role.spawnable)} disabled={dis} data-testid="role-spawnable" onChange={(e) => set({ spawnable: e.target.checked })} />spawnable
            </label>
          ) : null}
          <label className={styles.check} data-field="criterion_author">
            <input type="checkbox" checked={Boolean(role.criterion_author)} disabled={dis} data-testid="role-author" onChange={(e) => set({ criterion_author: e.target.checked })} />authors criteria
          </label>
          <label className={styles.check} data-field="criterion_checker">
            <input type="checkbox" checked={Boolean(role.criterion_checker)} disabled={dis} data-testid="role-checker" onChange={(e) => set({ criterion_checker: e.target.checked })} />checks criteria
          </label>
          <label className={styles.check} data-field="gate_answerer">
            <input type="checkbox" checked={Boolean(role.gate_answerer)} disabled={dis} data-testid="role-gate" onChange={(e) => set({ gate_answerer: e.target.checked })} />answers gates
          </label>
        </div>
        <span className={styles.help}>{FIELD_HELP.criterion_checker} {FIELD_HELP.gate_answerer}</span>
        <div className={styles.field} data-field="may_spawn">
          <span className={styles.fieldLabel}>May spawn</span>
          <div className={styles.checks}>
            {others.filter((o) => !o.human).map((o) => (
              <label key={o.id} className={styles.check}>
                <input type="checkbox" disabled={dis} checked={(role.may_spawn ?? []).includes(o.id)} data-testid={`role-may-spawn-${o.id}`}
                  onChange={(e) => set({ may_spawn: toggleIn(role.may_spawn, o.id, e.target.checked) })} />{roleLabel(o)}
              </label>
            ))}
          </div>
          <Help k="may_spawn" />
        </div>
        {!role.human ? (
          <div className={styles.field} data-field="spawned_by">
            <span className={styles.fieldLabel}>Spawned by</span>
            <div className={styles.checks}>
              {others.map((o) => (
                <label key={o.id} className={styles.check}>
                  <input type="checkbox" disabled={dis} checked={spawners.includes(o.id)} data-testid={`role-spawned-by-${o.id}`}
                    onChange={(e) => setSpawnedBy(o.id, e.target.checked)} />{roleLabel(o)}
                </label>
              ))}
            </div>
            <Help k="spawned_by" />
          </div>
        ) : null}
        <div className={styles.field} data-field="may_create">
          <span className={styles.fieldLabel}>May create</span>
          <div className={styles.checks}>
            {KINDS.map((k) => (
              <label key={k} className={styles.check}>
                <input type="checkbox" disabled={dis} checked={(role.may_create ?? []).includes(k)} data-testid={`role-may-create-${k}`}
                  onChange={(e) => set({ may_create: toggleIn(role.may_create, k, e.target.checked) })} />{k}
              </label>
            ))}
          </div>
        </div>
        <div className={styles.field} data-field="doc_types">
          <span className={styles.fieldLabel}>Authors documents</span>
          <div className={styles.checks}>
            {DOC_TYPES.map((k) => (
              <label key={k} className={styles.check}>
                <input type="checkbox" disabled={dis} checked={(role.doc_types ?? []).includes(k)}
                  onChange={(e) => set({ doc_types: toggleIn(role.doc_types, k, e.target.checked) })} />{k}
              </label>
            ))}
          </div>
        </div>
        <div className={styles.field}>
          <span className={styles.fieldLabel}>Workflow permissions</span>
          <div className={styles.checks}>
            {Object.keys(wf.permissions).map((k) => (
              <label key={k} className={styles.check} title={PERMISSION_HELP[k]}>
                <input type="checkbox" disabled={dis} checked={(wf.permissions[k] ?? []).includes(role.id)} data-testid={`role-perm-${k}`}
                  onChange={(e) => setPermission(k, e.target.checked)} />{k}
              </label>
            ))}
          </div>
          <Help k="permissions" />
        </div>
      </fieldset>
      {editable ? (
        <div className={styles.row}>
          <button type="button" className={`${ui.button} ${styles.small}`} data-testid="role-remove" onClick={removeRole}>Remove role {role.id}</button>
        </div>
      ) : null}
    </div>
  );
}

interface CardRead { name: string; source: "inline" | "shipped" | "none"; markdown: string; html: string; kernel_preamble: string }

function CardEditor({ role, savedRef, editable, onChange }: { role: RoleDef; savedRef: string; editable: boolean; onChange: (md: string) => void }): React.JSX.Element {
  const shipped = useQuery({
    queryKey: ["workflow", savedRef, "card", role.id],
    queryFn: () => api<CardRead>(`/v1/workflows/${encodeURIComponent(savedRef)}/card/${encodeURIComponent(role.id)}`),
    enabled: !role.card_md,
    retry: false,
  });
  const [debounced, setDebounced] = useState(role.card_md ?? "");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(role.card_md ?? ""), 300);
    return () => clearTimeout(t);
  }, [role.card_md]);
  const preview = useQuery({
    queryKey: ["card-preview", debounced],
    queryFn: async () => (await postJson<{ html: string; kernel_preamble: string }>("/v1/workflows/card-preview", { card_md: debounced })).value,
    enabled: Boolean(debounced),
    retry: false,
  });
  const inline = Boolean(role.card_md);
  return (
    <div className={styles.field} data-field="card">
      <span className={styles.fieldLabel}>Card {inline ? "(written in this workflow)" : shipped.data?.source === "shipped" ? `(shipped card /${shipped.data.name})` : ""}</span>
      <Help k="card" />
      {inline || editable ? (
        <div className={styles.cardEditor}>
          <textarea className={ui.textarea} rows={14} value={role.card_md ?? ""} disabled={!editable} data-testid="role-card"
            placeholder={shipped.data?.markdown ? "Empty: the shipped card is used. Start from it with the button below." : "Write the role's instructions in markdown."}
            onChange={(e) => onChange(e.target.value)} aria-label={`Card for ${role.id}`} />
          <div className={styles.preview} data-testid="role-card-preview">
            {inline ? (preview.data ? <Markdown html={preview.data.html} /> : <p className={styles.muted}>Rendering…</p>)
              : shipped.data?.html ? <Markdown html={shipped.data.html} /> : <p className={styles.muted}>No card yet.</p>}
          </div>
        </div>
      ) : (
        <div className={styles.preview} data-testid="role-card-preview">
          {shipped.data?.html ? <Markdown html={shipped.data.html} /> : <p className={styles.muted}>No card.</p>}
        </div>
      )}
      {editable && !inline && shipped.data?.markdown ? (
        <div className={styles.row}>
          <button type="button" className={`${ui.button} ${styles.small}`} data-testid="role-card-fork"
            onClick={() => onChange(shipped.data!.markdown)}>Edit a copy of the shipped card</button>
        </div>
      ) : null}
      <details>
        <summary className={styles.help}>Kernel preamble (always prepended, not editable)</summary>
        <div className={styles.kernel} data-testid="role-card-kernel">{shipped.data?.kernel_preamble ?? preview.data?.kernel_preamble ?? ""}</div>
      </details>
    </div>
  );
}

function AddRole({ wf, templates, onChange, onDone }: RolePanelProps & { onDone: (id: string) => void }): React.JSX.Element {
  const [tpl, setTpl] = useState("builder");
  const [id, setId] = useState("");
  const [label, setLabel] = useState("");
  const humans = wf.roles.filter((r) => r.human).map((r) => r.id);
  const defaultSpawner = wf.roles.find((r) => r.id === "architect")?.id ?? wf.roles.find((r) => (r.may_spawn ?? []).length && !r.human)?.id ?? humans[0] ?? "";
  const [spawner, setSpawner] = useState(defaultSpawner);
  const taken = wf.roles.some((r) => r.id === id);
  const bad = !ROLE_ID.test(id) ? "Use lowercase letters, digits and dashes, starting with a letter."
    : NON_AGENT_ROLES.has(id) ? `${id} is a person's role, never a seat: pick another id.`
    : taken ? `A role ${id} already exists.` : null;
  const add = () => {
    // blank = a spawnable seat role with nothing else: Validate then names what it lacks (card, bundle)
    const base = tpl === "blank" ? { spawnable: true } : templates?.roles[tpl]?.role ?? {};
    const role: RoleDef = { ...structuredClone(base), id, label: label.trim() || id };
    onChange({
      ...wf,
      roles: [...wf.roles.map((r) => (r.id === spawner ? { ...r, may_spawn: [...new Set([...(r.may_spawn ?? []), id])] } : r)), role],
    });
    onDone(id);
  };
  return (
    <form className={styles.upstream} data-testid="role-add" onSubmit={(e) => { e.preventDefault(); if (!bad) add(); }}>
      <strong>Add a role</strong>
      <div className={styles.grid}>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Start from</span>
          <select className={ui.select} value={tpl} onChange={(e) => setTpl(e.target.value)} data-testid="role-add-template">
            {Object.entries(templates?.roles ?? {}).map(([k, t]) => <option key={k} value={k}>{t.label} — {t.help}</option>)}
            <option value="blank">Blank</option>
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Id</span>
          <input className={ui.input} value={id} onChange={(e) => setId(e.target.value.trim())} placeholder="e.g. designer" data-testid="role-add-id" />
          <Help k="id" />
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Label</span>
          <input className={ui.input} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Designer" data-testid="role-add-label" />
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Spawned by</span>
          <select className={ui.select} value={spawner} onChange={(e) => setSpawner(e.target.value)} data-testid="role-add-spawner">
            <option value="">nobody yet</option>
            {wf.roles.map((r) => <option key={r.id} value={r.id}>{roleLabel(r)}</option>)}
          </select>
        </label>
      </div>
      {id && bad ? <p className={styles.help} role="alert">{bad}</p> : null}
      <div className={styles.row}>
        <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={Boolean(bad)} data-testid="role-add-save">Add role</button>
      </div>
    </form>
  );
}
