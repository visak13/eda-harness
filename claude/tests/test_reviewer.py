"""The reviewer ROLE and the planner's reviewer LEG — and the absence of
`branch_reviewer`.

v2.4 replaced /critic with domain review. `branch_reviewer` — the neuron-only
verb for convening a domain reviewer itself — was DELETED by owner ruling
2026-08-04 (d128's absolute reading confirmed): the planner's reviewer leg
(role="reviewer" dispatch) is the ONE review mechanism. This file pinned the
verb's round trips; it now pins the deletion (absence + positive controls,
per the codebase's standing rule) and the surviving reviewer discipline.
"""

from pathlib import Path

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"
_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def test_critic_and_branch_reviewer_are_retired():
    # the generic critic tool + briefs are gone (v2.4), and branch_reviewer
    # went with them (owner ruling 2026-08-04).
    import tempfile

    from edp_claude.server import make_context
    from edp_claude.tools import build_registry
    names = {t.name for t in build_registry(make_context(tempfile.mkdtemp()))}
    assert "consult_critic" not in names
    assert "branch_reviewer" not in names
    # POSITIVE CONTROLS: the reviewer ROLE machinery survives untouched —
    # the verdict verb is registered and the activator card exists.
    assert "record_branch_verdict" in names
    assert not (_CMD / "critic.md").exists()
    assert not (_CMD / "critic-review.md").exists()
    assert (_CMD / "reviewer.md").exists()


def test_no_role_surface_grants_branch_reviewer():
    from edp_claude.tools.roles import ROLE_TOOLSETS
    for role, toolset in ROLE_TOOLSETS.items():
        assert "branch_reviewer" not in toolset, f"{role} grants branch_reviewer"
    # POSITIVE CONTROL: the reviewer role still records verdicts.
    assert "record_branch_verdict" in ROLE_TOOLSETS["reviewer"]


def test_reviewer_brief_discipline():
    b = (_CMD / "reviewer.md").read_text(encoding="utf-8").lower()
    # 2026-06-03: the reviewer launches FRESH and loads the compiled doc —
    # it is NOT a fork of the trained chat.
    assert "fresh domain reviewer" in b
    assert "not a fork" in b and "get_specialist_doc" in b
    assert "review" in b and "verdict" in b
    assert "pass" in b and "fail" in b and "concerns" in b
    assert "check_inbox" in b and "reply" in b
    # reviews, doesn't build
    assert "building" in b or "you review" in b


def test_phase_e_routes_review_through_the_planner_leg():
    e = (_GUIDES / "neuron-phase-e.md").read_text(encoding="utf-8").lower()
    # The neuron convenes no reviewer of its own; phase E must say where the
    # judgment comes from instead.
    assert "branch_reviewer" not in e
    assert "review leg" in e
    assert "domain" in e and "review" in e


def test_phase_e_passes_concerns_and_prefers_matched_reviewer():
    # 2026-06-01 (Decision 5) survives the verb's deletion: recipe-end
    # review threads the actions' concerns into the review leg, and prefers
    # a concern-matched specialist (e.g. security) when one exists.
    e = (_GUIDES / "neuron-phase-e.md").read_text(encoding="utf-8").lower()
    assert "concerns" in e
    assert "neuron_search" in e and "security" in e
    assert "additional review leg" in e or "concern-matched" in e
