"""MULTI-SPEC worker selection (2026-06-03, recipe …-s14).

Additive extension: an action may carry N specs (spec_ids[]/specializations[]),
the planner stamps all relevant, Guard B validates EACH stamped spec has a
compiled doc, and a fresh worker loads + ORDERED-CONCATENATES all compiled
docs (amendment A3 — no universal dedup; the universal layer repeats per
stack, accepted). N=1 is bit-for-bit the old single-spec system, and old
plan JSON (legacy scalar spec_id) loads + round-trips to the old on-disk
shape (serialization-hazard safety for the pre-restart MCP/pool).

Amendments under test: A1 (canonical lists + legacy fold, no parallel scalar,
old-shape serialize for N≤1), A2 (no hard cap on N), A3 (ordered concatenation
with per-stack headers, universal repeats — no dedup).
"""

import json

from edp_contracts import ToolError, ToolOk

from edp_claude.compose import compose_specialist_docs
from edp_claude.schemas.plan import Action


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _action(**over) -> Action:
    base = dict(
        action_id="a1", description="x", status="pending",
        executor_mode="subagent", acceptance={"kind": "manual_review"},
    )
    base.update(over)
    return Action.model_validate(base)


# ── UNIT: effective_spec_ids — legacy fold, dedup, precedence ─────────────

def test_effective_spec_ids_empty():
    assert _action().effective_spec_ids() == []


def test_effective_spec_ids_legacy_scalar_folds():
    a = _action(spec_id="spec-java")
    assert a.spec_ids == ["spec-java"]
    assert a.effective_spec_ids() == ["spec-java"]
    # legacy specialization scalar folds too
    a2 = _action(specialization="Java Spring Boot")
    assert a2.specializations == ["Java Spring Boot"]
    assert a2.effective_specializations() == ["Java Spring Boot"]


def test_effective_spec_ids_multi():
    a = _action(spec_ids=["spec-java", "spec-react"])
    assert a.effective_spec_ids() == ["spec-java", "spec-react"]


def test_effective_spec_ids_dedup_preserves_order():
    a = _action(spec_ids=["spec-a", "spec-a", "spec-b", "spec-a"])
    assert a.effective_spec_ids() == ["spec-a", "spec-b"]


def test_effective_spec_ids_precedence_plural_wins():
    # both supplied → spec_ids wins, the scalar is ignored (folded only when
    # the plural is absent)
    a = _action(spec_id="spec-old", spec_ids=["spec-new"])
    assert a.effective_spec_ids() == ["spec-new"]


# ── UNIT: serialization-hazard — old-shape JSON for N≤1, plural only N≥2 ───

def test_serialize_generic_is_old_shape():
    d = _action().model_dump(mode="json")
    assert d["spec_id"] is None and d["specialization"] is None
    assert "spec_ids" not in d and "specializations" not in d


def test_serialize_single_spec_is_old_shape():
    d = _action(spec_ids=["spec-java"], specializations=["Java"]).model_dump(
        mode="json")
    # N=1 must serialize to the LEGACY scalar shape so the pre-restart
    # old-schema MCP/pool can still re-read the plan.
    assert d["spec_id"] == "spec-java" and "spec_ids" not in d
    assert d["specialization"] == "Java" and "specializations" not in d


def test_serialize_multi_spec_emits_plural():
    d = _action(spec_ids=["spec-java", "spec-react"]).model_dump(mode="json")
    assert d["spec_ids"] == ["spec-java", "spec-react"]
    assert "spec_id" not in d


def test_legacy_plan_json_round_trips():
    # a historical action dict (only the scalar) loads, then re-serializes to
    # the same old-schema-readable shape — no error, plural keys absent.
    legacy = {
        "action_id": "a1", "description": "x", "status": "pending",
        "executor_mode": "subagent",
        "acceptance": {"kind": "manual_review"},
        "specialization": "Java", "spec_id": "spec-java", "concerns": [],
    }
    a = Action.model_validate(legacy)
    out = a.model_dump(mode="json")
    assert out["spec_id"] == "spec-java" and "spec_ids" not in out
    # and the reload is identical
    assert Action.model_validate(out).effective_spec_ids() == ["spec-java"]


# ── UNIT: compose_specialist_docs — A3 ordered concat, no dedup ───────────

_UNIVERSAL = "- SOLID single-responsibility; no magic numbers [required]\n"
_JAVA = f"# Java\n## House style\n- Constructor injection [required]\n{_UNIVERSAL}"
_REACT = f"# React\n## House style\n- TanStack Query v5 [required]\n{_UNIVERSAL}"


def test_compose_zero_docs_is_empty():
    assert compose_specialist_docs([]) == ""
    assert compose_specialist_docs([("spec-x", None)]) == ""


def test_compose_one_doc_is_banner_plus_verbatim_doc():
    # F37#6: the provenance banner frames every composed grounding (the old
    # single-spec bit-for-bit pass-through predates the framing envelope);
    # the doc itself still rides verbatim after the banner.
    out = compose_specialist_docs([("spec-java", _JAVA)])
    assert out.startswith("<!-- SPECIALIST GROUNDING")
    assert out.endswith(_JAVA)


def test_compose_two_docs_concatenated_with_headers_universal_repeats():
    out = compose_specialist_docs([("spec-java", _JAVA), ("spec-react", _REACT)])
    # both stacks' headers present, in input order
    ji = out.index("Specialist stack: spec-java")
    ri = out.index("Specialist stack: spec-react")
    assert ji < ri
    # both stacks' [required] rules present
    assert "Constructor injection [required]" in out
    assert "TanStack Query v5 [required]" in out
    # A3: the universal layer REPEATS (no dedup) — appears once per doc
    assert out.count("SOLID single-responsibility") == 2


def test_compose_order_is_stable_to_input():
    out = compose_specialist_docs([("spec-react", _REACT), ("spec-java", _JAVA)])
    assert out.index("spec-react") < out.index("spec-java")


# ── Guard B (generalized): validate EACH stamped spec has a compiled doc ──

async def _plan(env):
    rid = _ok(await env.call("start_recipe", goal="build an api",
                             domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="linear-build", goal="build it"))["plan_id"]
    return pid


def _stamp(env, pid, action_id, *, spec_ids=None, specializations=None):
    """Stamp the canonical plural fields directly on the stored action."""
    p = env.ctx.plans.load(pid)
    a = next(x for x in p.actions if x.action_id == action_id)
    if spec_ids is not None:
        a.spec_ids = list(spec_ids)
    if specializations is not None:
        a.specializations = list(specializations)
    env.ctx.plans.save(p)


async def _make_spec(env, name, subject, *, with_doc=True):
    sid = _ok(await env.call("create_specialization", name=name,
                             subject=subject, description=subject))["spec_id"]
    if with_doc:
        _ok(await env.call("write_specialist_doc", spec_id=sid,
                           content=f"# {name}\n## House style\n- rule [required]\n"))
    return sid


async def test_guard_b_zero_specs_not_blocked(env):
    pid = await _plan(env)
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="Back up the data directory"))
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    msg = res.message if isinstance(res, ToolError) else ""
    assert "spec_id" not in msg and "spec_ids" not in msg


async def test_guard_b_declared_but_unresolved_refuses(env):
    pid = await _plan(env)
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="Implement POST /login",
                       specialization="Java Spring Boot REST API"))
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert "spec_ids is empty" in res.message and "neuron_search" in res.message


async def test_guard_b_single_missing_doc_refuses_and_names_it(env):
    pid = await _plan(env)
    sid = await _make_spec(env, "Spring", "spring", with_doc=False)
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="Implement POST /login"))
    _stamp(env, pid, "a1", spec_ids=[sid])
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert "no compiled" in res.message.lower() and sid in res.message


async def test_guard_b_two_specs_both_present_not_blocked(env):
    pid = await _plan(env)
    j = await _make_spec(env, "Spring", "spring")
    r = await _make_spec(env, "ReactTS", "react")
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="Full-stack login endpoint + form"))
    _stamp(env, pid, "a1", spec_ids=[j, r])
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    msg = res.message if isinstance(res, ToolError) else ""
    assert "no compiled" not in msg.lower() and "spec_ids is empty" not in msg


async def test_guard_b_two_specs_one_missing_refuses_only_missing(env):
    pid = await _plan(env)
    j = await _make_spec(env, "Spring", "spring")            # has doc
    r = await _make_spec(env, "ReactTS", "react", with_doc=False)  # no doc
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="Full-stack endpoint + form"))
    _stamp(env, pid, "a1", spec_ids=[j, r])
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert r in res.message            # names the missing one
    assert j not in res.message        # does NOT name the present one


# ── INTEGRATION: stamp via update_object, compose grounding ───────────────

async def test_planner_stamps_two_specs_via_update_object(env):
    pid = await _plan(env)
    j = await _make_spec(env, "Spring", "spring")
    r = await _make_spec(env, "ReactTS", "react")
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="Full-stack login endpoint + form"))
    # the planner stamps ALL relevant specs in ONE call
    _ok(await env.call("update_object", type="action",
                       ids={"plan_id": pid, "action_id": "a1"},
                       patch={"spec_ids": [j, r]}))
    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert a.effective_spec_ids() == [j, r]
    # Guard B passes
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    msg = res.message if isinstance(res, ToolError) else ""
    assert "no compiled" not in msg.lower()


async def test_update_object_legacy_spec_id_still_accepted(env):
    pid = await _plan(env)
    j = await _make_spec(env, "Spring", "spring")
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="login endpoint"))
    _ok(await env.call("update_object", type="action",
                       ids={"plan_id": pid, "action_id": "a1"},
                       patch={"spec_id": j}))       # legacy scalar patch
    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert a.effective_spec_ids() == [j]


async def test_get_specialist_docs_composes_both_stacks(env):
    j = await _make_spec(env, "Spring", "spring")
    r = await _make_spec(env, "ReactTS", "react")
    out = _ok(await env.call("get_specialist_docs", spec_ids=[j, r]))
    assert out["count"] == 2 and out["missing"] == []
    g = out["grounding"]
    assert f"Specialist stack: {j}" in g and f"Specialist stack: {r}" in g
    # both stacks' [required] rules present in the composed grounding
    assert g.count("[required]") >= 2


async def test_get_specialist_docs_single_is_byte_identical(env):
    # v7 P0 deleted the singular get_specialist_doc tool; the invariant
    # survives against the STORE read the singular used to pass through.
    j = await _make_spec(env, "Spring", "spring")
    one = _ok(await env.call("get_specialist_docs", spec_ids=[j]))
    direct = env.ctx.specs.read_doc(j, with_overlay=True)
    # F37#6: N=1 path = provenance banner + the single-spec doc verbatim
    assert one["grounding"].startswith("<!-- SPECIALIST GROUNDING")
    assert one["grounding"].endswith(direct)


async def test_get_specialist_docs_reports_missing(env):
    j = await _make_spec(env, "Spring", "spring")
    out = _ok(await env.call("get_specialist_docs", spec_ids=[j, "spec-nope"]))
    assert out["missing"] == ["spec-nope"] and out["count"] == 1


# ── INTEGRATION: old plan JSON on disk loads unchanged through the store ──

async def test_old_plan_json_loads_through_store(env):
    pid = await _plan(env)
    # hand-write an old-shape action into the plan file (scalar spec_id only)
    f = env.ctx.plans._file(pid)
    data = json.loads(f.read_text(encoding="utf-8"))
    data["actions"].append({
        "action_id": "legacy", "description": "old action", "status": "pending",
        "depends_on": [], "executor_mode": "subagent",
        "acceptance": {"kind": "manual_review", "expected": "", "actual": None,
                       "verify": None},
        "result_ref": None, "attempt": 0,
        "specialization": "Java", "spec_id": "spec-java", "concerns": [],
    })
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    p = env.ctx.plans.load(pid)                    # MUST NOT raise
    a = next(x for x in p.actions if x.action_id == "legacy")
    assert a.effective_spec_ids() == ["spec-java"]
    assert a.effective_specializations() == ["Java"]
    # and re-saving keeps the old on-disk shape for this N=1 action
    env.ctx.plans.save(p)
    reloaded = json.loads(f.read_text(encoding="utf-8"))
    la = next(x for x in reloaded["actions"] if x["action_id"] == "legacy")
    assert la["spec_id"] == "spec-java" and "spec_ids" not in la
