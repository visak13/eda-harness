"""DESIGN-v7 Phase 8 — the grounding brief (kill the triple read).

The planner writes ONE code map per plan (record_grounding_brief); the
dispatcher injects it by-id into every worker's grounding and the reviewer
brief, and its `paths` arm the 1.5.6 staleness fingerprint.
"""

from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _plan(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="do work"))
    return rid, pid


BRIEF = ("# map\n- src/widget.py: the widget core (class Widget)\n"
         "- landmine: helpers.py looks unused but backs the CLI\n")


async def test_brief_stored_stamped_and_fingerprinted(env):
    _rid, pid = await _plan(env)
    out = _ok(await env.call("record_grounding_brief", plan_id=pid,
                             content=BRIEF,
                             paths=["src/widget.py", "src/helpers.py"]))
    p = env.ctx.plans.load(pid)
    assert p.grounding_brief_path == out["path"]
    assert env.ctx.plans.read_grounding_brief(pid) == BRIEF
    assert set(p.grounding_fingerprint) == {"src/widget.py",
                                            "src/helpers.py"}
    # re-record: living map — content replaced, paths deduped
    _ok(await env.call("record_grounding_brief", plan_id=pid,
                       content=BRIEF + "corrected\n",
                       paths=["src/widget.py", "tests/test_widget.py"]))
    p = env.ctx.plans.load(pid)
    assert len(p.grounding_fingerprint) == 3


async def test_empty_brief_is_refused(env):
    _rid, pid = await _plan(env)
    res = await env.call("record_grounding_brief", plan_id=pid, content="  ")
    assert not isinstance(res, ToolOk)


async def test_dispatch_injects_the_brief_into_the_worker_grounding(env):
    _rid, pid = await _plan(env)
    _ok(await env.call("record_grounding_brief", plan_id=pid, content=BRIEF,
                       paths=["src/widget.py"]))
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1"))
    a = _ok(await env.call("read_object", type="action",
                           ids={"plan_id": pid, "action_id": "a1"}))
    grounding = a.get("grounding") or a
    blob = str(grounding)
    assert "the widget core" in blob, (
        "the worker's read_object('action') grounding must resolve the "
        f"grounding_brief pointer to full text; got keys {list(a)}")


# ── the injection cap must be LOUD at both ends ───────────────────────────
# Live incident 2026-07-25 (Fit s13): a brief was cut MID-SENTENCE at the cap
# with no marker. record_grounding_brief had reported success, so the planner
# believed it had transferred knowledge it had not, and the worker could not
# tell a brief that ENDED from one that was CUT. Caught ONLY because the
# worker happened to mention it. The cap is fine; the silence was the defect.

TAIL = "LANDMINE: never index on a boolean, it is not a valid key"


def _oversized() -> str:
    """A brief past the cap whose LAST line is the load-bearing one."""
    from edp_claude.tools._tools import _GROUNDING_BRIEF_INJECT_CAP as CAP
    return ("# map\n" + ("filler line that is pure orientation\n" * 400)
            )[:CAP + 500] + "\n" + TAIL + "\n"


async def test_planner_is_TOLD_at_write_time_when_the_brief_will_be_cut(env):
    """The write side must not report a bare success on a brief it knows
    cannot be delivered whole — that is what let the planner dispatch blind."""
    from edp_claude.tools._tools import _GROUNDING_BRIEF_INJECT_CAP as CAP
    _rid, pid = await _plan(env)
    big = _oversized()
    assert len(big) > CAP, "fixture must actually exceed the cap"
    out = _ok(await env.call("record_grounding_brief", plan_id=pid,
                             content=big, paths=["src/widget.py"]))
    note = out["note"]
    assert "ONLY THE FIRST" in note and str(CAP) in note, (
        "an oversized brief must be reported as oversized AT WRITE TIME, "
        f"naming the cap; got note={note!r}")
    assert str(len(big) - CAP) in note, (
        "the note must say HOW MUCH is being dropped, not merely that "
        f"something is; got note={note!r}")
    # the STORE still keeps it whole — the cap is a delivery limit only
    assert env.ctx.plans.read_grounding_brief(pid) == big


async def test_a_brief_within_the_cap_is_NOT_warned_about(env):
    """Guard against the inverse failure: a warning on every brief is a
    warning on none."""
    _rid, pid = await _plan(env)
    out = _ok(await env.call("record_grounding_brief", plan_id=pid,
                             content=BRIEF, paths=["src/widget.py"]))
    assert "ONLY THE FIRST" not in out["note"], out["note"]
    assert "travels whole" in out["note"], out["note"]


async def test_the_WORKER_is_told_its_brief_was_cut(env):
    """The delivered text must carry a marker at the cut. A worker that
    cannot tell 'ended' from 'was cut' will build against half a map and
    report success."""
    _rid, pid = await _plan(env)
    big = _oversized()
    _ok(await env.call("record_grounding_brief", plan_id=pid, content=big,
                       paths=["src/widget.py"]))
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1"))
    a = _ok(await env.call("read_object", type="action",
                           ids={"plan_id": pid, "action_id": "a1"}))
    blob = str(a.get("grounding") or a)
    assert "TRUNCATED" in blob, (
        "the injected brief must announce its own truncation; a silent cut "
        "is indistinguishable from a brief that simply ended")
    assert "ASK YOUR PLANNER" in blob, (
        "the marker must tell the worker HOW to recover the tail, not just "
        "that it is missing")
    # THE POINT OF THE WHOLE FIX: the dropped tail is the landmine half.
    assert TAIL not in blob, (
        "fixture is wrong — the tail must actually be beyond the cap, "
        "otherwise this test proves nothing")
