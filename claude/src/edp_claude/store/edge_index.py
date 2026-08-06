"""The graph overlay — a deterministic SQLite edge index over the JSON stores.

WHY THIS EXISTS (v7 WS3, §2.1b). The durable objects already carry typed links
(`Decision.affects`, `RecipeStep.serves`, `Action.serves`, `depends_on`,
`spec_ids`, `plan_ref`); this module materializes them as edges so retrieval
becomes selection: transitive impact for scoped invalidation ("revise d12 →
which shells actually need a delta?"), neighborhood packs for grounding, and
orphan detection (a step serving no outcome, a test verifying a dead target).

DESIGN RULES
  * The index is DERIVED STATE: `rebuild()` drops and rescans the raw store
    JSON. Corruption is repaired by rebuild, never migration. Files stay the
    substrate and stay diffable.
  * Edges are derived from SCHEMA-VALIDATED FIELDS only — never LLM-authored
    into the graph directly. The write-gate quality of the stores carries over.
  * Node ids are QUALIFIED, because bare action/step ids are only meaningful
    relative to their plan/recipe (the s26 item-13 aliasing lesson):
      recipe:<rid>  plan:<pid>  step:<rid>:<sid>  action:<pid>:<aid>
      outcome:<rid>:<oid>  decision:<rid>:<did>  assumption:<rid>:<aid>
      spec:<spec_id>  test:<test_id>  file:<relpath>
  * TEST LINEAGE (§2.5b) is the one non-derived table: tests are registered
    by the worker's write path (`record_test`) and SURVIVE rebuilds — the
    stores don't know about test files, but retirement queries must.
  * Raw-JSON scan, not model load: the index tolerates every historical store
    shape (missing keys are just absent edges) and never hydrates sidecars.

Reads no env at import; `EDP_GRAPH_DB` overrides the db path at call time.
"""

import json
import os
import sqlite3
from pathlib import Path

_DB_ENV = "EDP_GRAPH_DB"

#: rels derived by rebuild() — dropped and rescanned every time.
DERIVED_RELS = ("affects", "serves", "depends_on", "spec", "plan_ref",
                "part_of")
#: rels registered by write paths — survive rebuild().
REGISTERED_RELS = ("verifies", "covers")


def db_path(agent_home: str | os.PathLike) -> Path:
    override = os.environ.get(_DB_ENV, "").strip()
    if override:
        return Path(override)
    return Path(agent_home) / ".graph" / "edges.db"


def connect(agent_home: str | os.PathLike) -> sqlite3.Connection:
    p = db_path(agent_home)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE IF NOT EXISTS edges("
        "  src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL,"
        "  PRIMARY KEY(src, rel, dst));"
        "CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);"
        "CREATE TABLE IF NOT EXISTS nodes("
        "  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS test_edges("
        "  src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL,"
        "  PRIMARY KEY(src, rel, dst));")
    return con


# ── rebuild (derived edges + nodes) ──────────────────────────────────────────
def _iter_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _scan_recipe(rid: str, r: dict, add_edge, add_node) -> None:
    add_node(f"recipe:{rid}", "recipe", str(r.get("state", "")))
    comp = r.get("comprehension") or {}
    for o in comp.get("expected_outcomes") or []:
        oid = o.get("id")
        if oid:
            add_node(f"outcome:{rid}:{oid}", "outcome",
                     "met" if o.get("met") else "unmet")
    step_ids = set()
    for s in r.get("steps") or []:
        sid = s.get("step_id")
        if not sid:
            continue
        step_ids.add(sid)
        n = f"step:{rid}:{sid}"
        add_node(n, "step", str(s.get("status", "")))
        add_edge(n, "part_of", f"recipe:{rid}")
        for dep in s.get("depends_on") or []:
            add_edge(n, "depends_on", f"step:{rid}:{dep}")
        for oid in s.get("serves") or []:
            add_edge(n, "serves", f"outcome:{rid}:{oid}")
        if s.get("plan_ref"):
            add_edge(n, "plan_ref", f"plan:{s['plan_ref']}")
    ctx = r.get("context") or {}
    for kind, key in (("decision", "decisions"), ("assumption", "assumptions")):
        for d in ctx.get(key) or []:
            did = d.get("id")
            if not did:
                continue
            n = f"{kind}:{rid}:{did}"
            add_node(n, kind, str(d.get("status", "active")))
            for target in d.get("affects") or []:
                # a bare id resolves against this recipe's steps; anything
                # else is taken as already-qualified (`action:<pid>:<aid>`,
                # `step:<rid>:<sid>`, …) or a plan-relative action the plan
                # scan will have qualified — conservative: keep the raw form
                # so an unresolvable target is visible, never dropped.
                if target in step_ids:
                    add_edge(n, "affects", f"step:{rid}:{target}")
                else:
                    add_edge(n, "affects", target if ":" in target
                             else f"unresolved:{rid}:{target}")


def _scan_plan(pid: str, p: dict, add_edge, add_node) -> None:
    rid = p.get("recipe_id", "")
    add_node(f"plan:{pid}", "plan", str(p.get("state", "")))
    if rid and p.get("recipe_step_id"):
        add_edge(f"plan:{pid}", "part_of",
                 f"step:{rid}:{p['recipe_step_id']}")
    for a in p.get("actions") or []:
        aid = a.get("action_id")
        if not aid:
            continue
        n = f"action:{pid}:{aid}"
        add_node(n, "action", str(a.get("status", "")))
        add_edge(n, "part_of", f"plan:{pid}")
        for dep in a.get("depends_on") or []:
            add_edge(n, "depends_on", f"action:{pid}:{dep}")
        for oid in a.get("serves") or []:
            add_edge(n, "serves", f"outcome:{rid}:{oid}")
        for spec in (a.get("spec_ids") or
                     ([a["spec_id"]] if a.get("spec_id") else [])):
            add_edge(n, "spec", f"spec:{spec}")


def rebuild(agent_home: str | os.PathLike) -> dict:
    """Drop + rescan every derived edge/node from the raw store JSON.
    `test_edges` (registered lineage) survives untouched. Returns counts."""
    home = Path(agent_home)
    con = connect(home)
    try:
        con.execute("DELETE FROM edges")
        con.execute("DELETE FROM nodes")
        edges: set[tuple[str, str, str]] = set()
        nodes: dict[str, tuple[str, str]] = {}

        def add_edge(src: str, rel: str, dst: str) -> None:
            edges.add((src, rel, dst))

        def add_node(nid: str, kind: str, status: str) -> None:
            nodes[nid] = (kind, status)

        recipes_root = home / ".recipes"
        if recipes_root.is_dir():
            for rj in sorted(recipes_root.glob("*/recipe.json")):
                r = _iter_json(rj)
                if r and r.get("recipe_id"):
                    _scan_recipe(r["recipe_id"], r, add_edge, add_node)
        plans_root = home / ".plans"
        if plans_root.is_dir():
            for pj in sorted(plans_root.glob("*.json")):
                p = _iter_json(pj)
                if p and p.get("plan_id"):
                    _scan_plan(p["plan_id"], p, add_edge, add_node)

        con.executemany("INSERT OR REPLACE INTO edges VALUES (?,?,?)",
                        sorted(edges))
        con.executemany("INSERT OR REPLACE INTO nodes VALUES (?,?,?)",
                        [(k, v[0], v[1]) for k, v in sorted(nodes.items())])
        con.commit()
        return {"edges": len(edges), "nodes": len(nodes)}
    finally:
        con.close()


# ── test lineage (registered, survives rebuild) ──────────────────────────────
def record_test(agent_home: str | os.PathLike, *, test_id: str,
                verifies: list[str], covers: list[str],
                layer: str = "unit") -> None:
    """Register a test's reason-to-exist (§2.5b). `verifies` targets are
    qualified node ids (outcome:<rid>:<oid> / action:<pid>:<aid>); `covers`
    are repo-relative file paths. A test with no `verifies` target is the
    false-security test — the WRITE PATH refuses it here, at the seam."""
    if not test_id or not test_id.strip():
        raise ValueError("test_id is required")
    if not verifies:
        raise ValueError(
            f"test {test_id!r} verifies nothing — a test with no acceptance/"
            f"outcome target is exactly the false-security class the lineage "
            f"exists to prevent; name what it proves or do not register it.")
    if layer not in ("unit", "integration", "e2e"):
        raise ValueError(f"layer must be unit|integration|e2e, got {layer!r}")
    con = connect(agent_home)
    try:
        rows = ([(f"test:{test_id}", "verifies", v) for v in verifies]
                + [(f"test:{test_id}", "covers", f"file:{c}") for c in covers]
                + [(f"test:{test_id}", "layer", f"layer:{layer}")])
        con.executemany("INSERT OR REPLACE INTO test_edges VALUES (?,?,?)",
                        rows)
        con.commit()
    finally:
        con.close()


def layer_counts(agent_home: str | os.PathLike) -> dict[str, int]:
    """Registered tests per layer — the test_budget comparison input
    (§2.5b): a plan's stamped pyramid (e.g. e2e_max) is checked against
    THIS, mechanically, instead of a reviewer eyeballing a test tree."""
    con = connect(agent_home)
    try:
        rows = con.execute(
            "SELECT dst, count(DISTINCT src) FROM test_edges "
            "WHERE rel='layer' GROUP BY dst").fetchall()
        return {dst.split(":", 1)[1]: n for dst, n in rows}
    finally:
        con.close()


# ── queries ──────────────────────────────────────────────────────────────────
def _all_edges(con) -> list[tuple[str, str, str]]:
    return list(con.execute("SELECT src, rel, dst FROM edges UNION ALL "
                            "SELECT src, rel, dst FROM test_edges"))


def impacted_by(agent_home: str | os.PathLike, node: str,
                transitive: bool = True) -> set[str]:
    """Everything downstream of `node`: its `affects`/`serves` targets, plus
    (transitively) every dependent — X depends_on Y and Y impacted → X
    impacted. This is the scoped-invalidation query: revise a decision, wake
    only shells whose handle intersects this set."""
    con = connect(agent_home)
    try:
        fwd: dict[str, set[str]] = {}
        dependents: dict[str, set[str]] = {}
        for src, rel, dst in _all_edges(con):
            if rel in ("affects", "serves"):
                fwd.setdefault(src, set()).add(dst)
            elif rel == "depends_on":
                dependents.setdefault(dst, set()).add(src)
        out: set[str] = set()
        # seed with BOTH what the node points at (affects/serves) and what
        # depends on the node itself — a done action's dependents are
        # impacted even though no forward edge leaves it.
        frontier = set(fwd.get(node, set())) | set(dependents.get(node, set()))
        while frontier:
            out |= frontier
            if not transitive:
                break
            nxt: set[str] = set()
            for n in frontier:
                nxt |= dependents.get(n, set()) - out
                nxt |= fwd.get(n, set()) - out
            frontier = nxt
        return out
    finally:
        con.close()


def neighborhood(agent_home: str | os.PathLike, node: str,
                 depth: int = 1) -> list[tuple[str, str, str]]:
    """The undirected edge set within `depth` hops of `node` — the grounding
    pack selector (a worker sees sibling actions on its surfaces, decisions
    touching its files) without ever dumping the graph."""
    con = connect(agent_home)
    try:
        edges = _all_edges(con)
        seen = {node}
        out: list[tuple[str, str, str]] = []
        picked: set[tuple[str, str, str]] = set()
        for _ in range(max(1, depth)):
            # snapshot the frontier: edges are matched against the PRE-round
            # `seen` so one round = exactly one hop (mutating `seen` mid-scan
            # would leak depth-1 into depth-N depending on edge order).
            frontier = set(seen)
            grew = False
            for e in edges:
                if e in picked or not (e[0] in frontier or e[2] in frontier):
                    continue
                picked.add(e)
                out.append(e)
                if e[0] not in seen or e[2] not in seen:
                    grew = True
                seen.add(e[0])
                seen.add(e[2])
            if not grew:
                break
        return out
    finally:
        con.close()


def orphan_steps(agent_home: str | os.PathLike) -> list[str]:
    """Steps with NO `serves` edge — work no declared outcome asked for.
    Legacy steps predate the field, so this is a report, not an error; for
    NEW declarations the write gate refuses orphans up front."""
    con = connect(agent_home)
    try:
        rows = con.execute(
            "SELECT id FROM nodes WHERE kind='step' AND id NOT IN "
            "(SELECT src FROM edges WHERE rel='serves')").fetchall()
        return sorted(r[0] for r in rows)
    finally:
        con.close()


def dead_tests(agent_home: str | os.PathLike) -> list[tuple[str, str]]:
    """Registered tests whose `verifies` target no longer exists in the
    rebuilt node set — the stale-contract class (§2.5b): a retired feature's
    tests surface HERE mechanically, instead of relying on a planner's
    memory. Returns (test_node, dead_target) pairs → retirement actions."""
    con = connect(agent_home)
    try:
        rows = con.execute(
            "SELECT t.src, t.dst FROM test_edges t WHERE t.rel='verifies' "
            "AND t.dst NOT IN (SELECT id FROM nodes)").fetchall()
        return sorted((r[0], r[1]) for r in rows)
    finally:
        con.close()


def tests_covering(agent_home: str | os.PathLike,
                   files: list[str]) -> list[str]:
    """The impacted-test set for a change (§2.5b selective execution):
    registered tests whose `covers` hits any of `files`. Reviewers run THIS,
    not the world; the full suite runs at step/recipe close."""
    con = connect(agent_home)
    try:
        targets = {f"file:{f}" for f in files}
        rows = con.execute(
            "SELECT DISTINCT src FROM test_edges WHERE rel='covers'").fetchall()
        out = set()
        for (src,) in rows:
            hits = con.execute(
                "SELECT dst FROM test_edges WHERE src=? AND rel='covers'",
                (src,)).fetchall()
            if targets & {h[0] for h in hits}:
                out.add(src)
        return sorted(out)
    finally:
        con.close()
