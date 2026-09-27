// t-67d19c5807 (qa m-e633397a42): pure geometry for the Design tab's pipeline drawing, kept apart from React so
// vitest can prove the properties the drawing promises: the status flow wraps into rows that fit the box (so
// "done" is never off-canvas), actor labels wrap at word boundaries (never a mid-word cut), and every
// roles-graph edge runs only through the empty channels between columns and corridors between rows, so no
// edge crosses a box it does not start or end at.

export type Pt = { x: number; y: number };
export type Rect = { x: number; y: number; width: number; height: number };

/** ~px per character of the 11px system-ui labels; deliberately generous so an estimate never undershoots. */
export const CHAR_W = 6.4;

/** Split `text` into lines of at most `max` characters, breaking only between words. A single word longer than
 *  `max` keeps its own whole line: a label is never cut mid-word. */
export function wrapWords(text: string, max: number): string[] {
  const lines: string[] = [];
  let cur = "";
  for (const w of text.split(/\s+/).filter(Boolean)) {
    if (!cur) cur = w;
    else if (cur.length + 1 + w.length <= max) cur += ` ${w}`;
    else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  return lines;
}

// ----------------------------------------------------------------------------- status flow

export const FLOW = { SW: 118, SH: 32, GAP: 150, PAD: 20, TAIL: 22, LINE: 13 } as const;

/** Where each main-path status sits: row 0 uses slots 0..k-1, later rows start at slot 1 so the row-wrap arrow
 *  comes in from the left like any other edge (its label and gate chip get the same room). `avail` = the box's
 *  width in px; 0 (unknown, e.g. jsdom) means one row. */
export function flowSlots(n: number, avail: number): { perRow: number; at: { row: number; slot: number }[] } {
  const { SW, GAP, PAD, TAIL } = FLOW;
  const fit = avail > 0 ? Math.floor((avail - 2 * PAD - SW - TAIL) / GAP) + 1 : n;
  const perRow = Math.max(3, Math.min(n, fit));
  const at: { row: number; slot: number }[] = [];
  let row = 0; let slot = 0;
  for (let i = 0; i < n; i++) {
    if (slot >= perRow) { row += 1; slot = 1; }
    at.push({ row, slot });
    slot += 1;
  }
  return { perRow, at };
}

/** The width a flow of `perRow` slots needs (room on the right for the row-wrap arrow). */
export function flowWidth(perRow: number): number {
  return 2 * FLOW.PAD + (perRow - 1) * FLOW.GAP + FLOW.SW + FLOW.TAIL;
}

// ----------------------------------------------------------------------------- roles graph

// S14 reopen (qa m-c4f23e49f0 "the roles graph is tangled"): a role box carries its name, its class and what it
// checks (so no edge needs a label), and each role's arrows of one kind leave its box as ONE trunk that branches
// to its targets, instead of one private lane per edge.
export const GRID = { W: 172, H: 56, COLGAP: 104, ROWGAP: 30, PADX: 20, PADY: 24 } as const;

export function cellRect(col: number, row: number): Rect {
  return { x: GRID.PADX + col * (GRID.W + GRID.COLGAP), y: GRID.PADY + row * (GRID.H + GRID.ROWGAP), width: GRID.W, height: GRID.H };
}

/** Grid cells for columns of role ids. Column 0 keeps its order; a later role sits in the free row nearest the
 *  mean row of the roles in earlier columns that start it, so its spawn arrows run short and straight. (Check
 *  arrows are left out: pulling a builder toward its checkers lays their stubs over the spawn stubs.) */
export function placeCells(cols: string[][], edges: EdgeIn[]): Map<string, { col: number; row: number }> {
  const cells = new Map<string, { col: number; row: number }>();
  cols.forEach((ids, ci) => {
    if (ci === 0) { ids.forEach((id, row) => cells.set(id, { col: 0, row })); return; }
    const want = ids.map((id, i) => {
      const near = edges.flatMap((e) => ((e.kind ?? "spawn") === "spawn" && e.to === id ? [e.from] : []))
        .map((o) => cells.get(o)).filter((c): c is { col: number; row: number } => Boolean(c) && c!.col < ci);
      return { id, i, at: near.length ? near.reduce((a, c) => a + c.row, 0) / near.length : i };
    });
    const taken = new Set<number>();
    for (const w of [...want].sort((a, b) => a.at - b.at || a.i - b.i)) {
      let row = Math.max(0, Math.round(w.at));
      for (let d = 0; taken.has(row); d++) row = Math.max(0, Math.round(w.at) + (d % 2 ? -(d + 1) / 2 : d / 2 + 1));
      taken.add(row);
      cells.set(w.id, { col: ci, row });
    }
  });
  return cells;
}

/** x of channel c: the empty strip LEFT of column c (c = cols is right of the last column). */
const channelX = (c: number) => GRID.PADX + c * (GRID.W + GRID.COLGAP) - GRID.COLGAP / 2;
/** y of corridor r: the empty strip ABOVE row r (r = rows is below the last row). */
const corridorY = (r: number) => GRID.PADY + r * (GRID.H + GRID.ROWGAP) - GRID.ROWGAP / 2;

export type EdgeKind = "spawn" | "check";
export interface EdgeIn { id: string; from: string; to: string; kind?: EdgeKind }
export interface Routed { id: string; from: string; to: string; kind: EdgeKind; points: Pt[] }

const spread = (i: number, n: number, room: number) => {
  const step = n > 1 ? Math.min(12, room / (n - 1)) : 0;
  return (i - (n - 1) / 2) * step;
};

/** Orthogonal routes. An edge leaves its source's side into the channel beside it, runs along a corridor between
 *  rows when the target sits in another channel, then down the channel beside the target and into its side.
 *  Channels and corridors hold no boxes, so a route touches only its own two boxes. All edges of one source and
 *  kind share one exit point and one lane per channel and corridor (a trunk that branches), so a role that starts
 *  five others draws one line that splits, not five parallel ones. Within a channel, trunks whose branches go left
 *  sit left of those whose branches go right, which keeps branch-over-trunk crossings down. */
export function routeRoles(cells: Map<string, { col: number; row: number }>, edges: EdgeIn[]): { routes: Routed[]; rows: number } {
  const rows = Math.max(1, ...[...cells.values()].map((c) => c.row + 1));
  const plans = edges.filter((e) => cells.has(e.from) && cells.has(e.to) && e.from !== e.to).map((e) => {
    const s = cells.get(e.from)!; const t = cells.get(e.to)!;
    const kind: EdgeKind = e.kind ?? "spawn";
    let exitC: number; let entryC: number; let exitRight: boolean; let entryLeft: boolean;
    if (t.col > s.col) { exitC = s.col + 1; entryC = t.col; exitRight = true; entryLeft = true; }
    else if (t.col < s.col) { exitC = s.col; entryC = t.col + 1; exitRight = false; entryLeft = false; }
    else { exitC = entryC = s.col + 1; exitRight = true; entryLeft = false; }
    // one corridor per trunk: just below the source's row, so the trunk turns once
    const corridor = exitC === entryC ? null : Math.min(rows, s.row + 1);
    return { e, s, t, kind, group: `${e.from}:${kind}:${exitRight ? "r" : "l"}`, exitC, entryC, exitRight, entryLeft, corridor };
  });

  // box-side ports: one per trunk leaving the side, one per trunk arriving at it; spawns above checks
  const sides = new Map<string, string[]>();
  const add = (k: string, v: string) => { const l = sides.get(k) ?? sides.set(k, []).get(k)!; if (!l.includes(v)) l.push(v); };
  for (const p of plans) {
    add(`${p.e.from}:${p.exitRight ? "r" : "l"}`, `out:${p.group}`);
    add(`${p.e.to}:${p.entryLeft ? "l" : "r"}`, `in:${p.group}`);
  }
  for (const l of sides.values()) l.sort((a, b) => Number(a.includes(":check:")) - Number(b.includes(":check:")));
  const port = (box: string, right: boolean, key: string) => {
    const l = sides.get(`${box}:${right ? "r" : "l"}`)!;
    return spread(l.indexOf(key), l.length, GRID.H - 18);
  };

  // lanes: one per trunk in each channel / corridor it uses, ordered by where its branches go
  const chans = new Map<number, Map<string, number>>(); const cors = new Map<number, string[]>();
  for (const p of plans) {
    for (const c of new Set([p.exitC, p.entryC])) {
      const m = chans.get(c) ?? chans.set(c, new Map()).get(c)!;
      // a branch that ends at a box LEFT of this channel pulls the trunk left (-1), one to the right pushes it (+1)
      const dir = c === p.entryC ? (p.entryLeft ? 1 : -1) : (p.exitRight ? 1 : -1);
      m.set(p.group, (m.get(p.group) ?? 0) + dir + (p.kind === "check" ? 0.1 : 0));
    }
    if (p.corridor !== null) { const l = cors.get(p.corridor) ?? cors.set(p.corridor, []).get(p.corridor)!; if (!l.includes(p.group)) l.push(p.group); }
  }
  const order = new Map([...chans].map(([c, m]) => [c, [...m.entries()].sort((a, b) => a[1] - b[1]).map(([g]) => g)]));
  const chanX = (c: number, g: string) => { const l = order.get(c)!; return channelX(c) + spread(l.indexOf(g), l.length, GRID.COLGAP - 28); };
  const corY = (r: number, g: string) => { const l = cors.get(r)!; return corridorY(r) + spread(l.indexOf(g), l.length, GRID.ROWGAP - 12); };

  const routes: Routed[] = plans.map((p) => {
    const sr = cellRect(p.s.col, p.s.row); const tr = cellRect(p.t.col, p.t.row);
    const sy = sr.y + sr.height / 2 + port(p.e.from, p.exitRight, `out:${p.group}`);
    const ty = tr.y + tr.height / 2 + port(p.e.to, !p.entryLeft, `in:${p.group}`);
    const start = { x: p.exitRight ? sr.x + sr.width : sr.x, y: sy };
    const end = { x: p.entryLeft ? tr.x : tr.x + tr.width, y: ty };
    const cx1 = chanX(p.exitC, p.group); const cx2 = chanX(p.entryC, p.group);
    const points = p.corridor === null
      ? [start, { x: cx1, y: sy }, { x: cx1, y: ty }, end]
      : [start, { x: cx1, y: sy }, { x: cx1, y: corY(p.corridor, p.group) }, { x: cx2, y: corY(p.corridor, p.group) }, { x: cx2, y: ty }, end];
    return { id: p.e.id, from: p.e.from, to: p.e.to, kind: p.kind, points };
  });
  return { routes, rows };
}

/** How many times two routes of DIFFERENT trunks cross (a proper crossing of a horizontal and a vertical run). */
export function crossings(routes: Routed[]): number {
  const segs = routes.flatMap((r) => r.points.slice(1).map((b, i) => ({ g: `${r.from}:${r.kind}`, a: r.points[i], b })));
  const h = segs.filter((s) => s.a.y === s.b.y && s.a.x !== s.b.x); const v = segs.filter((s) => s.a.x === s.b.x && s.a.y !== s.b.y);
  const seen = new Set<string>();
  for (const x of h) for (const y of v) {
    if (x.g === y.g) continue;
    const [x0, x1] = [Math.min(x.a.x, x.b.x), Math.max(x.a.x, x.b.x)]; const [y0, y1] = [Math.min(y.a.y, y.b.y), Math.max(y.a.y, y.b.y)];
    if (y.a.x > x0 + 0.5 && y.a.x < x1 - 0.5 && x.a.y > y0 + 0.5 && x.a.y < y1 - 0.5) seen.add(`${y.a.x.toFixed(1)},${x.a.y.toFixed(1)}`);
  }
  return seen.size;
}

export function overlaps(a: Rect, b: Rect, pad = 0): boolean {
  return a.x < b.x + b.width + pad && b.x < a.x + a.width + pad && a.y < b.y + b.height + pad && b.y < a.y + a.height + pad;
}

/** Does the polyline pass through the inside of `r`? (Sampled every 2px along each segment.) */
export function crosses(points: Pt[], r: Rect): boolean {
  for (let k = 0; k + 1 < points.length; k++) {
    const a = points[k]; const b = points[k + 1];
    const n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / 2));
    for (let j = 0; j <= n; j++) {
      const x = a.x + ((b.x - a.x) * j) / n; const y = a.y + ((b.y - a.y) * j) / n;
      if (x > r.x + 1 && x < r.x + r.width - 1 && y > r.y + 1 && y < r.y + r.height - 1) return true;
    }
  }
  return false;
}

export const polyline = (pts: Pt[]) => pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
