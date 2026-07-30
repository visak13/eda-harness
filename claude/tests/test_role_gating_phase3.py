"""Context-diet Phase 3 — role gating completion.

3a: the foreground neuron shell is stamped (EDP_ROLE=neuron in .mcp.json) —
    it was the ONLY unscoped shell, fail-opening to the full registry.
3b: _NEURON is a POSITIVE curated list (ceiling asserted in test_w4_roles
    CEILINGS) — the craft/authoring surfaces left it.
3c: under enforce, an off-scope tool registers as a REFUSAL STUB (same name,
    real arg schema, one-word description) whose every call returns a
    structured precondition naming the owning role(s) — closing the
    "silently absent, no log, no explanation" blocker.
3d: the d67 review-leg guard is capability-based via Action.leg_kind; the
    name regex survives only as the legacy fallback, and a declaration
    un-reserves the review*/r<n> namespace.
"""
import json
from pathlib import Path

from edp_contracts import ToolError, ToolOk

from edp_claude.tools.roles import ROLE_TOOLSETS


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# ── 3a: the neuron shell is stamped ────────────────────────────────────────

def test_mcp_json_stamps_neuron_role():
    cfg = json.loads((Path(__file__).resolve().parents[1] / ".mcp.json")
                     .read_text(encoding="utf-8"))
    env = cfg["mcpServers"]["edp-claude"]["env"]
    assert env.get("EDP_ROLE") == "neuron", (
        "the foreground neuron shell must be scoped — it was the only "
        "unscoped shell and fail-opened to the full registry")


# ── 3b: positive list, delegation shape ────────────────────────────────────

def test_neuron_is_positive_and_delegates():
    n = ROLE_TOOLSETS["neuron"]
    # delegation verbs stay
    assert {"train_specialist", "consult_specialist",
            "pool_spawn_planner"} <= n
    # craft/authoring surfaces are gone
    for cut in ("assemble_ruleset", "get_specialist_docs",
                "get_specialization", "record_spec_version", "register_rule",
                "list_rules", "check_specialist_decay", "add_action",
                "create_plan", "record_plan", "record_grounding_brief",
                "record_branch_verdict", "create_object", "inspect_worker",
                "sol_consult", "sol_author_asset"):
        assert cut not in n, f"{cut} crept back onto the neuron surface"


# ── 3c: refusal stubs under enforce ────────────────────────────────────────

def _tools_by_name(tmp_path):
    from edp_claude.mcp_server import build_mcp
    mcp = build_mcp(tmp_path)
    return {t.name: t for t in mcp._tool_manager.list_tools()}


async def test_enforce_registers_refusal_stub_not_silence(tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "enforce")
    tools = _tools_by_name(tmp_path)

    # the full catalog registers: real tools + stubs — nothing is invisible
    assert "pool_spawn_planner" in tools, (
        "off-scope tool vanished — the silent-absence blocker is back")
    stub = tools["pool_spawn_planner"]
    assert stub.description == "(not available to role=worker)"

    # a real on-scope tool keeps its real description
    assert not tools["record_action_status"].description.startswith(
        "(not available")

    # calling the stub returns the structured refusal, not an execution
    out = await stub.run({"recipe_id": "r", "step_id": "s1"})
    blob = json.dumps(out if isinstance(out, (dict, list)) else out.__dict__,
                      default=str)
    assert "scoped to role(s)" in blob and "planner" in blob
    assert "broker" in blob


async def test_unset_role_gets_no_stubs(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_ROLE_SCOPE"):
        monkeypatch.delenv(var, raising=False)
    tools = _tools_by_name(tmp_path)
    assert not any((t.description or "").startswith("(not available")
                   for t in tools.values())


# ── 3d: leg_kind beats the name regex ──────────────────────────────────────

def test_effective_leg_kind_resolution():
    from edp_claude.tools._tools import _effective_leg_kind

    class _A:
        def __init__(self, k):
            self.leg_kind = k

    # declaration wins, both ways
    assert _effective_leg_kind(_A("build"), "r1") == "build"
    assert _effective_leg_kind(_A("review"), "a7") == "review"
    # legacy fallback: the taught conventions
    assert _effective_leg_kind(None, "r2") == "review"
    assert _effective_leg_kind(None, "final-review") == "review"
    assert _effective_leg_kind(None, "v3") == "verify"
    assert _effective_leg_kind(None, "a1") == "build"


async def test_declared_build_unreserves_review_name(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    # an action named r1 but DECLARED a build leg dispatches as a worker
    _ok(await env.call("add_action", plan_id=pid, action_id="r1",
                       description="rasterize layer one", leg_kind="build"))
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="r1")
    if isinstance(res, ToolError):
        assert "REVIEW leg" not in res.message, res.message

    # an action DECLARED review is refused as worker regardless of its name
    _ok(await env.call("add_action", plan_id=pid, action_id="a9",
                       description="judge the output", leg_kind="review"))
    res2 = await env.call("pool_spawn_worker", plan_id=pid, action_id="a9")
    assert isinstance(res2, ToolError), res2
    assert "REVIEW leg" in res2.message

    # the declaration persists (emission-gated: absent when None)
    p = env.ctx.plans.load(pid)
    a9 = next(x for x in p.actions if x.action_id == "a9")
    assert a9.leg_kind == "review"
    dumped = next(x for x in p.model_dump(mode="json")["actions"]
                  if x["action_id"] == "r1")
    assert dumped.get("leg_kind") == "build"
    legacy = next(x for x in p.model_dump(mode="json")["actions"]
                  if x["action_id"] == "a9")
    assert legacy.get("leg_kind") == "review"
