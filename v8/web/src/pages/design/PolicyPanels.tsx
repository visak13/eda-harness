import { useEffect, useRef } from "react";
import type { Templates, WorkflowDef } from "../../api/workflows";
import ui from "../../components/ui.module.css";
import styles from "./Design.module.css";
import { CAP_HELP, GATE_EDGE, GATE_HELP, HOOK_HELP, preconditionText, roleLabel } from "./model";

// S14 (§4.14(c)): hooks, gates and caps — toggles and params, each with a one-line explanation. Hooks are a
// fixed registry (no user code runs); a gate's preconditions are the board's and shown read-only.

interface PanelProps { wf: WorkflowDef; editable: boolean; onChange: (wf: WorkflowDef) => void; focusField?: string | null }

function useFocus(focusField: string | null | undefined) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focusField) return;
    const el = ref.current?.querySelector<HTMLElement>(`[data-field="${focusField}"]`);
    if (!el) return;
    el.scrollIntoView?.({ block: "center" });
    el.classList.add(styles.flash);
    el.querySelector<HTMLElement>("input,select,button")?.focus();
    const t = setTimeout(() => el.classList.remove(styles.flash), 2400);
    return () => clearTimeout(t);
  }, [focusField]);
  return ref;
}

export function HooksPanel({ wf, editable, onChange, focusField, templates }: PanelProps & { templates: Templates | undefined }): React.JSX.Element {
  const ref = useFocus(focusField);
  const names = [...new Set([...Object.keys(templates?.hooks ?? {}), ...Object.keys(wf.hooks)])];
  const set = (name: string, patch: { on?: boolean; params?: Record<string, unknown> }) => {
    const cur = wf.hooks[name] ?? { on: false, params: {} };
    onChange({ ...wf, hooks: { ...wf.hooks, [name]: { ...cur, ...patch } } });
  };
  return (
    <div ref={ref} className={styles.card} data-testid="design-hooks">
      <h2 className={styles.cardTitle}>Hooks</h2>
      <p className={styles.muted}>Built-in board behaviours. Switch one off or change its parameter; nothing else runs.</p>
      {names.map((name) => {
        const h = wf.hooks[name] ?? { on: false, params: {} };
        const defaults = templates?.hooks[name] ?? {};
        const params = { ...defaults, ...h.params };
        return (
          <div key={name} className={styles.hookRow} data-field={name} data-testid={`hook-${name}`}>
            <label className={styles.check}>
              <input type="checkbox" checked={h.on} disabled={!editable} data-testid={`hook-toggle-${name}`}
                onChange={(e) => set(name, { on: e.target.checked })} />
              <span className={styles.mono}>{name}</span>
            </label>
            <div className={styles.field}>
              <span className={styles.help}>{HOOK_HELP[name] ?? "A board behaviour."}</span>
              {Object.keys(params).length ? (
                <div className={styles.row}>
                  {Object.entries(params).map(([k, v]) => (
                    <label key={k} className={styles.check}>
                      <span className={styles.fieldLabel}>{k}</span>
                      {k === "role" || k === "epic_checker" || k === "checked_by" ? (
                        <select className={ui.select} value={String(v ?? "")} disabled={!editable || !h.on} data-testid={`hook-param-${name}-${k}`}
                          onChange={(e) => set(name, { params: { ...h.params, [k]: e.target.value } })}>
                          {wf.roles.map((r) => <option key={r.id} value={r.id}>{roleLabel(r)}</option>)}
                          {wf.roles.some((r) => r.id === v) ? null : <option value={String(v ?? "")}>{String(v ?? "")} (not a role)</option>}
                        </select>
                      ) : (
                        <input className={ui.input} value={String(v ?? "")} disabled={!editable || !h.on} data-testid={`hook-param-${name}-${k}`}
                          onChange={(e) => set(name, { params: { ...h.params, [k]: e.target.value } })} />
                      )}
                    </label>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function GatesPanel({ wf, editable, onChange, focusField }: PanelProps): React.JSX.Element {
  const ref = useFocus(focusField);
  const setAnswerer = (gate: string, role: string, on: boolean) => onChange({
    ...wf,
    gates: wf.gates.map((g) => (g.id !== gate ? g : {
      ...g, answerers: on ? [...new Set([...g.answerers, role])] : g.answerers.filter((x) => x !== role),
    })),
  });
  return (
    <div ref={ref} className={styles.card} data-testid="design-gates">
      <h2 className={styles.cardTitle}>Gates</h2>
      <p className={styles.muted}>A gate stops work until a human answers it. Pick who answers; the board checks the preconditions.</p>
      {wf.gates.map((g) => {
        const edge = GATE_EDGE[g.id];
        const humanAnswer = g.answerers.some((a) => wf.roles.find((r) => r.id === a)?.human);
        return (
          <div key={g.id} className={styles.hookRow} data-field={g.id} data-testid={`gate-${g.id}`}>
            <div className={styles.field}>
              <span className={styles.mono}>{g.id}</span>
              {edge ? <span className={styles.help}>between {edge[0]} and {edge[1]}</span> : <span className={styles.help}>on any live ticket</span>}
              {!humanAnswer ? <span className={`${styles.badge} ${styles.badgeErr}`}>no human answers it</span> : null}
            </div>
            <div className={styles.field}>
              <span className={styles.help}>{GATE_HELP[g.id] ?? "A decision a human answers."}</span>
              <div className={styles.checks}>
                {wf.roles.map((r) => (
                  <label key={r.id} className={styles.check}>
                    <input type="checkbox" disabled={!editable} checked={g.answerers.includes(r.id)} data-testid={`gate-answerer-${g.id}-${r.id}`}
                      onChange={(e) => setAnswerer(g.id, r.id, e.target.checked)} />{roleLabel(r)}{r.human ? "" : " (agent)"}
                  </label>
                ))}
              </div>
              <details>
                <summary className={styles.help}>{g.requires.length + (g.answer_requires?.length ?? 0)} preconditions</summary>
                <ul className={styles.pre}>
                  {[...g.requires, ...(g.answer_requires ?? [])].map((p, i) => <li key={i}>{preconditionText(p)}</li>)}
                </ul>
              </details>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function CapsPanel({ wf, editable, onChange, focusField }: PanelProps): React.JSX.Element {
  const ref = useFocus(focusField);
  const caps = Object.keys({ ...CAP_HELP, ...wf.caps });
  return (
    <div ref={ref} className={styles.card} data-testid="design-caps">
      <h2 className={styles.cardTitle}>Caps</h2>
      <p className={styles.muted}>Limits the board enforces on every epic pinned to this version. Each must be 1 or more; a cap of 0 deadlocks work, it does not pause it.</p>
      <div className={styles.grid}>
        {caps.map((k) => (
          <label key={k} className={styles.field} data-field={k}>
            <span className={styles.fieldLabel}>{k.replaceAll("_", " ")}</span>
            <input className={ui.input} type="number" value={wf.caps[k] ?? ""} disabled={!editable} data-testid={`cap-${k}`}
              onChange={(e) => onChange({ ...wf, caps: { ...wf.caps, [k]: e.target.value === "" ? 0 : Number(e.target.value) } })} />
            <span className={styles.help}>{CAP_HELP[k] ?? ""}</span>
          </label>
        ))}
      </div>
      <p className={styles.help}>Concurrent seats per role are set on each role (Roles → Max concurrent seats) and per class in Admin → Services → Capacity.</p>
    </div>
  );
}
