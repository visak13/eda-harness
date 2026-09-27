import { useState } from "react";
import type { Transition, WorkflowDef } from "../../api/workflows";
import styles from "./Design.module.css";
import { GATE_EDGE, GATE_LABEL, MAIN_PATH, checksByRole, plain, preconditionText, roleLabel, roleLayers, whoTakes } from "./model";

// S14 (§4.14(c)): the pipeline at a glance — who spawns whom and who checks what (roles graph), then the
// status flow with the gates between stages. Every edge comes from the definition; the full transition
// table underneath lists each edge's declared preconditions, so nothing the board enforces is hidden.

const NODE_W = 150;
const NODE_H = 46;
const COL = 210;
const ROW = 66;

export function PipelineView({ wf }: { wf: WorkflowDef }): React.JSX.Element {
  const [picked, setPicked] = useState<string | null>(null);
  const edge = picked ? wf.transitions.find((t) => `${t.from}→${t.to}` === picked) ?? null : null;
  return (
    <div className={styles.card} data-testid="design-pipeline">
      <h2 className={styles.cardTitle}>How a ticket moves</h2>
      <p className={styles.help}>Left to right, the path every ticket takes from idea to done. A chip above an arrow is a gate: a person answers before work goes on. Pick an arrow to see who may move a ticket along it.</p>
      <StatusFlow wf={wf} onPick={setPicked} picked={picked} />
      {edge ? <EdgeDetail wf={wf} t={edge} /> : null}
      <h2 className={styles.cardTitle}>Who starts and checks whom</h2>
      <p className={styles.help}>People sit on the left. A solid arrow means that role starts seats of the next; a dashed arrow means it checks their work.</p>
      <RolesGraph wf={wf} />
      <TransitionTable wf={wf} onPick={setPicked} picked={picked} />
    </div>
  );
}

function RolesGraph({ wf }: { wf: WorkflowDef }): React.JSX.Element {
  const { layers, unreached, idle } = roleLayers(wf);
  const checks = checksByRole(wf);
  const cols = [...layers, ...(unreached.length ? [unreached] : [])];
  const pos = new Map<string, { x: number; y: number }>();
  cols.forEach((col, ci) => col.forEach((id, ri) => pos.set(id, { x: 20 + ci * COL, y: 20 + ri * ROW })));
  const width = Math.max(720, 40 + cols.length * COL);
  const height = Math.max(120, 40 + Math.max(1, ...cols.map((c) => c.length)) * ROW);
  const byId = new Map(wf.roles.map((r) => [r.id, r]));
  const spawnEdges = wf.roles.flatMap((r) => (r.may_spawn ?? []).filter((s) => pos.has(s) && pos.has(r.id)).map((s) => [r.id, s] as const));
  const builders = wf.roles.filter((r) => r.capacity_class === "builder" && pos.has(r.id)).map((r) => r.id);
  const checkEdges = Object.entries(checks).flatMap(([checker, kinds]) =>
    pos.has(checker) ? builders.filter((b) => b !== checker).map((b) => [checker, b, kinds.join(", ")] as const) : []);
  const unreachedSet = new Set(unreached);
  return (
    <>
      <div className={styles.svgWrap}>
        <svg className={styles.svg} width={width} height={height} role="img" data-testid="pipeline-roles"
          aria-label={`Roles: ${cols.flat().map((id) => `${id}${byId.get(id)?.human ? " (human)" : ""} spawns ${(byId.get(id)?.may_spawn ?? []).join(", ") || "nobody"}`).join("; ")}`}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0L10 5L0 10z" fill="currentColor" />
            </marker>
          </defs>
          {spawnEdges.map(([a, b]) => {
            const p = pos.get(a)!; const q = pos.get(b)!;
            return <path key={`s-${a}-${b}`} className={styles.edgeSpawn} markerEnd="url(#arrow)" data-testid={`spawn-edge-${a}-${b}`}
              d={`M${p.x + NODE_W} ${p.y + NODE_H / 2} C${p.x + NODE_W + 30} ${p.y + NODE_H / 2} ${q.x - 30} ${q.y + NODE_H / 2} ${q.x} ${q.y + NODE_H / 2}`} />;
          })}
          {checkEdges.map(([a, b, kinds]) => {
            const p = pos.get(a)!; const q = pos.get(b)!;
            const mx = (p.x + q.x + NODE_W) / 2; const my = (p.y + q.y) / 2 + NODE_H;
            return (
              <g key={`c-${a}-${b}`} data-testid={`check-edge-${a}-${b}`}>
                <path className={styles.edgeCheck} markerEnd="url(#arrow)"
                  d={`M${p.x + NODE_W / 2} ${p.y + NODE_H} Q${mx} ${my + 30} ${q.x + NODE_W / 2} ${q.y + NODE_H}`} />
                <text className={styles.edgeLabel} x={mx} y={my + 22} textAnchor="middle">checks {kinds}</text>
              </g>
            );
          })}
          {cols.flat().map((id) => {
            const r = byId.get(id)!; const p = pos.get(id)!;
            const cls = [styles.node, r.human ? styles.nodeHuman : "", unreachedSet.has(id) ? styles.nodeUnreached : ""].join(" ");
            const sub = r.human ? "human" : `${r.capacity_class ?? "no class"}${r.max_concurrent ? ` · max ${r.max_concurrent}` : ""}`;
            return (
              <g key={id} className={cls} transform={`translate(${p.x} ${p.y})`} data-testid={`role-node-${id}`}>
                <rect width={NODE_W} height={NODE_H} rx={8} />
                <text className={styles.nodeLabel} x={10} y={19}>{roleLabel(r)}</text>
                <text className={styles.nodeSub} x={10} y={36}>{unreachedSet.has(id) ? "no spawner" : sub}{checks[id] ? ` · checks ${checks[id].join(",")}` : ""}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className={styles.legend}>
        <span><span className={styles.swatch} />starts seats of</span>
        <span><span className={`${styles.swatch} ${styles.swatchCheck}`} />checks the builders' work</span>
        {idle.length ? <span data-testid="pipeline-idle">on call, not in the flow: {idle.join(", ")}</span> : null}
        {unreached.length ? <span data-testid="pipeline-unreached">no role starts: {unreached.join(", ")}</span> : null}
      </div>
    </>
  );
}

function StatusFlow({ wf, onPick, picked }: { wf: WorkflowDef; onPick: (k: string) => void; picked: string | null }): React.JSX.Element {
  const main = MAIN_PATH.filter((s) => wf.statuses.includes(s));
  const side = wf.statuses.filter((s) => !main.includes(s));
  const SW = 118; const GAP = 150;
  const x = (i: number) => 20 + i * GAP;
  const width = Math.max(720, 40 + main.length * GAP);
  const height = side.length ? 200 : 120;
  const terminal = new Set(wf.terminal);
  const gatesOn = (a: string, b: string) => wf.gates.filter((g) => {
    const e = GATE_EDGE[g.id];
    return e && e[0] === a && e[1] === b;
  });
  return (
    <div className={styles.svgWrap}>
      <svg className={styles.svg} width={width} height={height} role="img" data-testid="pipeline-flow"
        aria-label={`How a ticket moves: ${main.map(plain).join(" → ")}${side.length ? `; it can also be ${side.map(plain).join(", ")}` : ""}`}>
        {main.slice(0, -1).map((s, i) => {
          const to = main[i + 1];
          const t = wf.transitions.find((e) => e.from === s && e.to === to);
          const key = `${s}→${to}`;
          const x1 = x(i) + SW; const x2 = x(i + 1);
          const gates = gatesOn(s, to);
          return (
            <g key={key}>
              {t ? (
                <g className={styles.edgeHit} tabIndex={0} role="button" aria-label={`${key}: ${whoTakes(wf, t)}`}
                  aria-pressed={picked === key} data-testid={`flow-edge-${s}-${to}`}
                  onClick={() => onPick(key)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(key); } }}>
                  <line className={t.requires.length ? styles.flowEdge : styles.flowEdgeBare} x1={x1} y1={56} x2={x2 - 2} y2={56} markerEnd="url(#arrow2)" />
                  <rect x={x1} y={40} width={x2 - x1} height={32} fill="transparent" />
                  <text className={styles.edgeLabel} x={(x1 + x2) / 2} y={90} textAnchor="middle">{whoTakes(wf, t).slice(0, 22)}</text>
                </g>
              ) : (
                <text className={styles.edgeLabel} x={(x1 + x2) / 2} y={60} textAnchor="middle">no edge</text>
              )}
              {gates.map((g, gi) => (
                <g key={g.id} className={styles.gateChip} transform={`translate(${(x1 + x2) / 2 - 50} ${14 - gi * 18})`} data-testid={`flow-gate-${g.id}`}>
                  <rect width={100} height={18} rx={9} />
                  <text className={styles.gateText} x={50} y={12.5} textAnchor="middle">{GATE_LABEL[g.id] ?? plain(g.id)}</text>
                </g>
              ))}
            </g>
          );
        })}
        <defs>
          <marker id="arrow2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill="currentColor" />
          </marker>
        </defs>
        {main.map((s, i) => (
          <g key={s} className={`${styles.status} ${terminal.has(s) ? styles.statusTerminal : ""}`} transform={`translate(${x(i)} 40)`} data-testid={`flow-status-${s}`}>
            <rect width={SW} height={32} rx={16} />
            <text className={styles.nodeLabel} x={SW / 2} y={21} textAnchor="middle">{plain(s)}</text>
          </g>
        ))}
        {side.map((s, i) => (
          <g key={s} className={`${styles.status} ${terminal.has(s) ? styles.statusTerminal : ""}`} transform={`translate(${x(i + 1)} 140)`} data-testid={`flow-status-${s}`}>
            <rect width={SW} height={32} rx={16} />
            <text className={styles.nodeLabel} x={SW / 2} y={21} textAnchor="middle">{plain(s)}</text>
          </g>
        ))}
        {side.length ? <text className={styles.edgeLabel} x={20} y={160}>can also be:</text> : null}
      </svg>
    </div>
  );
}

function EdgeDetail({ wf, t }: { wf: WorkflowDef; t: Transition }): React.JSX.Element {
  return (
    <div className={styles.upstream} data-testid="flow-edge-detail">
      <strong>{plain(t.from)} → {plain(t.to)}</strong>
      <span className={styles.muted}>Who may move a ticket here: {whoTakes(wf, t)}{t.auto ? " — the board carries a ticket along it when the checks pass" : ""}</span>
      {t.requires.length ? (
        <ul className={styles.pre}>{t.requires.map((p, i) => <li key={i}>{preconditionText(p)}</li>)}</ul>
      ) : <span className={styles.badge} data-testid="flow-edge-bare">no check: anyone may move a ticket here at any time</span>}
    </div>
  );
}

function TransitionTable({ wf, onPick, picked }: { wf: WorkflowDef; onPick: (k: string) => void; picked: string | null }): React.JSX.Element {
  return (
    <details data-testid="pipeline-transitions">
      <summary className={styles.fieldLabel}>Every move and what the board checks ({wf.transitions.length})</summary>
      <table className={styles.diffTable}>
        <thead><tr><th>Move</th><th>Who may make it</th><th>What the board checks</th></tr></thead>
        <tbody>
          {wf.transitions.map((t) => {
            const key = `${t.from}→${t.to}`;
            return (
              <tr key={key} aria-selected={picked === key}>
                <td><button type="button" className={`${styles.item} ${styles.small}`} onClick={() => onPick(key)}>{plain(t.from)} → {plain(t.to)}</button></td>
                <td>{whoTakes(wf, t)}</td>
                <td>{t.requires.length ? t.requires.map((p) => p.check).join(", ") : <span className={`${styles.badge} ${styles.badgeDraft}`}>none</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}
