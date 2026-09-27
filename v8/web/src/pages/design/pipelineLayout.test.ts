// t-67d19c5807 (qa m-e633397a42): the pipeline drawing's geometry — the flow fits its box, labels wrap at words,
// roles-graph edges never cross a box they don't start or end at, and each role's arrows share one trunk.
import { describe, expect, it } from "vitest";
import { build_standard_like } from "./pipelineLayout.fixture";
import { FLOW, cellRect, crosses, crossings, flowSlots, flowWidth, placeCells, routeRoles, wrapWords } from "./pipelineLayout";

describe("wrapWords", () => {
  it("breaks only between words and never drops or cuts one", () => {
    const text = "architect, owner, engineer, sme, board (auto)";
    const lines = wrapWords(text, 20);
    expect(lines.join(" ")).toBe(text);
    for (const l of lines) expect(l.length).toBeLessThanOrEqual(20);
    expect(wrapWords("supercalifragilistic-word short", 8)).toEqual(["supercalifragilistic-word", "short"]);
  });
});

describe("flowSlots", () => {
  it("wraps the 7-status main path so every status fits the measured box", () => {
    for (const avail of [560, 770, 900, 1300]) {
      const { perRow, at } = flowSlots(7, avail);
      expect(at).toHaveLength(7);
      expect(flowWidth(perRow)).toBeLessThanOrEqual(Math.max(avail, flowWidth(3)));
      for (const a of at) expect(FLOW.PAD + a.slot * FLOW.GAP + FLOW.SW).toBeLessThanOrEqual(flowWidth(perRow));
    }
    expect(flowSlots(7, 1300).at.every((a) => a.row === 0)).toBe(true);
    expect(flowSlots(7, 0).at.every((a) => a.row === 0)).toBe(true); // unmeasured: one row
    const wrapped = flowSlots(7, 770).at;
    expect(new Set(wrapped.map((a) => a.row)).size).toBeGreaterThan(1);
    expect(wrapped.filter((a) => a.row > 0).every((a) => a.slot >= 1)).toBe(true); // wrap arrow comes in from slot 0
  });
});

describe("routeRoles", () => {
  const { cells, edges } = build_standard_like();
  const { routes } = routeRoles(cells, edges);
  const boxes = [...cells.entries()].map(([id, c]) => ({ id, ...cellRect(c.col, c.row) }));

  it("routes every edge", () => expect(routes.map((r) => r.id).sort()).toEqual(edges.map((e) => e.id).sort()));

  it("no edge runs through a box it doesn't start or end at", () => {
    for (const r of routes) for (const b of boxes) {
      if (b.id === r.from || b.id === r.to) continue;
      expect(crosses(r.points, b), `${r.id} through ${b.id}`).toBe(false);
    }
  });

  it("one source's arrows of one kind leave as one trunk: same exit point, same lane", () => {
    const groups = new Map<string, typeof routes>();
    for (const r of routes) (groups.get(`${r.from}:${r.kind}`) ?? groups.set(`${r.from}:${r.kind}`, []).get(`${r.from}:${r.kind}`)!).push(r);
    for (const [g, rs] of groups) {
      expect(new Set(rs.map((r) => `${r.points[0].x},${r.points[0].y}`)).size, `${g} exit point`).toBe(1);
      expect(new Set(rs.map((r) => r.points[1].x)).size, `${g} lane`).toBe(1);
    }
  });

  it("crosses itself far less than the one-lane-per-edge router did (33 crossings on this graph)", () => {
    expect(crossings(routes)).toBeLessThanOrEqual(10);
  });
});

describe("placeCells", () => {
  it("puts a later role beside the roles that start it, one role per cell", () => {
    const spawn = (a: string, b: string) => ({ id: `${a}-${b}`, from: a, to: b, kind: "spawn" as const });
    const cells = placeCells([["owner"], ["architect", "engineer", "qa"], ["sme"]],
      [spawn("owner", "architect"), spawn("owner", "engineer"), spawn("owner", "qa"), spawn("architect", "sme"),
        { id: "qa-sme", from: "qa", to: "sme", kind: "check" }]);
    expect(cells.get("sme")).toEqual({ col: 2, row: 0 }); // beside architect; the check from qa does not pull it down
    expect([...cells.values()].map((c) => `${c.col}:${c.row}`).length).toBe(new Set([...cells.values()].map((c) => `${c.col}:${c.row}`)).size);
    expect(["architect", "engineer", "qa"].map((id) => cells.get(id)!.row)).toEqual([0, 1, 2]);
  });
});
