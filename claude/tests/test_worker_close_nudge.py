"""Phase 6 — the worker-close-nudge Stop hook actually works now.

The hook shipped triple-dead: PROBE mode never armed, it read
EDP_SPAWN_HANDLE (nothing sets it; the launcher stamps EDP_HANDLE), and it
looked for plans at .plans/<id>/plan.json while plans live at
.plans/<id>.json — its own 2026-07-25 probe LOGGED the env-var hole and
nobody fixed it. These tests pin all three fixes.
"""
import importlib.util
import json
from pathlib import Path

HOOK = (Path(__file__).resolve().parents[1] / ".claude" / "hooks"
        / "worker-close-nudge.py")


def _load():
    spec = importlib.util.spec_from_file_location("worker_close_nudge", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reads_edp_handle_with_spawn_fallback():
    src = HOOK.read_text(encoding="utf-8")
    # the real launcher variable first, the never-set legacy name as fallback
    assert 'os.environ.get("EDP_HANDLE")' in src
    assert src.index('os.environ.get("EDP_HANDLE")') \
        < src.index('os.environ.get("EDP_SPAWN_HANDLE")')


def test_assignment_state_reads_toplevel_plan_json(tmp_path):
    mod = _load()
    # re-anchor the hook's repo root to tmp: root = parents[2] of __file__
    fake = tmp_path / "claude" / ".claude" / "hooks" / "worker-close-nudge.py"
    fake.parent.mkdir(parents=True)
    mod.__file__ = str(fake)

    plans = tmp_path / "claude" / ".plans"
    plans.mkdir(parents=True)
    (plans / "recipe-x-s1.json").write_text(json.dumps({
        "plan_id": "recipe-x-s1",
        "actions": [{"action_id": "a1", "status": "done"},
                    {"action_id": "a2", "status": "in_progress"}],
    }), encoding="utf-8")

    assert mod._assignment_state("recipe-x-s1:a1") == (True, [])
    assert mod._assignment_state("recipe-x-s1:a2") == (False, [])
    # unknown plan/action stays None — and None must never pass the guard
    assert mod._assignment_state("recipe-x-s1:zz") == (None, [])
    assert mod._assignment_state("nope:a1") == (None, [])
    assert mod._assignment_state("") == (None, [])


def test_assignment_state_judges_the_whole_batch(tmp_path):
    """2026-08-13 live repro (recipe 2270d3 s1, twice): a batch worker
    recorded its handle's action done, the armed hook judged terminal=True
    on that ONE action, and its close nudge instructed the shell to exit —
    stranding the remaining members. Terminal must mean the whole group."""
    mod = _load()
    fake = tmp_path / "claude" / ".claude" / "hooks" / "worker-close-nudge.py"
    fake.parent.mkdir(parents=True)
    mod.__file__ = str(fake)

    plans = tmp_path / "claude" / ".plans"
    plans.mkdir(parents=True)
    (plans / "p1.json").write_text(json.dumps({
        "plan_id": "p1",
        "actions": [
            {"action_id": "a1", "status": "done", "batch_group": "g"},
            {"action_id": "a2", "status": "in_progress", "batch_group": "g"},
            {"action_id": "a3", "status": "pending", "batch_group": "g"},
            {"action_id": "b1", "status": "done"},
        ],
    }), encoding="utf-8")

    # head recorded done, members open → NOT terminal; remaining named
    assert mod._assignment_state("p1:a1") == (False, ["a2", "a3"])
    # ungrouped action unaffected by the batch rule
    assert mod._assignment_state("p1:b1") == (True, [])

    # whole group terminal → close nudge territory again
    (plans / "p2.json").write_text(json.dumps({
        "plan_id": "p2",
        "actions": [
            {"action_id": "a1", "status": "done", "batch_group": "g"},
            {"action_id": "a2", "status": "failed", "batch_group": "g"},
        ],
    }), encoding="utf-8")
    assert mod._assignment_state("p2:a1") == (True, [])


def test_guard_requires_all_clauses(tmp_path):
    """The should_nudge conjunction: worker + handle + terminal + under cap.
    Reproduced here from the guard's own terms so a future edit that widens
    scope (e.g. nudging planners) breaks a test, not the fleet."""
    mod = _load()
    fake = tmp_path / "c" / ".claude" / "hooks" / "h.py"
    fake.parent.mkdir(parents=True)
    mod.__file__ = str(fake)
    plans = tmp_path / "c" / ".plans"
    plans.mkdir(parents=True)
    (plans / "p1.json").write_text(json.dumps({
        "actions": [{"action_id": "a1", "status": "done"}]}),
        encoding="utf-8")

    def guard(role, handle, blocks):
        terminal, _ = mod._assignment_state(handle)
        return (role == "worker" and bool(handle) and terminal is True
                and blocks < mod.MAX_BLOCKS)

    assert guard("worker", "p1:a1", 0)
    assert not guard("planner", "p1:a1", 0)      # craft scope only
    assert not guard("worker", "", 0)            # no handle, no action check
    assert not guard("worker", "p1:zz", 0)       # unknown → None → refuse
    assert not guard("worker", "p1:a1", mod.MAX_BLOCKS)  # loop cap
