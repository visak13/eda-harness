import { useEffect, useRef, useState } from "react";
import type { Transition, WorkflowDef } from "../../api/workflows";
import styles from "./Design.module.css";
import { GATE_EDGE, GATE_LABEL, MAIN_PATH, checksByRole, plain, preconditionKey, preconditionText, roleLabel, roleLayers, whoTakes } from "./model";
import { CHAR_W, FLOW, GRID, cellRect, flowSlots, flowWidth, placeCells, polyline, routeRoles, wrapWords, type EdgeIn } from "./pipelineLayout";

// S14 (§4.14(c)): the pipeline at a glance — who spawns whom and who checks what (roles graph), then the
// status flow with the gates between stages. Every edge comes from the definition; the full transition
// table underneath lists each edge's declared preconditions, so nothing the board enforces is hidden.
// t-67d19c5807: the geometry lives in pipelineLayout.ts — the flow wraps into rows that fit its box, actor
// labels wrap at words, and roles-graph edges run between the boxes, never through them.

/** The box's inner width, tracked; 0 until measured (and in jsdom, which has no layout). */
function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

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
  const inGraph = new Set(cols.flat());
  const byId = new Map(wf.roles.map((r) => [r.id, r]));
  const builders = wf.roles.filter((r) => r.capacity_class === "builder" && inGraph.has(r.id)).map((r) => r.id);
  const edges: EdgeIn[] = [
    ...wf.roles.flatMap((r) => (r.may_spawn ?? []).filter((s) => inGraph.has(s) && inGraph.has(r.id))
      .map((s) => ({ id: `spawn-edge-${r.id}-${s}`, from: r.id, to: s, kind: "spawn" as const }))),
    ...Object.entries(checks).flatMap(([checker]) => inGraph.has(checker)
      ? builders.filter((b) => b !== checker).map((b) => ({ id: `check-edge-${checker}-${b}`, from: checker, to: b, kind: "check" as const }))
      : []),
  ];
  const cells = placeCells(cols, edges);
  const { routes, rows } = routeRoles(cells, edges);
  const width = GRID.PADX + cols.length * (GRID.W + GRID.COLGAP);
  const height = Math.max(120, GRID.PADY + rows * (GRID.H + GRID.ROWGAP));
  const unreachedSet = new Set(unreached);
  const label = (id: string) => { const r = byId.get(id); return r ? roleLabel(r) : id; };
  // one line per fact, each whole: what the role is, then what it checks (the dashed arrows carry no label)
  const lines = (id: string): string[] => {
    const r = byId.get(id)!;
    const what = unreachedSet.has(id) ? "no spawner" : r.human ? "a person" : `${r.capacity_class ?? "no class"}${r.max_concurrent ? ` · max ${r.max_concurrent}` : ""}`;
    const chk = checks[id] ? `checks ${checks[id].join(", ")}` : "";
    return [what, ...(chk ? [chk] : [])];
  };
  const room = Math.floor((GRID.W - 20) / CHAR_W);
  return (
    <>
      <div className={styles.svgWrap}>
        <svg className={`${styles.svg} ${styles.svgFit}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" data-testid="pipeline-roles"
          aria-label={`Roles: ${cols.flat().map((id) => `${label(id)}${byId.get(id)?.human ? " (a person)" : ""} starts ${(byId.get(id)?.may_spawn ?? []).map(label).join(", ") || "nobody"}${checks[id] ? ` and checks ${checks[id].join(", ")}` : ""}`).join("; ")}`}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0L10 5L0 10z" fill="currentColor" />
            </marker>
          </defs>
          {routes.map((r) => r.kind === "spawn" ? (
            <path key={r.id} className={styles.edgeSpawn} markerEnd="url(#arrow)" data-testid={r.id} data-from={r.from} data-to={r.to} d={polyline(r.points)}>
              <title>{label(r.from)} starts seats of {label(r.to)}</title>
            </path>
          ) : (
            <g key={r.id} data-testid={r.id} data-from={r.from} data-to={r.to}>
              <path className={styles.edgeCheck} markerEnd="url(#arrow)" d={polyline(r.points)}>
                <title>{label(r.from)} checks the work of {label(r.to)} ({(checks[r.from] ?? []).join(", ")})</title>
              </path>
            </g>
          ))}
          {cols.flat().map((id) => {
            const r = byId.get(id)!; const p = cellRect(cells.get(id)!.col, cells.get(id)!.row);
            const cls = [styles.node, r.human ? styles.nodeHuman : "", unreachedSet.has(id) ? styles.nodeUnreached : ""].join(" ");
            const ls = lines(id);
            return (
              <g key={id} className={cls} transform={`translate(${p.x} ${p.y})`} data-testid={`role-node-${id}`}>
                <title>{`${roleLabel(r)}: ${ls.join(" · ")}`}</title>
                <rect width={GRID.W} height={GRID.H} rx={8} />
                <text className={styles.nodeLabel} x={10} y={ls.length > 1 ? 18 : 23}>{roleLabel(r)}</text>
                {ls.map((l, i) => (
                  <text key={i} className={styles.nodeSub} x={10} y={(ls.length > 1 ? 34 : 40) + i * 14}>{l.length > room ? `${l.slice(0, l.lastIndexOf(" ", room))} …` : l}</text>
                ))}
              </g>
            );
          })}
        </svg>
      </div>
      <div className={styles.legend}>
        <span><span className={styles.swatch} />starts seats of</span>
        <span><span className={`${styles.swatch} ${styles.swatchCheck}`} />checks the work of (what it checks is on its box)</span>
        {idle.length ? <span data-testid="pipeline-idle">on call, not in the flow: {idle.map(label).join(", ")}</span> : null}
        {unreached.length ? <span data-testid="pipeline-unreached">no role starts: {unreached.map(label).join(", ")}</span> : null}
      </div>
    </>
  );
}

function StatusFlow({ wf, onPick, picked }: { wf: WorkflowDef; onPick: (k: string) => void; picked: string | null }): React.JSX.Element {
  const [wrapRef, avail] = useWidth<HTMLDivElement>();
  const main = MAIN_PATH.filter((s) => wf.statuses.includes(s));
  const side = wf.statuses.filter((s) => !main.includes(s));
  const { SW, SH, GAP, PAD, TAIL, LINE } = FLOW;
  const who = (t: Transition | undefined) => (t ? whoTakes(wf, t) : "");
  const labelLines = (t: Transition | undefined) => (t ? wrapWords(who(t), Math.floor((GAP - 12) / CHAR_W)) : ["no edge"]);
  const maxLines = Math.max(1, ...main.slice(0, -1).map((s, i) => labelLines(wf.transitions.find((e) => e.from === s && e.to === main[i + 1])).length));
  const { perRow, at } = flowSlots(main.length, avail);
  const gatesOn = (a: string, b: string) => wf.gates.filter((g) => {
    const e = GATE_EDGE[g.id];
    return e && e[0] === a && e[1] === b;
  });
  const maxGates = Math.max(0, ...main.slice(0, -1).map((s, i) => gatesOn(s, main[i + 1]).length));
  // one row: gate chips, the status pills, the wrapped actor labels, then the corridor the row-wrap arrow runs along
  const TOP = 8 + Math.max(1, maxGates) * 18;
  const LABEL_Y = SH + 18; // first label baseline, below the pills
  const COR = LABEL_Y + (maxLines - 1) * LINE + 12; // the corridor under a row's labels
  const ROW_H = COR + TOP + 6;
  const nRows = Math.max(...at.map((a) => a.row)) + 1;
  const x = (slot: number) => PAD + slot * GAP;
  const y = (row: number) => TOP + row * ROW_H; // top of the pills of `row`
  const width = Math.max(720, flowWidth(perRow));
  const lastBottom = y(nRows - 1) + COR;
  const sideY = lastBottom + 8;
  const height = side.length ? sideY + SH + 16 : lastBottom + 4;
  const terminal = new Set(wf.terminal);
  return (
    <div className={styles.svgWrap} ref={wrapRef}>
      <svg className={styles.svg} width={width} height={height} role="img" data-testid="pipeline-flow"
        aria-label={`How a ticket moves: ${main.map(plain).join(" → ")}${side.length ? `; it can also be ${side.map(plain).join(", ")}` : ""}`}>
        <defs>
          <marker id="arrow2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill="currentColor" />
          </marker>
        </defs>
        {main.slice(0, -1).map((s, i) => {
          const to = main[i + 1];
          const t = wf.transitions.find((e) => e.from === s && e.to === to);
          const key = `${s}→${to}`;
          const a = at[i]; const b = at[i + 1];
          const wraps = b.row !== a.row;
          const cy = y(b.row) + SH / 2;
          // a wrap comes in from slot 0's centre on the next row, after a drop down the right-hand side
          const x1 = wraps ? x(0) + SW / 2 : x(a.slot) + SW; const x2 = x(b.slot);
          const d = wraps
            ? (() => {
              const ex = x(a.slot) + SW; const ay = y(a.row) + SH / 2; const rx = ex + TAIL - 6;
              const cor = y(a.row) + COR;
              return `M${ex} ${ay} L${rx} ${ay} L${rx} ${cor} L${x1} ${cor} L${x1} ${cy} L${x2 - 2} ${cy}`;
            })()
            : `M${x1} ${cy} L${x2 - 2} ${cy}`;
          const gates = gatesOn(s, to);
          const lines = labelLines(t);
          const mid = (x1 + x2) / 2;
          return (
            <g key={key}>
              {t ? (
                <g className={styles.edgeHit} tabIndex={0} role="button" aria-label={`${key}: ${who(t)}`}
                  aria-pressed={picked === key} data-testid={`flow-edge-${s}-${to}`}
                  onClick={() => onPick(key)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(key); } }}>
                  <title>{`${plain(s)} → ${plain(to)}: ${who(t)}`}</title>
                  <path className={t.requires.length ? styles.flowEdge : styles.flowEdgeBare} d={d} markerEnd="url(#arrow2)" />
                  <rect x={x1} y={cy - 16} width={Math.max(8, x2 - x1)} height={32} fill="transparent" />
                  <text className={styles.edgeLabel} x={mid} y={y(b.row) + LABEL_Y} textAnchor="middle">
                    {lines.map((l, li) => <tspan key={li} x={mid} dy={li ? LINE : 0}>{l}</tspan>)}
                  </text>
                </g>
              ) : (
                <text className={styles.edgeLabel} x={mid} y={cy + 4} textAnchor="middle">no edge</text>
              )}
              {gates.map((g, gi) => (
                <g key={g.id} className={styles.gateChip} transform={`translate(${wraps ? Math.max(mid - 50, x1 + 6) : mid - 50} ${y(b.row) - 22 - gi * 18})`} data-testid={`flow-gate-${g.id}`}>
                  <rect width={100} height={18} rx={9} />
                  <text className={styles.gateText} x={50} y={12.5} textAnchor="middle">{GATE_LABEL[g.id] ?? plain(g.id)}</text>
                </g>
              ))}
            </g>
          );
        })}
        {main.map((s, i) => (
          <g key={s} className={`${styles.status} ${terminal.has(s) ? styles.statusTerminal : ""}`} transform={`translate(${x(at[i].slot)} ${y(at[i].row)})`} data-testid={`flow-status-${s}`}>
            <rect width={SW} height={SH} rx={16} />
            <text className={styles.nodeLabel} x={SW / 2} y={21} textAnchor="middle">{plain(s)}</text>
          </g>
        ))}
        {side.map((s, i) => (
          <g key={s} className={`${styles.status} ${terminal.has(s) ? styles.statusTerminal : ""}`} transform={`translate(${x(i + 1)} ${sideY})`} data-testid={`flow-status-${s}`}>
            <rect width={SW} height={SH} rx={16} />
            <text className={styles.nodeLabel} x={SW / 2} y={21} textAnchor="middle">{plain(s)}</text>
          </g>
        ))}
        {side.length ? <text className={styles.edgeLabel} x={PAD} y={sideY + 20}>can also be:</text> : null}
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
        <ul className={styles.pre}>{t.requires.map((p, i) => <li key={i} title={`board check: ${preconditionKey(p)}`}>{preconditionText(p)}</li>)}</ul>
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
                <td>{t.requires.length ? t.requires.map((p, i) => <span key={i} title={`board check: ${preconditionKey(p)}`}>{i ? "; " : ""}{preconditionText(p)}</span>) : <span className={`${styles.badge} ${styles.badgeDraft}`}>none</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}
