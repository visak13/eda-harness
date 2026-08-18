"""Orchestrator launch contract + shared-guide loadability.

W15 (DESIGN-v6): the orchestrator was mis-modeled as an append-only
`spec-orchestrator` and reverted to a directly-edited GUIDE
(docs/guides/orchestrator-launch.md, loaded via get_guide). The
ensure_orchestrator bootstrap + its seed are RETIRED — coverage that the
mechanism is gone lives in tests/test_w15_orchestrator_guide.py. This file
retains the shared-guide loadability + shell-brief contracts, which are
independent of the retired orchestrator spec.
"""

from pathlib import Path

from edp_contracts import ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_architecture_vocabulary_guide_loads(env):
    # the shared vocab doc is loadable by every shell via get_guide.
    out = _ok(await env.call("get_guide", name="architecture-vocabulary"))
    body = out["content"].lower()
    for noun in ("broker", "pool", "recipe", "plan", "action", "step",
                 "outcome", "session", "lock", "message", "worklog",
                 "neuron", "spec"):
        assert noun in body
    assert "describe_objects" in body and "update_object" in body
    assert "verify" in body and "next_action" in body
    # the three-planes model + mandatory message subscription
    assert "three planes" in body or "object graph" in body
    assert "observe" in body and "monitor" in body
    assert "reactive-streams" in body            # points to the rx guide


async def test_reactive_streams_guide_loads(env):
    # the agent-facing rx operator reference is loadable via get_guide.
    out = _ok(await env.call("get_guide", name="reactive-streams"))
    body = out["content"].lower()
    assert "observe" in body and "monitor" in body
    for src in ("rx.broker", "rx.worklog", "rx.pool", "rx.merge"):
        assert src in body
    assert "scope=" in body                       # the pool-scope rule
    # s14 rewrote this guide into teach-to-choose form (building blocks +
    # a NEED->SOURCE/OPERATOR/EFFECT decision map), intentionally dropping
    # the old literal "control-plane"/"data-plane" plane labels. Assert the
    # current phrasing instead — do NOT re-add the dropped terms to the guide.
    assert "decision map" in body                 # teach-to-choose, not canned recipes
    assert "data-plane" in body                   # the reduction discipline survives
    assert "fsm boundary" in body                 # don't reinvent what the FSM owns
    assert "register_rule" in body                # the durable-rule loop
    assert "fork_join" in body                    # the wave gate


def test_neuron_brief_bootstraps_universal_layer():
    # 2026-06-01: the neuron also floors the universal coding-standards
    # layer, so `spec-universal` exists before any worker/reviewer
    # assemble_ruleset (otherwise assembly fails on a missing parent).
    b = (_CMD / "neuron.md").read_text(encoding="utf-8").lower()
    assert "ensure_universal" in b
    assert "spec-universal" in b


def test_neuron_brief_loads_orchestrator_launch_guide():
    # W15 (DESIGN-v6): the orchestrator is a directly-edited GUIDE, not a
    # spec. The neuron brief must LOAD it via get_guide('orchestrator-launch')
    # at Step 0 and must NOT bootstrap the retired spec-orchestrator.
    # Replaces test_neuron_brief_bootstraps_orchestration_spec (a10 removed the
    # old spec-bootstrap assertion). NOTE: a bare "spec-orchestrator" mention is
    # allowed ONLY in RETIREMENT framing (like the ScheduleWakeup pattern in
    # test_v6_docs); what must be gone are the LIVE call sites — the
    # ensure_orchestrator bootstrap and the get_specialization / add_spec_entry
    # loads against spec-orchestrator.
    b = (_CMD / "neuron.md").read_text(encoding="utf-8").lower()
    assert 'get_guide("orchestrator-launch")' in b \
        or "get_guide('orchestrator-launch')" in b
    # the retired bootstrap tool is gone entirely
    assert "ensure_orchestrator" not in b
    # no live spec-orchestrator load/author call survives
    assert 'get_specialization(spec_id="spec-orchestrator")' not in b
    assert 'add_spec_entry(spec_id="spec-orchestrator"' not in b


def test_briefs_point_at_object_surface_not_lambda():
    # OBJECT-MODEL inc4: every shell brief drives state inspection through
    # the object + CRUD surface; the retired lambda DSL is gone.
    for name in ("neuron.md", "agentic-plan.md", "worker.md"):
        b = (_CMD / name).read_text(encoding="utf-8").lower()
        assert "work_via_lambda" not in b, name
        assert "get_lambda_guide" not in b, name
        assert "architecture-vocabulary" in b, name
    nb = (_CMD / "neuron.md").read_text(encoding="utf-8").lower()
    assert "query_objects" in nb and "update_object" in nb


def test_briefs_read_state_via_object_surface_not_raw_files():
    # 2026-05-31: agents fumbled raw-path reads of recipe/plan (guessing
    # edp-pool/.edp_state, hedging powershell+python in parallel). State
    # reads MUST go through read_object/query_objects — the old raw-file
    # instructions are removed and the shells use the object surface.
    # (goal-keeper.md / pattern-observer.md deleted with their dead roles,
    # owner ruling 2026-08-04 — the worker brief is the surviving surface.)
    for name in ("worker.md",):
        b = (_CMD / name).read_text(encoding="utf-8")
        assert "read_object" in b, name
    w = (_CMD / "worker.md").read_text(encoding="utf-8")
    assert "Read `.plans/<plan_id>.json` (normal Read tool)" not in w
    assert 'read_object("action"' in w


def test_vocab_guide_forbids_raw_state_file_reads():
    from pathlib import Path
    g = (Path(__file__).resolve().parents[1] / "docs" / "guides"
         / "architecture-vocabulary.md").read_text(encoding="utf-8").lower()
    assert "never read or write the recipe/plan" in g
    assert "edp-pool/.edp_state" in g          # names the exact wrong-path trap
    assert "blocked state to surface" in g     # MCP-down ≠ improvise files


def test_every_interactive_shell_mandates_message_subscription():
    # 2026-05-30: shells skipped the rx plane and fell back to slow
    # heartbeat polling. Every interactive shell brief must now set up at
    # least a message subscription (observe rx.broker) and point at the
    # operator guide.
    # F3 (2026-08-17): wiring is one arm_wiring() call — the rx spec lives
    # in code (_WIRING_SPECS), so the cards mandate arm_wiring + Monitor
    # instead of spelling observe(rx.broker...). Either form satisfies the
    # invariant "every interactive shell arms a push subscription".
    for name in ("neuron.md", "agentic-plan.md", "worker.md",
                 "curiosity.md"):
        b = (_CMD / name).read_text(encoding="utf-8").lower()
        assert ("arm_wiring(" in b
                or ("observe(" in b and "rx.broker" in b)), name
        assert "monitor" in b, name


def test_neuron_planner_frame_heartbeat_as_backstop():
    # the heartbeat stays (self-paced backstop + pacer), but the
    # subscription is primary — the brief must say so, not present them
    # as equal options.
    for name in ("neuron.md", "agentic-plan.md"):
        b = (_CMD / name).read_text(encoding="utf-8").lower()
        assert "backstop" in b, name
        assert "first" in b, name                 # subscribe FIRST
