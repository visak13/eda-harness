"""MCP-1/MCP-2 — the MCP stdio server is pure transport over the already
-tested 16-tool registry. The real MCP protocol round-trip is manual-HITL
(needs a real claude); here we assert wiring + envelope shape."""

from edp_claude.server import make_context
from edp_claude.tools import ALL_TOOL_CLASSES, build_registry


def test_mcp_1_registry_has_59_named_tools(tmp_path):
    tools = build_registry(make_context(tmp_path))
    names = sorted(t.name for t in tools)
    # 36 + neuron DB + specialization_recipe (phases 2+3, 11 tools)
    #   + phase 4 self-train: train_specialist (1)
    #   + phase 5 branch-for-task: branch_specialist, flow_back_learnings (2)
    #     [both RETIRED 2026-06-03 — see the -2 below]
    #   + phase 6 subsume comprehension: seed_comprehension_specialists (1)
    #   + phase 8 orchestration-as-spec: ensure_orchestrator (1)
    #     [RETIRED 2026-07 W15 — orchestrator reverted spec->guide; see -1]
    #   + phase 9 decay: check_specialist_decay (1)
    #   + v2.2 curiosity: consult_curiosity (1)
    #   + 2026-05-24: mark_outcome_met, update_specialist (2)
    #   + 2026-05-25: pool_reap, read_worklog, inspect_worker (3)
    #   + 2026-05-28 comprehension gate: record_comprehension_signoff (1)
    #   + 2026-05-28 OBJECT-MODEL: describe_objects, read_object,
    #     query_objects, create_object, update_object (5); lambda surface
    #     (get_lambda_guide, work_via_lambda) RETIRED (-2)
    #   + 2026-05-29 REACTIVE-STREAMS: observe (1)
    #   + 2026-05-30 FSM-RESPONSIBILITY: reconcile (1)
    #   + 2026-06-01 SPECIALIZATION-LAYERED-RULESETS: ensure_universal,
    #     assemble_ruleset (2)
    #   + 2026-06-01 whoami (canonical broker inbox; the colon/dash bug) (1)
    #   + 2026-06-02 SPECIALIST-COMPILED-DOCS: write_specialist_doc,
    #     get_specialist_doc (2)
    #   + 2026-06-03 retire the execution fork: branch_specialist,
    #     flow_back_learnings REMOVED (-2)
    #   + 2026-06-03 MULTI-SPEC: get_specialist_docs (compose N docs) (1)
    #   + 2026-06-04 SPEC-FLOWBACK: propose_spec_learning,
    #     list_spec_learnings (2) — quarantined-sidecar flow-back; NOT the
    #     retired fork-based flow_back_learnings (approval reuses
    #     update_specialist, no new approval path)
    #   + 2026-06-06 s27 Item 2: resolve_spec_learning (1) — the missing
    #     reject/promote half that closes the flow-back loop
    #   + 2026-06-06 s14 EVENT-PLANE AGENT-USABILITY: register_rule,
    #     list_rules (2) — durable reactive rule registry exposed as
    #     agent-callable MCP tools (observe gains an optional governed
    #     effect= arg; no new tool for that path)
    #   + 2026-06-10 P2 tiered storage: supersede_decision (1) — archive a
    #     decision out of the active set (index + worker stamp skip it)
    #   + 2026-06-10 P3 advisory-FSM CRUD: delete_object (1) — step/action
    #     deletion with advisories + audit trail
    #   + 2026-06-10 P4 flowback: emit_recipe_event (1) — recipe-scoped
    #     broadcast channel (rx.recipe_events) for worker→neuron learnings
    #   + 2026-06-10 P5 proactive comms: status_ping (1) — the cheap
    #     heartbeat-tick child check (inspect_worker minus the tail dump)
    #   + 2026-07-04 DESIGN-v6 W4: record_context (1) — the consolidated
    #     memory-write verb that routes to record_decision/assumption/
    #     rejected_option/remember (old verb classes stay registered)
    #   + 2026-07 DESIGN-v6 W15: ensure_orchestrator REMOVED (-1) — the
    #     orchestrator was mis-modeled as an append-only spec; reverted to a
    #     directly-edited guide (docs/guides/orchestrator-launch.md via
    #     get_guide). ensure_universal + the protected-spec subsystem stay.
    # DERIVED, not a magic number: the registry is the source of truth, so
    # this tracks ALL_TOOL_CLASSES instead of a hardcoded constant that goes
    # stale every time a tool lands (W4/a5 stale-count fix — was 81).
    assert len(names) == len(ALL_TOOL_CLASSES)
    assert "record_context" in names
    assert "supersede_decision" in names
    assert "delete_object" in names
    assert "emit_recipe_event" in names
    assert "status_ping" in names
    assert {"record_comprehension_signoff", "describe_objects",
            "read_object", "query_objects", "create_object",
            "update_object", "observe", "reconcile",
            "ensure_universal", "assemble_ruleset", "whoami",
            "write_specialist_doc",
            "get_specialist_docs",
            "list_spec_learnings", "register_rule",
            "list_rules"} <= set(names)
    # the execution-fork tools are retired — no fork path except
    # update_specialist (re-training); workers/reviewers run fresh + doc.
    assert "branch_specialist" not in names
    assert "flow_back_learnings" not in names
    # v7 P0 (break-and-migrate): the W6.4-retired verbs are DEREGISTERED —
    # gone from the registry itself, successors carry the capability
    # (record_context / get_specialist_docs / emit_recipe_event auto-propose
    # / resolve_spec_learnings / add_step+record_step_result).
    for retired in ("record_decision", "record_assumption",
                    "record_rejected_option", "remember",
                    "get_specialist_doc", "propose_spec_learning",
                    "resolve_spec_learning", "record_step"):
        assert retired not in names, retired
    assert "get_lambda_guide" not in names      # retired
    assert "work_via_lambda" not in names       # retired
    assert {"neuron_search", "create_specialization", "add_spec_entry",
            "neuron_set_status", "get_specialization", "train_specialist",
            "seed_comprehension_specialists",
            "check_specialist_decay", "consult_curiosity",
            "mark_outcome_met", "update_specialist",
            "pool_reap", "read_worklog", "inspect_worker"} <= set(names)
    # W15: the orchestrator spec-ness is retired — no ensure_orchestrator tool.
    assert "ensure_orchestrator" not in names
    assert {"create_plan", "add_action"} <= set(names)
    assert "pool_close_self" in names
    assert "close_recipe" in names
    assert {"get_guide", "consult_specialist", "record_specialist_consult",
            "run_ocak_audit", "record_audit_verdict"} <= set(names)
    assert {"ask_above", "notify_above", "reply", "check_inbox"} <= set(names)
    assert "consult_curiosity" in names
    # DELETED with their dead roles / by owner ruling (2026-08-04):
    for gone in ("consult_goal_keeper", "consult_pattern_observer",
                 "branch_reviewer"):
        assert gone not in names, gone
    assert "consult_critic" not in names  # retired in v2.4
    assert "respond" not in names  # renamed; addressing moved under tool
    assert {"next_action", "resolve_recipe", "start_recipe",
            "record_branch_verdict", "record_outcome",
            "add_step"} <= set(names)


def test_mcp_1b_build_mcp_registers_all(tmp_path, monkeypatch):
    # stub backend = deterministic + offline for the registry-count check
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    # DESIGN-v6 W4: build_mcp now SCOPES the registered surface to EDP_ROLE.
    # This test proves the UNSCOPED (absent-role) full-set path, so it must
    # neutralise any ambient EDP_ROLE/EDP_HANDLE (a worker running the suite
    # leaks EDP_ROLE=worker, which would scope build_mcp to 21 tools and
    # false-fail this assertion). Per-role scoping is proven in
    # tests/test_w4_roles.py.
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    from edp_claude.mcp_server import build_mcp

    mcp = build_mcp(tmp_path)
    listed = mcp._tool_manager.list_tools()
    got = sorted(t.name for t in listed)
    expected = sorted(t.name for t in build_registry(make_context(tmp_path)))
    assert got == expected
    # DERIVED from the live registry, not a magic number (W4/a5 stale-count
    # fix — was a hardcoded 81 that broke on every tool addition).
    assert len(got) == len(ALL_TOOL_CLASSES)


def test_build_context_backend_select(tmp_path, monkeypatch):
    from edp_claude.clients import HttpBroker, HttpPool
    from edp_claude.mcp_server import _build_context
    from edp_claude.stubs import StubBroker, StubPool

    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    c = _build_context(tmp_path)
    assert isinstance(c.broker, StubBroker) and isinstance(c.pool, StubPool)

    # default = http: real client types, NO network at construction
    monkeypatch.delenv("EDP_MCP_BACKEND", raising=False)
    monkeypatch.setenv("EDP_BROKER_URL", "http://127.0.0.1:9100")
    monkeypatch.setenv("EDP_POOL_URL", "http://127.0.0.1:9200")
    c2 = _build_context(tmp_path)
    assert isinstance(c2.broker, HttpBroker)
    assert isinstance(c2.pool, HttpPool)


def test_mcp_schema_is_real_not_payload_wrapper(tmp_path, monkeypatch):
    """Post-HITL sweep B: every tool must advertise its REAL InputModel
    schema with flat top-level args — never the old opaque
    `{payload: object}`. Regression-lock the disease fix at the MCP
    boundary."""
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    # W4: neutralise ambient EDP_ROLE/EDP_HANDLE so build_mcp registers the
    # FULL surface — this test inspects next_action / pool_close_self, which a
    # scoped worker/reviewer surface would omit (leaked worker env else fails).
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    from edp_claude.mcp_server import build_mcp

    mcp = build_mcp(tmp_path)
    by_name = {t.name: t for t in mcp._tool_manager.list_tools()}

    na = by_name["next_action"].parameters
    props = set(na.get("properties", {}))
    assert "payload" not in props  # the wrapper is GONE
    assert {"handle", "handle_type"} <= props  # the real contract is visible
    assert "handle" in na.get("required", [])

    # a no-field InputModel (pool_close_self) → no required args, which
    # correctly documents "this tool takes nothing".
    cs = by_name["pool_close_self"].parameters
    assert not cs.get("required")
    assert "payload" not in cs.get("properties", {})


async def test_mcp_2_shim_returns_envelope_dict(tmp_path):
    """A tool invoked through the registry returns a JSON-able envelope
    dict (what the MCP shim forwards)."""
    tools = {t.name: t for t in build_registry(make_context(tmp_path))}
    res = await tools["next_action"].run(
        {"handle": "missing", "handle_type": "recipe"}
    )
    d = res.model_dump(mode="json")
    assert d["ok"] is False
    assert d["code"] == "tool_precondition"
