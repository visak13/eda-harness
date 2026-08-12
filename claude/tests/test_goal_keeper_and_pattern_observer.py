"""goal_keeper + pattern_observer are DEAD ROLES (owner ruling 2026-08-04).

This file pinned the Phase-6 (2026-05-21) externality substrate: consult-spawn
-reply round trips, spawn roles, brief discipline. The owner ruled both roles
dead and everything was deleted — tool classes, role rows, tier rows, spawn
methods, activator cards. What remains to pin is the ABSENCE, each half with a
positive control so a clean sweep is never a dead sweep (the codebase's
standing absence-testing rule).
"""

from pathlib import Path

from edp_claude.tools._tools import ALL_TOOL_CLASSES
from edp_claude.tools.roles import CRUD_OBJECT_SCOPE, ROLE_TOOLSETS

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"

_DEAD_ROLES = ("goal_keeper", "pattern_observer")
_DEAD_VERBS = ("consult_goal_keeper", "consult_pattern_observer")
_DEAD_CARDS = ("goal-keeper.md", "goal-keeper-check.md", "pattern-observer.md")


def test_dead_role_tools_are_deregistered():
    names = {cls.name for cls in ALL_TOOL_CLASSES}
    for verb in _DEAD_VERBS:
        assert verb not in names, f"{verb} is back in the registry"
    # POSITIVE CONTROL: the surviving advisory consult is still registered.
    assert "consult_curiosity" in names


def test_dead_roles_have_no_row_anywhere():
    # (The MODEL_TIERS half of this pin went with the table itself —
    # 2026-08-12 dead-surface retirement; test_w10b_benchmark.py pins that.)
    for role in _DEAD_ROLES:
        assert role not in ROLE_TOOLSETS, f"{role} has a toolset row again"
        assert role not in CRUD_OBJECT_SCOPE, f"{role} has a CRUD row again"
    # POSITIVE CONTROL: curiosity keeps both rows.
    assert "curiosity" in ROLE_TOOLSETS
    assert "curiosity" in CRUD_OBJECT_SCOPE


def test_no_surface_grants_the_dead_consult_verbs():
    for role, toolset in ROLE_TOOLSETS.items():
        for verb in _DEAD_VERBS:
            assert verb not in toolset, f"{role} grants {verb}"
    # POSITIVE CONTROL: the neuron still holds the surviving consult.
    assert "consult_curiosity" in ROLE_TOOLSETS["neuron"]


def test_dead_activator_cards_are_gone():
    for card in _DEAD_CARDS:
        assert not (_CMD / card).exists(), f"{card} is back"
    # POSITIVE CONTROL: the sweep is looking at the real commands dir.
    assert (_CMD / "curiosity.md").exists()
