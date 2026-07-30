"""W13 (DESIGN-v6) — the automatic COMPACTION-triggered re-ground path.

This module owns the tests for the NEW W13 surface built by action a2:

  * ``.claude/hooks/reground-on-compact.py`` — the SessionStart hook that
    fires ONLY on ``source == 'compact'`` and injects a BOUNDED re-ground
    directive (no slash command, no LLM, no recipe-size dump), composing with
    the existing ``next_action(reground=true)`` / ``_reground_payload`` path
    rather than re-implementing the digest.
  * ``.claude/settings.json`` — the wiring that registers that hook under a
    ``SessionStart`` / matcher ``compact`` entry while preserving PreToolUse.

REUSED (not duplicated — d7 test-discipline) coverage. The FULL contract that
``next_action(reground=true)`` still returns the W1 digest + W2 monitor-rewire
block, and that the legacy fixture 0e7ca8 loads byte-identically, already lives
in the sibling modules and is exercised by the same ``-k`` verify selection:

  * ``tests/test_epochs.py``
      - ``test_next_action_reground_true_delivers_digest_and_rewire`` — reground
        returns the full W1 digest (``north_star``/``active_decisions``) + the
        rewire block (cron constant + roles).  [W1 digest + W2 rewire]
      - ``test_o6_legacy_fixture_byte_identical_and_epoch_computes``  [o6/d24]
  * ``tests/test_rewire.py``
      - ``test_reground_rewire_carries_actual_observe_spec`` and the rest of its
        §3–5 block — the rewire hand-back's observe specs, cron constant, and
        durable-rule notes.  [W2 monitor-rewire block]
      - ``test_o6_legacy_fixture_byte_identical``  [o6/d24]

The ONE bridge test below (``test_w13_hook_directive_names_a_live_reground_``)
only proves the exact directive token the hook injects IS a real trigger — it
asserts PRESENCE of a reground block, deferring the digest/rewire *internals*
to the modules above so nothing is duplicated.

Env discipline (d7/d8): tests run under uv/pytest on Windows; every assertion
is pure Python — no POSIX shell, no grep. The hook is imported by file path and
driven in-process (stdin via ``io.StringIO``, stdout via capsys), so no external
process/shell is spawned. Any leaked worker env (EDP_ROLE/EDP_HANDLE/
EDP_TIER_WRITE) is neutralised in-process (conftest + the local fixture).
"""

import importlib.util
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from edp_contracts import ToolOk

from edp_claude.fsm.recipe_fsm import recipe_context
from edp_claude.schemas import Recipe

REPO = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO / ".claude" / "hooks" / "reground-on-compact.py"
SETTINGS_PATH = REPO / ".claude" / "settings.json"


# ── env discipline (d7/d8): clear inherited worker env in-process ─────────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE"):
        monkeypatch.delenv(var, raising=False)


def _now():
    return datetime.now(timezone.utc)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# ── load the hyphenated hook script by file path (not importable by name) ─────
def _load_hook():
    assert HOOK_PATH.exists(), f"W13 hook missing at {HOOK_PATH}"
    spec = importlib.util.spec_from_file_location("reground_on_compact", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hook():
    return _load_hook()


def _run_main(mod, monkeypatch, capsys, stdin_text):
    """Drive the hook's main() with `stdin_text` fed on stdin; return
    (exit_code, captured_stdout)."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    rc = mod.main()
    return rc, capsys.readouterr().out


# ── 1. the hook fires ONLY on source == 'compact' (pure function) ────────────
def test_reground_context_fires_only_on_compact(hook):
    # compact → a non-empty directive string.
    out = hook.reground_context({"source": "compact"})
    assert isinstance(out, str) and out.strip()
    # every other (and malformed) source → strict None (no-op).
    for src in ("startup", "resume", "clear", "", "COMPACT", "compaction"):
        assert hook.reground_context({"source": src}) is None, src
    assert hook.reground_context({}) is None            # missing source key
    assert hook.reground_context({"source": None}) is None
    assert hook.reground_context("not-a-dict") is None  # defensive: non-dict


# ── 1b. main() over stdin: additionalContext present ONLY on compact ─────────
def test_main_emits_additionalcontext_on_compact(hook, monkeypatch, capsys):
    rc, out = _run_main(hook, monkeypatch, capsys,
                        json.dumps({"source": "compact",
                                    "hookEventName": "SessionStart"}))
    assert rc == 0
    payload = json.loads(out)                            # valid JSON on stdout
    block = payload["hookSpecificOutput"]
    assert block["hookEventName"] == "SessionStart"
    assert isinstance(block["additionalContext"], str)
    assert block["additionalContext"].strip()


@pytest.mark.parametrize("src", ["startup", "resume", "clear"])
def test_main_is_strict_noop_for_non_compact_sources(hook, monkeypatch, capsys,
                                                     src):
    rc, out = _run_main(hook, monkeypatch, capsys, json.dumps({"source": src}))
    assert rc == 0
    assert out == ""                                     # NOTHING injected


def test_main_is_failsafe_on_malformed_input(hook, monkeypatch, capsys):
    # unreadable / non-JSON stdin must NEVER break session start.
    for bad in ("{not json", "", "null", "[]", "\x00\x01"):
        rc, out = _run_main(hook, monkeypatch, capsys, bad)
        assert rc == 0, bad
        assert out == "", bad


# ── 2. the injected payload is a BOUNDED directive — no slash cmd, no LLM,
#      no recipe-size output; carries the banner + the reground directive ─────
def test_injected_payload_is_bounded_directive_not_recipe_dump(hook, monkeypatch,
                                                               capsys):
    rc, out = _run_main(hook, monkeypatch, capsys,
                        json.dumps({"source": "compact"}))
    assert rc == 0
    injected = json.loads(out)["hookSpecificOutput"]["additionalContext"]

    # it is exactly the fixed O(1) banner constant — never recipe-derived.
    assert injected == hook._BANNER

    # (a) carries the re-ground banner + the exact next-turn directive.
    assert "COMPACTED" in injected
    assert "next_action(reground=true)" in injected

    # (b) NO slash command (d36): the hook must not fire one. A slash command
    # is a '/' at a token boundary (e.g. '/compact'); plain '/' inside words
    # like 'recipe/plan' is fine. Assert no token-boundary slash exists.
    assert not re.search(r"(?<!\S)/[A-Za-z]", injected), injected

    # (c) NO recipe-size / digest output embedded here — the payload POINTS at
    # the next_action(reground=true) path; it must NOT inline the digest. The
    # banner may NAME 'digest'/'rewire' in prose (it tells the shell what it
    # will receive), but the actual digest STRUCTURE keys must be ABSENT.
    for digest_key in ("north_star", "active_decisions", "observe_specs",
                       "durable_rules", "cron_prompt"):
        assert digest_key not in injected, digest_key

    # (d) bounded: a fixed directive, not something that scales with the
    # recipe. Comfortably under a small ceiling (it is ~0.6 KB today).
    assert len(injected) < 1500

    # (e) no LLM/model output marker — it is a static constant, proven by the
    # equality above; also assert it fires no other slash-style command word.
    assert "/compact" not in injected and "/clear" not in injected


# ── 3. bridge: the token the hook injects names a LIVE reground trigger ──────
#      (PRESENCE only — the digest/rewire internals are asserted in
#      tests/test_epochs.py + tests/test_rewire.py; not duplicated here.) ─────
def _mk_recipe(env, rid="r-w13", *, decisions=(), state="executing"):
    """An EXECUTING recipe with one idle spawn_planner step, so next_action
    makes no forward move and the reground trigger table is clean to read."""
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state=state,
        comprehension={"branches": [], "curiosity_cleared": True,
                       "expected_outcomes": [
                           {"id": "o1", "description": "d",
                            "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner", "attempt": 0}],
        context={"decisions": list(decisions), "assumptions": [],
                 "rejected_options": []},
        created_at=_now(), updated_at=_now(),
    )))
    return rid


async def test_w13_hook_directive_names_a_live_reground_trigger(env, hook):
    # the exact token the hook injects into additionalContext …
    assert "next_action(reground=true)" in hook._BANNER
    # … is a REAL trigger: calling next_action(reground=True) yields a reground
    # block. (Full digest+rewire shape → test_epochs/test_rewire; here we only
    # prove the hook points the shell at a path that actually regrounds.)
    rid = _mk_recipe(env, decisions=[
        {"id": "d1", "text": "D", "rationale": "r", "by": "neuron",
         "at": _now().isoformat(), "load_bearing": True}])
    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe",
                           reground=True))
    assert "reground" in d["context"]
    assert d["context"]["reground"]["rewire"]["cron_prompt"]


# ── 4. REGRESSION: the step-count-gap backstop (recipe_fsm grew_steps>=2) ────
#      still fires. This is the SECONDARY safety net a2 left untouched. The
#      canonical Item-1 coverage is tests/test_item1_comprehension_recheck.py
#      (test_item1_recheck_on_major_step_growth); this re-exercises the exact
#      grew_steps>=2 invariant so the W13 change provably did not disturb it. ─
def _recipe_with_baseline(n_steps, base_steps, *, n_outcomes=1, base_outcomes=1):
    outcomes = [{"id": f"o{i}", "description": "d", "verification": "v"}
                for i in range(n_outcomes)]
    steps = [{"step_id": f"s{i}", "kind": "work", "description": "d",
              "status": "pending", "depends_on": [],
              "execution": "spawn_planner", "attempt": 0}
             for i in range(n_steps)]
    return Recipe.model_validate(dict(
        recipe_id="r-w13-bk", user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "curiosity_cleared": True,
                       "expected_outcomes": outcomes,
                       "baseline": {"n_steps": base_steps,
                                    "n_outcomes": base_outcomes}},
        steps=steps, context={},
        created_at=_now(), updated_at=_now(),
    ))


def test_w13_step_count_gap_backstop_still_fires():
    # grew from 2 -> 4 steps (>=2 more, no new outcome) → the backstop fires.
    ctx = recipe_context(_recipe_with_baseline(n_steps=4, base_steps=2))
    assert "comprehension_recheck" in ctx
    assert "SCOPE CHANGE" in ctx["comprehension_recheck"]


def test_w13_step_count_gap_backstop_below_threshold_is_silent():
    # +1 step, no new outcome → below the grew_steps>=2 threshold → no fire.
    ctx = recipe_context(_recipe_with_baseline(n_steps=3, base_steps=2))
    assert "comprehension_recheck" not in ctx


# ── 5. the settings.json wiring: SessionStart(compact) registered, PreToolUse
#      preserved. (o6 byte-identity of 0e7ca8 → test_epochs/test_rewire.) ────
def test_settings_wires_sessionstart_compact_hook_preserving_pretooluse():
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    hooks = settings["hooks"]

    # SessionStart is registered with matcher 'compact' → the reground hook.
    sessionstart = hooks["SessionStart"]
    compact_entries = [e for e in sessionstart if e.get("matcher") == "compact"]
    assert len(compact_entries) == 1, sessionstart
    cmds = [h["command"] for h in compact_entries[0]["hooks"]
            if h.get("type") == "command"]
    assert any("reground-on-compact.py" in c for c in cmds), cmds
    # follows the existing pattern: the venv python invokes the hook script.
    assert all("python.exe" in c for c in cmds), cmds

    # the pre-existing PreToolUse hooks are preserved intact (Bash + PowerShell).
    matchers = {e.get("matcher") for e in hooks["PreToolUse"]}
    assert {"Bash", "PowerShell"} <= matchers, matchers
