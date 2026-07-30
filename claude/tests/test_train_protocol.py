"""2026-05-24 — train-decision protocol (Fix A).

The deadlock: the neuron replied "train it" to the planner but never
called train_specialist, and decided to train without asking the user.
Fix: the orchestrator seed + phase-D carry the protocol — ask the user
first; deciding train ⇒ call train_specialist in the same turn; never
tell the planner to train.
"""

from pathlib import Path

from edp_contracts import ToolOk

_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"
_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# W15 (DESIGN-v6): test_orchestrator_seed_carries_train_protocol RETIRED.
# The train-gap protocol no longer lives in a `spec-orchestrator` seed (the
# orchestrator spec-ness is retired) — it lives in neuron-phase-d.md
# (asserted below) and the directly-edited orchestrator-launch.md guide
# (its content is asserted by the migration action a7).


def test_phase_d_handles_specialist_gap_without_deadlock():
    d = (_GUIDES / "neuron-phase-d.md").read_text(encoding="utf-8").lower()
    assert "no specialist for x" in d or "train one?" in d
    assert "askuserquestion" in d            # ask the user
    assert "same turn" in d                   # call train_specialist now
    assert "deadlock" in d                     # the named failure
    assert 'never reply "train it"' in d or "never reply 'train it'" in d \
        or "cannot call" in d


def test_planner_brief_never_trains_and_disambiguates():
    # 2026-05-31 planner phasing: the never-train-yourself + disambiguate
    # discipline lives in the drive phase guide's dispatch_action branch.
    b = (_GUIDES / "planner-phase-drive.md").read_text(encoding="utf-8").lower()
    assert "never train a specialist yourself" in b \
        or "cannot call" in b
    assert "disambiguate" in b or "to confirm" in b
