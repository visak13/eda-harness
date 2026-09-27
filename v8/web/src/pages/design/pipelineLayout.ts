// t-67d19c5807 (qa m-e633397a42): pure geometry for the Design tab's pipeline drawing, kept apart from React so
// vitest can prove the properties the drawing promises: the status flow wraps into rows that fit the box (so
// "done" is never off-canvas), actor labels wrap at word boundaries (never a mid-word cut), and every
// roles-graph edge runs only through the empty channels between columns and corridors between rows, so no
// edge crosses a box it does not start or end at and no label sits on a box.

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

export const GRID = { W: 164, H: 46, COLGAP: 96, ROWGAP: 34, PADX: 20, PADY: 30 } as const;

export function cellRect(col: number, row: number): Rect {
  return { x: GRID.PADX + col * (GRID.W + GRID.COLGAP), y: GRID.PADY + row * (GRID.H + GRID.ROWGAP), width: GRID.W, height: GRID.H };
}

/** x of channel c: the empty strip LEFT of column c (c = cols is right of the last column). */
const channelX = (c: number) => GRID.PADX + c * (GRID.W + GRID.COLGAP) - GRID.COLGAP / 2;
/** y of corridor r: the empty strip ABOVE row r (r = rows is below the last row). */
const corridorY = (r: number) => GRID.PADY + r * (GRID.H + GRID.ROWGAP) - GRID.ROWGAP / 2;

export interface EdgeIn { id: string; from: string; to: string; label?: string }
export interface Routed { id: string; from: string; to: string; points: Pt[]; label?: { text: string; x: number; y: number; box: Rect } }

const lane = (i: number, n: number, room: number) => {
  const step = n > 1 ? Math.min(8, room / (n - 1)) : 0;
  return (i - (n - 1) / 2) * step;
};

/** Orthogonal routes: out of the source's side into the channel beside it, along a corridor between rows when
 *  the target sits in another column, down the channel beside the target and into its side. Channels and
 *  corridors hold no boxes, so a route touches only its own two boxes. Edges sharing a channel, corridor or
 *  box side get their own lane/port offset. Labels go to the first spot along their route that touches no box
 *  and no other label; failing that, they are stacked in a strip under the graph (`extraHeight`). */
export function routeRoles(cells: Map<string, { col: number; row: number }>, edges: EdgeIn[]): { routes: Routed[]; extraHeight: number; rows: number } {
  const rows = Math.max(1, ...[...cells.values()].map((c) => c.row + 1));
  const plans = edges.filter((e) => cells.has(e.from) && cells.has(e.to) && e.from !== e.to).map((e) => {
    const s = cells.get(e.from)!; const t = cells.get(e.to)!;
    let exitC: number; let entryC: number; let exitRight: boolean; let entryLeft: boolean;
    if (t.col > s.col) { exitC = s.col + 1; entryC = t.col; exitRight = true; entryLeft = true; }
    else if (t.col < s.col) { exitC = s.col; entryC = t.col + 1; exitRight = false; entryLeft = false; }
    else { exitC = entryC = s.col + 1; exitRight = true; entryLeft = false; }
    const corridor = exitC === entryC ? null : (t.row >= s.row ? t.row : t.row + 1);
    return { e, s, t, exitC, entryC, exitRight, entryLeft, corridor };
  });
  // ports: spread the edges leaving/entering the same box side along that side
  const sides = new Map<string, number[]>();
  const sideKey = (id: string, right: boolean) => `${id}:${right ? "r" : "l"}`;
  plans.forEach((p, i) => {
    (sides.get(sideKey(p.e.from, p.exitRight)) ?? sides.set(sideKey(p.e.from, p.exitRight), []).get(sideKey(p.e.from, p.exitRight))!).push(i);
    (sides.get(sideKey(p.e.to, !p.entryLeft)) ?? sides.set(sideKey(p.e.to, !p.entryLeft), []).get(sideKey(p.e.to, !p.entryLeft))!).push(i);
  });
  const port = (id: string, right: boolean, i: number) => {
    const list = sides.get(sideKey(id, right))!;
    return lane(list.indexOf(i), list.length, GRID.H - 16);
  };
  // lanes: one per edge in each channel and corridor it uses
  const chans = new Map<number, number[]>(); const cors = new Map<number, number[]>();
  plans.forEach((p, i) => {
    for (const c of new Set([p.exitC, p.entryC])) (chans.get(c) ?? chans.set(c, []).get(c)!).push(i);
    if (p.corridor !== null) (cors.get(p.corridor) ?? cors.set(p.corridor, []).get(p.corridor)!).push(i);
  });
  const chanX = (c: number, i: number) => channelX(c) + lane(chans.get(c)!.indexOf(i), chans.get(c)!.length, GRID.COLGAP - 36);
  const corY = (r: number, i: number) => corridorY(r) + lane(cors.get(r)!.indexOf(i), cors.get(r)!.length, GRID.ROWGAP - 18) * 0.5;

  const boxes = [...cells.values()].map((c) => cellRect(c.col, c.row));
  const placed: Rect[] = [];
  const hits = (r: Rect) => boxes.some((b) => overlaps(r, b, 3)) || placed.some((b) => overlaps(r, b, 2));
  const bottom = GRID.PADY + rows * (GRID.H + GRID.ROWGAP) - GRID.ROWGAP;
  let stacked = 0;
  const routes: Routed[] = plans.map((p, i) => {
    const sr = cellRect(p.s.col, p.s.row); const tr = cellRect(p.t.col, p.t.row);
    const sy = sr.y + sr.height / 2 + port(p.e.from, p.exitRight, i);
    const ty = tr.y + tr.height / 2 + port(p.e.to, !p.entryLeft, i);
    const start = { x: p.exitRight ? sr.x + sr.width : sr.x, y: sy };
    const end = { x: p.entryLeft ? tr.x : tr.x + tr.width, y: ty };
    const cx1 = chanX(p.exitC, i); const cx2 = chanX(p.entryC, i);
    const points = p.corridor === null
      ? [start, { x: cx1, y: sy }, { x: cx1, y: ty }, end]
      : [start, { x: cx1, y: sy }, { x: cx1, y: corY(p.corridor, i) }, { x: cx2, y: corY(p.corridor, i) }, { x: cx2, y: ty }, end];
    const out: Routed = { id: p.e.id, from: p.e.from, to: p.e.to, points };
    if (p.e.label) {
      const w = p.e.label.length * CHAR_W + 6; const h = 13;
      const spots: Pt[] = [];
      for (let k = 0; k + 1 < points.length; k++) {
        const a = points[k]; const b = points[k + 1];
        for (const f of [0.5, 0.3, 0.7, 0.15, 0.85]) spots.push({ x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f });
      }
      let at: Rect | null = null;
      for (const sp of spots) {
        for (const dy of [-h / 2 - 3, h / 2 + 3, 0]) {
          const r = { x: sp.x - w / 2, y: sp.y + dy - h / 2, width: w, height: h };
          if (r.x >= 0 && r.y >= 0 && !hits(r)) { at = r; break; }
        }
        if (at) break;
      }
      if (!at) { at = { x: GRID.PADX, y: bottom + 12 + stacked * (h + 4), width: w, height: h }; stacked += 1; }
      placed.push(at);
      out.label = { text: p.e.label, x: at.x + at.width / 2, y: at.y + h - 3, box: at };
    }
    return out;
  });
  return { routes, extraHeight: stacked ? 12 + stacked * 17 : 0, rows };
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
