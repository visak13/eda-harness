"""DESIGN-v6 W7 (items 4 + 6) — canonical RECONCILE-LOOP cron prompt.

Guards the single source of truth for the neuron+planner heartbeat cron
prompt and the retirement of the ScheduleWakeup-long-prompt pattern:

  * ONE importable module-level constant with the EXACT canonical value.
  * Scoped to neuron + planner ONLY (worker/curiosity keep their own
    check_inbox prompts — deliberately NOT this constant).
  * No stale long-prompt cron literal survives in the code paths that
    reference the canonical string.
"""

import inspect
from pathlib import Path

from edp_claude import cadence


# The exact, load-bearing value (DESIGN-v6 lines 383, 389). Spelled out
# literally here so a reword of the constant fails the assertion.
_CANONICAL = (
    "call reconcile then next_action and obey wait_hint: "
    "if it says wait, end your turn"
)


def test_constant_exact_value():
    assert cadence.RECONCILE_LOOP_CRON_PROMPT == _CANONICAL


def test_constant_importable_from_canonical_home():
    # Importable as a plain module-level constant (no call, no LLM).
    from edp_claude.cadence import RECONCILE_LOOP_CRON_PROMPT
    assert RECONCILE_LOOP_CRON_PROMPT == _CANONICAL


def test_single_source_reexported_not_respelled():
    # _tools.py must IMPORT the constant (single source), not re-spell it.
    from edp_claude.tools import _tools
    assert _tools.RECONCILE_LOOP_CRON_PROMPT is cadence.RECONCILE_LOOP_CRON_PROMPT


def test_scoped_to_neuron_and_planner_only():
    roles = cadence.RECONCILE_LOOP_ROLES
    assert set(roles) == {"neuron", "planner"}
    # Worker + curiosity must NOT be armed with the reconcile-loop prompt —
    # they keep their existing check_inbox-based Step-0 prompts.
    assert "worker" not in roles
    assert "curiosity" not in roles


def test_prompt_is_never_the_verbatim_goal():
    # The invariant: the cron prompt is a short reflex, never a per-recipe
    # goal. Guard the length so a future goal-as-prompt regression is caught.
    assert len(cadence.RECONCILE_LOOP_CRON_PROMPT) < 120
    assert "reconcile" in cadence.RECONCILE_LOOP_CRON_PROMPT
    assert "next_action" in cadence.RECONCILE_LOOP_CRON_PROMPT


def test_no_retired_long_prompt_cron_literal_in_touched_paths():
    # The ScheduleWakeup-long-prompt pattern is retired: the cadence module
    # (the code path this action authored) must not arm a cron with a long
    # multi-sentence prompt string. Only the short canonical constant lives
    # here.
    src = Path(cadence.__file__).read_text(encoding="utf-8")
    # No stray reconcile-loop-style prompt literal other than the canonical
    # one (which is assembled from two adjacent string fragments).
    assert src.count("call reconcile then next_action") == 1
    # The retired pattern paired ScheduleWakeup with a long prompt; the code
    # path carries no such call.
    assert "ScheduleWakeup(" not in src


def test_cadence_knobs_are_the_shared_home():
    # The cadence config lives beside the canonical string and _tools uses it.
    from edp_claude.tools import _tools
    assert _tools._heartbeat_secs is cadence.heartbeat_secs
    assert _tools._wait_escalate_secs is cadence.wait_escalate_secs
    assert _tools._wait_escalate_multiplier is cadence.wait_escalate_multiplier
    assert isinstance(cadence.heartbeat_secs(), int)
    assert isinstance(cadence.wait_escalate_multiplier(), int)
    assert isinstance(cadence.wait_escalate_secs(600), int)
    # The helpers are plain deterministic functions (principle 6).
    assert not inspect.iscoroutinefunction(cadence.heartbeat_secs)
