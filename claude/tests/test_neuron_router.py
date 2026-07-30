"""v2.5 — neuron-as-router.

The neuron's brief + the orchestrator spec frame it as a pure router:
it delegates comprehension/research/planning/execution/review to the
respective neurons and only maintains the recipe map. It does not
decide or execute inline.
"""

from pathlib import Path

from edp_contracts import ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def test_neuron_brief_frames_router_not_brain():
    b = (_CMD / "neuron.md").read_text(encoding="utf-8").lower()
    assert "router" in b and "not the brain" in b
    # delegation targets named
    assert "curiosity" in b and "specialist" in b and "planner" in b
    assert "reviewer fork" in b or "reviewer forks" in b
    # the means, not advisors
    assert "means to the goal" in b or "the means" in b
    # don't execute/decide inline
    assert "editing a file" in b or "another neuron's part" in b


# W15 (DESIGN-v6): test_orchestrator_seed_carries_router_principle RETIRED.
# The router principle no longer lives in a `spec-orchestrator` seed (the
# orchestrator spec-ness is retired) — it moves to the directly-edited
# docs/guides/orchestrator-launch.md guide (its content is asserted by the
# migration action a7). The neuron-brief framing above is unaffected.
