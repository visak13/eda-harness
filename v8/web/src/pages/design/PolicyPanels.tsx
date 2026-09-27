import { useEffect, useRef } from "react";
import type { Templates, WorkflowDef } from "../../api/workflows";
import ui from "../../components/ui.module.css";
import styles from "./Design.module.css";
import {
  CAP_HELP, CAP_LABEL, GATE_EDGE, GATE_HELP, GATE_LABEL, HOOK_HELP, HOOK_LABEL, PARAM_LABEL, checksByRole, plain, preconditionText, roleLabel,
} from "./model";

// S14 (§4.14(c)): hooks, gates and caps — toggles and params, each with a one-line explanation. Hooks are a
// fixed registry (no user code runs); a gate's preconditions are the board's and shown read-only.
// t-0c16c00424: plain names lead (the internal key stays, small, for reading board messages); every field keeps
// its hint line, and an empty list says what to do next.

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
      <h2 className={styles.cardTitle}>What the board does on its own</h2>
      <p className={styles.muted}>Built-in behaviours (hooks). Switch one off or change who it involves; no other code runs.</p>
      {names.length === 0 ? <p className={styles.empty} data-testid="hooks-empty">No behaviours are listed yet. Reload the page; if it stays empty, the board could not send its hook list.</p> : null}
      {names.map((name) => {
        const h = wf.hooks[name] ?? { on: false, params: {} };
        const defaults = templates?.hooks[name] ?? {};
        const params = { ...defaults, ...h.params };
        return (
          <div key={name} className={styles.hookRow} data-field={name} data-testid={`hook-${name}`}>
            <label className={styles.check}>
              <input type="checkbox" checked={h.on} disabled={!editable} data-testid={`hook-toggle-${name}`}
                onChange={(e) => set(name, { on: e.target.checked })} />
              <span className={styles.field}>
                <span className={styles.plainName}>{HOOK_LABEL[name] ?? plain(name)}</span>
                <span className={styles.keyName}>{name}</span>
              </span>
            </label>
            <div className={styles.field}>
              <span className={styles.help}>{HOOK_HELP[name] ?? "A board behaviour."}</span>
              {Object.keys(params).length ? (
                <div className={styles.row}>
                  {Object.entries(params).map(([k, v]) => (
                    <label key={k} className={styles.check}>
                      <span className={styles.fieldLabel}>{PARAM_LABEL[k] ?? plain(k)}</span>
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
      <h2 className={styles.cardTitle}>Where a person must say yes</h2>
      <p className={styles.muted}>A gate stops work until a person answers it. Pick who may answer; the board checks the rest.</p>
      {wf.gates.length === 0 ? <p className={styles.empty} data-testid="gates-empty">No gates: nothing in this workflow waits for a person. To add one, duplicate a preset that has the gate you want (Standard has them all).</p> : null}
      {wf.gates.map((g) => {
        const edge = GATE_EDGE[g.id];
        const humanAnswer = g.answerers.some((a) => wf.roles.find((r) => r.id === a)?.human);
        return (
          <div key={g.id} className={styles.hookRow} data-field={g.id} data-testid={`gate-${g.id}`}>
            <div className={styles.field}>
              <span className={styles.plainName}>{GATE_LABEL[g.id] ?? plain(g.id)}</span>
              <span className={styles.keyName}>{g.id}</span>
              {edge ? <span className={styles.help}>between {plain(edge[0])} and {plain(edge[1])}</span> : <span className={styles.help}>on any live ticket</span>}
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
                <summary className={styles.help}>What the board checks first ({g.requires.length + (g.answer_requires?.length ?? 0)})</summary>
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
      <h2 className={styles.cardTitle}>Limits (caps)</h2>
      <p className={styles.muted}>Limits the board keeps on every epic that runs on this version. Each must be 1 or more; a limit of 0 stops work for good, it does not pause it.</p>
      <div className={styles.grid}>
        {caps.map((k) => (
          <label key={k} className={styles.field} data-field={k}>
            <span className={styles.fieldLabel}>{CAP_LABEL[k] ?? plain(k)}</span>
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

/** t-0c16c00424: who checks each kind of work, in words, from the checker map (first matching rule wins). */
export function CheckersPanel({ wf }: { wf: WorkflowDef }): React.JSX.Element {
  const checks = checksByRole(wf);
  const byId = new Map(wf.roles.map((r) => [r.id, r]));
  const rows = Object.entries(checks);
  const unchecked = wf.kinds.filter((k) => !rows.some(([, kinds]) => kinds.includes(k)));
  return (
    <div className={styles.card} data-testid="design-checkers">
      <h2 className={styles.cardTitle}>Who checks the work</h2>
      <p className={styles.muted}>When a ticket reaches review, the board asks this role for a pass or fail on each of its checks (criteria). A role never checks its own work.</p>
      {rows.length === 0 ? <p className={styles.empty} data-testid="checkers-empty">No role checks any work, so nothing can pass review. Give a role "Records pass/fail verdicts" under Roles.</p> : (
        <ul className={styles.checkList}>
          {rows.map(([role, kinds]) => {
            const r = byId.get(role);
            return (
              <li key={role} className={styles.checkItem} data-testid={`checker-${role}`}>
                <span className={styles.plainName}>{r ? roleLabel(r) : role}{r?.human ? " (a person)" : ""}</span>
                <span>checks every {kinds.map(plain).join(", ")}</span>
              </li>
            );
          })}
        </ul>
      )}
      {unchecked.length ? <p className={styles.help} data-testid="checkers-unchecked">Not checked by any role: {unchecked.map(plain).join(", ")}.</p> : null}
    </div>
  );
}
