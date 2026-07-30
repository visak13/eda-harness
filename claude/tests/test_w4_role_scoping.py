"""DESIGN-v6 W4 REMEDIATION — planner object-CRUD floor + warn-then-enforce
per-role/per-object-type scoping (recipe …-eaa75d s8/a2; decisions d14/d15).

Covers the three coordinated changes:
  (1) roles.py — the planner ROLE_TOOLSETS floor regains update_object +
      delete_object (NOT create_object), matching the derived snapshot.
  (2) _tools.py — an in-tool per-role/per-object-type CRUD guard on
      create_object/update_object/delete_object, governed by EDP_ROLE_SCOPE.
  (3) mcp_server.py — the build_mcp seam reads EDP_ROLE_SCOPE (warn|enforce,
      DEFAULT warn): warn registers the full surface and logs off-set CALLS;
      enforce filters the registry to the role's set.

FLOOR-TEST SCOPE (deliberate, confirmed by the planner + neuron this step).
The FLOOR TEST here regenerates the OBJECT-CRUD floor from the derived
snapshot (docs/design/v6-audit/role-toolsets-derived.md) and asserts each
role reproduces it EXACTLY — this is the dimension the W4 regression actually
governs (a planner was trimmed BELOW its create/update/delete floor). It is
NOT a full-inventory exact reproduction of every tool the guides mention,
because that is currently blocked by design, not by this code:
  • REVIEWER scope enforcement is DEFERRED (role-toolsets-derived.md ‡ / d14)
    until the assemble_ruleset read-composition question is resolved, and the
    reviewer surface sits AT its ceiling (14);
  • the planner floor's non-CRUD guide-union reconciliation (status_ping,
    neuron_search, broker_send, get_specialist_doc, …) is out of THIS step's
    scope and lands with the s9 guide-sync sweep.
So a full-inventory superset assertion would be un-green for reasons unrelated
to this remediation; the CRUD-dimension reproduction is the meaningful,
regression-locking check for W4.

ENV DISCIPLINE (d7/d8). Every test that touches role-scoped registration,
EDP_HANDLE resolution or the CRUD guard controls EDP_ROLE / EDP_HANDLE /
EDP_ROLE_SCOPE EXPLICITLY via monkeypatch (a spawned worker/planner shell
leaks these and pytest subprocesses inherit them). The acceptance gate
neutralises the env with a shell `unset` (NOT an `env -` prefix — this host's
verify bash has no `env` binary, d8).
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools import build_registry
from edp_claude.tools._tools import ALL_TOOL_CLASSES, record_role_scope_violation
from edp_claude.tools.roles import (
    CRUD_OBJECT_SCOPE,
    ROLE_TOOLSETS,
    crud_scope_violation,
)

CRUD_VERBS = ("create_object", "update_object", "delete_object")


# ── helpers ─────────────────────────────────────────────────────────────────
def _now():
    return datetime.now(timezone.utc)


def _save_recipe(ctx, rid):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now(),
    ))


def _save_plan_with_action(ctx, rid, plan_id):
    # two independent actions: on-role tests update a1 and delete a2 (a2 has no
    # dependents, so its deletion is a clean advisory delete, not a hard-block).
    def _act(aid):
        return Action(
            action_id=aid, description=f"do {aid}",
            status="pending", executor_mode="inline",
            acceptance=Acceptance(kind="manual_review", expected="x"))
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=[_act("a1"), _act("a2")]))


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


def _violations(ctx, plan_id):
    return [e for e in ctx.plans.read_worklog(plan_id, tail=50)
            if e.get("kind") == "role_scope_violation"]


# ════════════════════════════════════════════════════════════════════════════
# (i) FLOOR TEST — reproduce the derived-snapshot object-CRUD grant EXACTLY
# ════════════════════════════════════════════════════════════════════════════
def _derived_doc_crud_floor() -> dict[str, set[str]]:
    """Regenerate the per-role object-CRUD floor FROM the derived snapshot.

    The generic object-CRUD verbs are listed ONLY in a role's inventory
    backtick list in role-toolsets-derived.md, so a section-scoped
    backticked-verb membership test reproduces the snapshot's grant exactly
    (the prose "CRUD object-types:" lines name object TYPES, not the verbs,
    and never in backticks — so they don't false-match)."""
    doc = (Path(__file__).resolve().parents[1] / "docs" / "design"
           / "v6-audit" / "role-toolsets-derived.md")
    text = doc.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    cur, buf = None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+([A-Z][A-Z /-]*?)\s*$", line)
        if m:
            if cur is not None:
                sections[cur] = "\n".join(buf)
            cur, buf = m.group(1).strip().lower(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf)
    return {role: {v for v in CRUD_VERBS if f"`{v}`" in body}
            for role, body in sections.items()}


def test_floor_reproduces_derived_crud_grant_exactly():
    floor = _derived_doc_crud_floor()
    # parser sanity — a silently-empty parse must not vacuously pass. The
    # neuron is the one role granted the full generic CRUD in the snapshot.
    assert floor.get("neuron") == set(CRUD_VERBS), floor.get("neuron")

    crud = set(CRUD_VERBS)
    checked = 0
    for role in ("neuron", "planner", "worker", "reviewer", "specialist"):
        assert role in floor, f"derived doc has no ## {role.upper()} section"
        assert role in ROLE_TOOLSETS, role
        got = set(ROLE_TOOLSETS[role]) & crud
        want = floor[role]
        assert got == want, (
            f"role {role!r} object-CRUD grant {sorted(got)} does not "
            f"reproduce the derived snapshot floor {sorted(want)} "
            "(update roles.py, not this assertion)")
        checked += 1
    assert checked == 5


def test_planner_floor_regains_update_and_delete_not_create():
    # the exact W4 regression + its inverse: update_object + delete_object are
    # restored; create_object is NOT granted (the planner creates via
    # create_plan / add_action, never the generic verb).
    ps = ROLE_TOOLSETS["planner"]
    assert "update_object" in ps
    assert "delete_object" in ps
    assert "create_object" not in ps


def test_worker_object_crud_is_readonly_but_keeps_status():
    ws = ROLE_TOOLSETS["worker"]
    assert set(CRUD_VERBS).isdisjoint(ws)
    assert {"read_object", "query_objects", "describe_objects"} <= ws
    assert "record_action_status" in ws


# ════════════════════════════════════════════════════════════════════════════
# (ii) CRUD SCOPE PREDICATE — pure policy (roles.crud_scope_violation)
# ════════════════════════════════════════════════════════════════════════════
def test_crud_scope_predicate_on_and_off_scope():
    # on-scope → None
    assert crud_scope_violation("planner", "plan") is None
    assert crud_scope_violation("planner", "action") is None
    assert crud_scope_violation("neuron", "recipe") is None
    assert crud_scope_violation("neuron", "step") is None
    # off-object-type → message names role + allowed types
    msg = crud_scope_violation("planner", "recipe")
    assert msg is not None and "planner" in msg and "action" in msg
    # a read-only role → every object-type is a violation
    v = crud_scope_violation("worker", "action")
    assert v is not None and "read-only" in v
    # fail-open — absent/blank/unknown role is unconstrained (human foreground)
    assert crud_scope_violation(None, "recipe") is None
    assert crud_scope_violation("", "recipe") is None
    assert crud_scope_violation("totally-unknown-role", "recipe") is None


def test_crud_object_scope_table_matches_the_snapshot():
    # planner = plan + action ONLY; neuron additionally recipe/step/north_star.
    assert CRUD_OBJECT_SCOPE["planner"] == frozenset({"plan", "action"})
    assert {"recipe", "step", "north_star"} <= CRUD_OBJECT_SCOPE["neuron"]
    for readonly in ("worker", "reviewer", "specialist", "consult"):
        assert CRUD_OBJECT_SCOPE[readonly] == frozenset()


# ════════════════════════════════════════════════════════════════════════════
# (iii) FUNCTIONAL — the in-tool guard: on-role always works; off-scope is
#       warn-log+proceed by default, enforce-refuse when flipped.
# ════════════════════════════════════════════════════════════════════════════
async def test_planner_updates_own_action_on_role_succeeds_warn(tmp_path, monkeypatch):
    # THE regression case (2026-07-04): a planner mutating its OWN plan's
    # action must succeed. Default (warn) mode.
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func:s1")   # planner: recipe:step
    monkeypatch.delenv("EDP_ROLE_SCOPE", raising=False)     # → default warn
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")
    t = _tools(ctx)

    res = await t["update_object"].run({
        "type": "action",
        "ids": {"plan_id": "recipe-w4func-s1", "action_id": "a1"},
        "patch": {"description": "planner edited its own action"}})
    assert isinstance(res, ToolOk), res

    p = ctx.plans.load("recipe-w4func-s1")
    a = next(a for a in p.actions if a.action_id == "a1")
    assert a.description == "planner edited its own action"
    # on-role → NOTHING logged (the guard returns silently)
    assert _violations(ctx, "recipe-w4func-s1") == []


async def test_planner_updates_own_action_on_role_succeeds_enforce(tmp_path, monkeypatch):
    # the on-role path MUST always succeed, INCLUDING under enforce (d15 "also").
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func:s1")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "enforce")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")
    t = _tools(ctx)

    res = await t["update_object"].run({
        "type": "action",
        "ids": {"plan_id": "recipe-w4func-s1", "action_id": "a1"},
        "patch": {"description": "on-role under enforce"}})
    assert isinstance(res, ToolOk), res
    p = ctx.plans.load("recipe-w4func-s1")
    assert next(a for a in p.actions
                if a.action_id == "a1").description == "on-role under enforce"
    assert _violations(ctx, "recipe-w4func-s1") == []


async def test_planner_deletes_own_action_on_role_succeeds_warn(tmp_path, monkeypatch):
    # HARD_CONDITION (neuron): the on-role path must prove delete_object too,
    # not only update_object. A planner deletes its OWN plan's action (warn).
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func:s1")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")
    t = _tools(ctx)

    res = await t["delete_object"].run({
        "type": "action",
        "ids": {"plan_id": "recipe-w4func-s1", "action_id": "a2"},
        "reason": "superseded — on-role planner delete"})
    assert isinstance(res, ToolOk), res
    p = ctx.plans.load("recipe-w4func-s1")
    assert [a.action_id for a in p.actions] == ["a1"]
    assert _violations(ctx, "recipe-w4func-s1") == []


async def test_planner_deletes_own_action_on_role_succeeds_enforce(tmp_path, monkeypatch):
    # ...and the same delete works under enforce (on-role always succeeds).
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func:s1")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "enforce")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")
    t = _tools(ctx)

    res = await t["delete_object"].run({
        "type": "action",
        "ids": {"plan_id": "recipe-w4func-s1", "action_id": "a2"},
        "reason": "superseded — on-role planner delete under enforce"})
    assert isinstance(res, ToolOk), res
    p = ctx.plans.load("recipe-w4func-s1")
    assert [a.action_id for a in p.actions] == ["a1"]
    assert _violations(ctx, "recipe-w4func-s1") == []


async def test_off_object_type_warn_logs_and_proceeds(tmp_path, monkeypatch):
    # a planner mutating a recipe STEP is OFF-object-type (planner CRUD =
    # plan/action only). Under warn: log a role_scope_violation AND proceed —
    # the step edit actually lands.
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func:s1")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")
    t = _tools(ctx)

    res = await t["update_object"].run({
        "type": "step",
        "ids": {"recipe_id": "recipe-w4func", "step_id": "s1"},
        "patch": {"description": "planner touched a step (off-scope)"}})
    # PROCEEDED — this is NOT the enforce refusal, and the edit took effect.
    assert isinstance(res, ToolOk), res
    r = ctx.recipes.load("recipe-w4func")
    assert any(s.description == "planner touched a step (off-scope)"
               for s in r.steps)

    hits = _violations(ctx, "recipe-w4func-s1")
    assert hits, "warn mode must record a role_scope_violation"
    h = hits[-1]
    assert h["agent_role"] == "planner"
    assert h["tool"] == "update_object"
    assert h.get("object_type") == "step"
    assert h.get("mode") == "warn"


async def test_off_object_type_enforce_refuses_and_blocks(tmp_path, monkeypatch):
    # the wired-but-not-default enforce flip: the SAME off-type call refuses
    # with a _precondition naming the role + allowed types, and the mutation
    # does NOT happen.
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func:s1")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "enforce")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")
    t = _tools(ctx)

    res = await t["update_object"].run({
        "type": "step",
        "ids": {"recipe_id": "recipe-w4func", "step_id": "s1"},
        "patch": {"description": "should NOT apply"}})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "role-scope refused" in res.message
    assert "planner" in res.message and "step" in res.message
    # blocked → the step is unchanged
    r = ctx.recipes.load("recipe-w4func")
    assert all(s.description != "should NOT apply" for s in r.steps)
    # the refusal is still recorded (enforce mode)
    hits = _violations(ctx, "recipe-w4func-s1")
    assert any(h.get("mode") == "enforce" for h in hits), hits


async def test_worker_object_crud_off_role_warn_logs_and_proceeds(tmp_path, monkeypatch):
    # a WORKER is read-only over the generic verbs; under warn an off-role
    # update is logged (role=worker) and proceeds.
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func-s1:a1")  # worker: plan:action
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")
    t = _tools(ctx)

    res = await t["update_object"].run({
        "type": "action",
        "ids": {"plan_id": "recipe-w4func-s1", "action_id": "a1"},
        "patch": {"description": "worker edit (off-role, warn)"}})
    assert isinstance(res, ToolOk), res
    hits = _violations(ctx, "recipe-w4func-s1")
    assert hits and hits[-1]["agent_role"] == "worker"
    assert hits[-1]["tool"] == "update_object"


# ════════════════════════════════════════════════════════════════════════════
# (iv) SEAM — build_mcp warn (register all) vs enforce (filter) + the shared
#      violation logger the warn-mode off-set shim calls on each off-set call.
# ════════════════════════════════════════════════════════════════════════════
def _seam_names(tmp_path):
    from edp_claude.mcp_server import build_mcp
    mcp = build_mcp(tmp_path)
    return {t.name for t in mcp._tool_manager.list_tools()}


def test_seam_default_is_enforce_and_filters(tmp_path, monkeypatch):
    # DESIGN-v7 P0: enforce IS the default — an unset EDP_ROLE_SCOPE filters
    # a role shell's registry to exactly its toolset. This test used to pin
    # warn-as-default (d15's observe-before-enforce Phase-1 bar); v7 closed
    # the last known enforce break (the reviewer-leg role default, P4.1)
    # and flipped it. warn survives as the diagnostic OPT-OUT below.
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.delenv("EDP_ROLE_SCOPE", raising=False)   # → default enforce
    names = _seam_names(tmp_path)
    assert names == set(ROLE_TOOLSETS["worker"])
    assert "next_action" not in names       # planner-only, absent


def test_seam_warn_opt_out_registers_full_surface(tmp_path, monkeypatch):
    # warn (the diagnostic opt-out): NO filtering — a worker shell keeps the
    # full surface, and a planner-only tool is STILL registered (its shim
    # logs on call rather than being absent).
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    names = _seam_names(tmp_path)
    assert len(names) == len(ALL_TOOL_CLASSES)
    assert "next_action" in names           # planner-only, still registered
    assert "pool_spawn_worker" in names


def test_seam_enforce_filters_to_role_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "enforce")
    names = _seam_names(tmp_path)
    assert names == set(ROLE_TOOLSETS["worker"])
    assert "next_action" not in names


def test_record_role_scope_violation_logs_role_and_tool(tmp_path, monkeypatch):
    # the exact helper the warn-mode off-set shim invokes per off-set CALL:
    # it writes a role_scope_violation (role + tool) to the caller's plan
    # worklog and returns the active mode.
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func-s1:a1")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")

    mode = record_role_scope_violation(ctx, "next_action")
    assert mode == "warn"
    hits = _violations(ctx, "recipe-w4func-s1")
    assert hits and hits[-1]["agent_role"] == "worker"
    assert hits[-1]["tool"] == "next_action"


# ════════════════════════════════════════════════════════════════════════════
# (v) s25/a4 — THE BARE-HANDLE BLIND SPOT (a1 blocker 1, CRITICAL)
#
# `_role_scope_worklog_key` (was `…_plan_id`) resolved the worklog target via
# _self_and_parent_addresses, which returns (handle, None) when the handle has
# no ':'. `record_role_scope_violation` then hit `if pid:` and wrote NOTHING.
#
# EVERY non-planner, non-worker role is spawned with a BARE handle —
# reviewer `review-<neuron_id>-<hex8>`, specialist `specialist-<slug>-<hex8>`,
# consult `consult-<hex8>`, curiosity/goal_keeper/pattern_observer likewise. So
# their violations were SILENTLY DROPPED, and "zero violations" from those roles
# was indistinguishable from "never instrumented" — while four of the seven known
# guide/toolset gaps lived in exactly those roles. The d14/d15 flip gate ("a
# zero-violation recipe") was measuring nothing for six of the nine roles.
#
# This is the observability PREREQUISITE for any future enforce flip. It changes
# no on-scope behaviour: warn still logs-and-proceeds, enforce still refuses.
# ════════════════════════════════════════════════════════════════════════════
def _bare_handle_violations(ctx, handle):
    """A bare-handle shell's trail is keyed by the HANDLE (no plan exists)."""
    return [e for e in ctx.plans.read_worklog(handle, tail=50)
            if e.get("kind") == "role_scope_violation"]


async def test_bare_handle_reviewer_violation_is_recorded_not_dropped(
        tmp_path, monkeypatch):
    # THE regression, stated as a1 stated it: "a reviewer with a bare handle
    # produces exactly one role_scope_violation; today that assertion is RED."
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    monkeypatch.setenv("EDP_HANDLE", "review-neuron-java-abc123")  # NO colon
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    ctx = make_context(tmp_path)

    mode = record_role_scope_violation(ctx, "next_action")
    assert mode == "warn"

    hits = _bare_handle_violations(ctx, "review-neuron-java-abc123")
    assert len(hits) == 1, (
        "a bare-handle reviewer's off-scope call was dropped — the flip gate "
        f"cannot see it. got: {hits}")
    assert hits[0]["agent_role"] == "reviewer"
    assert hits[0]["tool"] == "next_action"
    assert hits[0]["handle"] == "review-neuron-java-abc123"

    # the trail is NOT mistaken for a plan (no plan.json is written)
    assert not ctx.plans.exists("review-neuron-java-abc123")


async def test_every_bare_handle_role_is_instrumented(tmp_path, monkeypatch):
    # all six blind roles, enumerated. "When an invariant spans N surfaces,
    # enumerate the N surfaces" (W5/a5's durable lesson) — a spot-check on the
    # reviewer alone would leave five roles silently dropping events.
    bare = {
        "reviewer": "review-neuron-java-abc123",
        "specialist": "specialist-java-abc123",
        "consult": "consult-abc123",
        "curiosity": "curiosity-abc123",
        "goal_keeper": "recipe-x-goalkeeper-abc123",
        "pattern_observer": "patterns-observer-abc123",
    }
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    ctx = make_context(tmp_path)
    for role, handle in bare.items():
        assert ":" not in handle, handle       # the precondition under test
        monkeypatch.setenv("EDP_ROLE", role)
        monkeypatch.setenv("EDP_HANDLE", handle)
        record_role_scope_violation(ctx, "close_recipe")
        hits = _bare_handle_violations(ctx, handle)
        assert len(hits) == 1, f"{role} violation dropped: {hits}"
        assert hits[0]["agent_role"] == role
        assert hits[0]["handle"] == handle


async def test_colon_handle_roles_still_log_to_their_plan(tmp_path, monkeypatch):
    # the fallback must not STEAL the planner/worker path: a colon handle still
    # resolves to the plan worklog, exactly as before (planner → dash plan_id,
    # worker → handle prefix). This is the "changes nothing for on-scope roles"
    # half of the contract.
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-w4func")
    _save_plan_with_action(ctx, "recipe-w4func", "recipe-w4func-s1")

    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func:s1")   # recipe:step
    record_role_scope_violation(ctx, "close_recipe")

    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "recipe-w4func-s1:a1")  # plan:action
    record_role_scope_violation(ctx, "next_action")

    hits = _violations(ctx, "recipe-w4func-s1")
    assert [h["agent_role"] for h in hits] == ["planner", "worker"], hits
    # NOT written under the raw handles
    assert _bare_handle_violations(ctx, "recipe-w4func:s1") == []


async def test_neuron_without_a_handle_records_nothing(tmp_path, monkeypatch):
    # the foreground neuron is unconstrained by design (toolset_for_role → None,
    # build_mcp registers everything), so it has no off-scope calls to record.
    # The fallback must not invent a trail for it.
    monkeypatch.setenv("EDP_ROLE", "neuron")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE_SCOPE", "warn")
    ctx = make_context(tmp_path)

    from edp_claude.tools._tools import _role_scope_worklog_key
    assert _role_scope_worklog_key() is None
    assert record_role_scope_violation(ctx, "close_recipe") == "warn"

    # and NOTHING was written — no trail invented for a handle-less shell.
    plans = tmp_path / ".plans"
    trails = list(plans.rglob("worklog.jsonl")) if plans.exists() else []
    assert trails == [], f"a handle-less neuron wrote a violation trail: {trails}"
