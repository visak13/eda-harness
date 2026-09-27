// The Standard workflow's roles graph as qa saw it (m-e633397a42): owner spawns everyone, architect spawns in the
// same column, qa/adversary check builders in their own column — the shapes that used to cross boxes.
import type { EdgeIn } from "./pipelineLayout";

export function build_standard_like(): { cells: Map<string, { col: number; row: number }>; edges: EdgeIn[] } {
  const cells = new Map<string, { col: number; row: number }>([
    ["owner", { col: 0, row: 0 }],
    ["architect", { col: 1, row: 0 }], ["engineer", { col: 1, row: 1 }], ["adversary", { col: 1, row: 2 }],
    ["qa", { col: 1, row: 3 }], ["doctor", { col: 1, row: 4 }],
    ["sme", { col: 2, row: 0 }],
  ]);
  const spawn = (a: string, b: string): EdgeIn => ({ id: `spawn-edge-${a}-${b}`, from: a, to: b });
  const check = (a: string, b: string, k: string): EdgeIn => ({ id: `check-edge-${a}-${b}`, from: a, to: b, label: `checks ${k}` });
  const edges = [
    ...["architect", "engineer", "adversary", "qa", "doctor"].map((r) => spawn("owner", r)),
    ...["engineer", "adversary", "qa", "sme"].map((r) => spawn("architect", r)),
    check("engineer", "sme", "task"),
    check("qa", "engineer", "epic, story"), check("qa", "sme", "epic, story"),
    check("adversary", "engineer", "epic, story"), check("adversary", "sme", "epic, story"),
  ];
  return { cells, edges };
}
