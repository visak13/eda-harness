"""W11 a6 (DESIGN-v6 §W11) — `resume_recipe`, the suspended-dispatch guard,
and the FSM's suspension surface.

Resume is the inverse of suspend: true the record up to reality, re-ground, put
the planners back. The bar this module pins:

  * a manifested resume FORKS each in-flight step's planner onto the claude
    session suspend snapshotted (`resume_session`), which is what drives
    `--resume <base> --session-id <fork> --fork-session`;
  * a resume with NO manifest is the ordinary CRASH path (power loss, killed
    stack), not an error — it degrades to reconcile + digest + fresh spawns;
  * WORKERS are never re-dispatched by resume. Reconcile returns their reaped
    `in_progress` actions to `pending` and the normal `next_action` flow picks
    them up fresh — which is why resume never needs, and never passes,
    `pool_spawn_worker(force=true)`. Asserting ZERO worker spawns is the
    stronger claim: a kwarg cannot be wrong on a call that never happens;
  * resume is IDEMPOTENT. It spawns planners BEFORE clearing `suspended_at`, so
    a crash between the two leaves live planners under a parked recipe — noisy
    but VISIBLE (dispatch is refused), which beats clear-then-spawn's silent
    "live recipe with no planners". Recovery is to re-run it, so a second run
    must ASK THE POOL which step handles are live and skip them, never assume a
    duplicate spawn would be refused by lock-by-spawn lifetime. This also
    mitigates the in_progress dispatch window the W2 dup-guard does not cover;
  * suspend and resume DERIVE THE PLANNER SET DIFFERENTLY (d59, seen live in
    a10): suspend snapshots any LIVE planner from the pool registry, resume
    respawns only the planners of `in_progress` steps. The sets agree by
    construction on the sanctioned path and diverge off it. A diverging row is
    WARN-logged and counted (`planners_orphaned`), never silently dropped, and
    the resume `note` is DERIVED from those counters — so a resume that put back
    nothing, or that dropped a live planner, cannot read as success. The union is
    rejected on purpose: respawning a snapshot planner for a `pending` step
    double-dispatches against next_action, and for a `done` step resurrects
    finished work;
  * a parked recipe REFUSES dispatch — `pool_spawn_worker` AND
    `pool_spawn_planner` — and both succeed once `suspended_at` is cleared;
  * that refusal is a TOOL-surface guard, and the PORT stays open on purpose:
    resume must spawn while `suspended_at` is still set. Both halves are pinned
    here, because only the pair states the contract;
  * a parked recipe's planner is dead BY DESIGN, so `reconcile` must not
    crash-recover it — doing so would burn the step's one re-dispatch budget and
    strand resume with nothing to fork;
  * `recipe_context` surfaces the parked flag on the first tick.

SAFETY (assumption a5/RP-A + a3): every test builds its OWN recipe in `tmp_path`.
No real recipe is ever suspended or resumed — suspending THIS recipe would park
the planner that dispatched the work.

Env discipline (d7/d8): the autouse conftest fixture clears the leaked
EDP_ROLE/EDP_HANDLE; every assertion is pure Python (the acceptance verify shell
has no `env` binary — an `env -u VAR …` prefix exits 127, read as FAILED).
"""

import json
from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.fsm.recipe_fsm import recipe_context
from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import PlanState
from edp_claude.tools import _tools

RECIPE_ID = "r-resume"
STEP_ID = "s1"
PLAN_ID = f"{RECIPE_ID}-{STEP_ID}"
PLANNER_HANDLE = f"{RECIPE_ID}:{STEP_ID}"          # pool session handle (colon)
WORKER_HANDLE = f"{PLAN_ID}:a1"
ACTION_ID = "a1"


def _now():
    return datetime.now(timezone.utc)


# ── a temp fixture recipe — NEVER a real one ─────────────────────────────────
def _steps(*specs: tuple[str, str]) -> list[dict]:
    """`(step_id, status)` pairs → step dicts. Lets a test spell the DIVERGENCE
    shape (a step that is not `in_progress`) without hand-writing the boilerplate
    five times."""
    return [{"step_id": sid, "kind": "work", "description": "d",
             "status": status, "depends_on": [], "execution": "spawn_planner"}
            for sid, status in specs]


def _recipe(steps: list[dict] | None = None, **over) -> Recipe:
    return Recipe.model_validate(dict(
        recipe_id=RECIPE_ID, user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=steps if steps is not None else _steps((STEP_ID, "in_progress")),
        context={"decisions": [], "assumptions": [], "rejected_options": []},
        created_at=_now(), updated_at=_now(), **over,
    ))


@pytest.fixture(autouse=True)
def _instant_grace(monkeypatch):
    """Collapse suspend's bounded wait so setup never sleeps."""
    monkeypatch.setattr(_tools, "SUSPEND_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(_tools, "SUSPEND_POLL_SECS", 0.0)


@pytest.fixture(autouse=True)
def _no_foreground_log(monkeypatch):
    """An EMPTY foreground registry — without this the reader would read the
    REAL repo log. Resume never needs it; suspend records a null session."""
    monkeypatch.setattr(_tools, "latest_foreground_session", lambda: None)
    monkeypatch.setattr(_tools, "foreground_session_by_id", lambda _sid: None)


class _LogSpy:
    """A `LoggerLike` double. The real logger sets `propagate = False`, so a
    root-handler capture (`caplog`) never sees its records — substituting the
    module's `_log` is the only way to assert a WARN was emitted, and it also
    pins the structured FIELDS, not just the prose."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def _rec(self, level, kind, detail, **fields):
        self.records.append(
            {"level": level, "kind": kind, "detail": detail, **fields})

    def debug(self, kind, detail, **f): self._rec("debug", kind, detail, **f)
    def info(self, kind, detail, **f): self._rec("info", kind, detail, **f)
    def warning(self, kind, detail, **f): self._rec("warning", kind, detail, **f)
    def error(self, kind, detail, **f): self._rec("error", kind, detail, **f)


@pytest.fixture
def logspy(monkeypatch) -> _LogSpy:
    spy = _LogSpy()
    monkeypatch.setattr(_tools, "_log", spy)
    return spy


def _warnings(spy: _LogSpy, kind: str) -> list[dict]:
    return [r for r in spy.records
            if r["level"] == "warning" and r["kind"] == kind]


@pytest.fixture
def recipe(env):
    env.ctx.recipes.save(_recipe())
    return env.ctx.recipes.load(RECIPE_ID)


async def _plan_with_open_action(env):
    """A DISPATCHING plan carrying one in_progress action — the shape a plan has
    while a worker is running it, which is what suspend interrupts."""
    await env.call("create_plan", recipe_id=RECIPE_ID, step_id=STEP_ID,
                   shape="linear", goal="do the thing")
    await env.call("add_action", plan_id=PLAN_ID, action_id=ACTION_ID,
                   description="build it")
    plan = env.ctx.plans.load(PLAN_ID)
    plan.state = PlanState.DISPATCHING
    plan.actions[0].status = "in_progress"
    env.ctx.plans.save(plan)


async def _spawn(env, *, planners=(PLANNER_HANDLE,), workers=(WORKER_HANDLE,)):
    """Populate the stub pool with live planner/worker rows. Returns the planner
    handle -> pinned claude session id, which is what a resume forks from."""
    sessions: dict[str, str] = {}
    for handle in planners:
        rid, step = handle.split(":", 1)
        res = await env.ctx.pool.spawn_planner(rid, step)
        sessions[handle] = res.data["claude_session_id"]
    for handle in workers:
        pid, action = handle.rsplit(":", 1)
        await env.ctx.pool.spawn_worker(pid, action)
    return sessions


async def _park(env, **spawn_kw) -> dict[str, str]:
    """The realistic setup: build the plan, spawn the shells, then run the REAL
    suspend_recipe. Driving a5's writer (rather than hand-stamping a manifest)
    is what makes a writer/reader drift show up as a failure here."""
    await _plan_with_open_action(env)
    sessions = await _spawn(env, **spawn_kw)
    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID, reason="restart")
    assert isinstance(res, ToolOk), res
    return sessions


def _planner_spawns(env) -> list[dict]:
    return [s for s in env.ctx.pool.spawns if s["role"] == "planner"]


def _worker_spawns(env) -> list[dict]:
    return [s for s in env.ctx.pool.spawns if s["role"] == "worker"]


def _events(env) -> list[dict]:
    path = env.ctx.recipes.root / RECIPE_ID / "events.jsonl"
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _manifest_path(env):
    return env.ctx.recipes.root / RECIPE_ID / _tools.SUSPEND_MANIFEST_NAME


# ════════════════════════════════════════════════════════════════════════
# (a) the manifested resume — planners are FORKED back onto their sessions
# ════════════════════════════════════════════════════════════════════════
async def test_resume_with_manifest_respawns_planner_with_resume_session(env,
                                                                         recipe):
    sessions = await _park(env)
    base = sessions[PLANNER_HANDLE]
    assert _planner_spawns(env) == [], "suspend reaped the planner"

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert isinstance(res, ToolOk), res
    assert res.data["manifest_found"] is True
    assert res.data["planners_respawned"] == 1
    assert res.data["planners_forked"] == 1
    # the fork names the EXACT session suspend snapshotted — passing it beside
    # the pool client's fresh pin is what drives --resume/--fork-session.
    spawned = _planner_spawns(env)
    assert len(spawned) == 1
    assert spawned[0]["handle"] == PLANNER_HANDLE
    assert spawned[0]["resume_session"] == base
    assert spawned[0]["claude_session"] != base, "a fork, not a mutation"


async def test_the_forked_session_is_the_one_the_manifest_recorded(env, recipe):
    """Cross-check the two artifacts rather than trusting one: the resume_session
    handed to the pool must equal the manifest's snapshot for that handle."""
    await _park(env)
    manifest = json.loads(_manifest_path(env).read_text(encoding="utf-8"))
    snapshot = {s["handle"]: s["claude_session_id"] for s in manifest["sessions"]}

    await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert _planner_spawns(env)[0]["resume_session"] == snapshot[PLANNER_HANDLE]


async def test_resume_reports_the_reground_digest_and_canonical_heartbeat(env,
                                                                          recipe):
    await _park(env)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    # (c) re-ground via the W1 digest — passed through in FULL (#18 class (b):
    # a grounding-delivery payload is bounded at author time, never truncated).
    assert res.data["digest"]["recipe_id"] == RECIPE_ID
    assert res.data["digest"]["north_star"]["user_goal_verbatim"] == \
        "user asked for X"
    # (f) the heartbeat is re-armed from the CANONICAL cadence constant —
    # imported, never re-spelled as a new string.
    from edp_claude.cadence import RECONCILE_LOOP_CRON_PROMPT
    assert res.data["rewire"]["heartbeat"]["cron_prompt"] == \
        RECONCILE_LOOP_CRON_PROMPT


# ════════════════════════════════════════════════════════════════════════
# (b) the CRASH path — no manifest is normal, not an error
# ════════════════════════════════════════════════════════════════════════
async def test_resume_without_a_manifest_succeeds_via_reconcile_alone(env,
                                                                      recipe):
    """Power loss / killed stack: `suspended_at` was never stamped and no
    manifest exists. Everything durable is already on disk, so resume must work
    — degrading only to a FRESH planner (no session to fork)."""
    await _plan_with_open_action(env)
    await _spawn(env)
    # crash: the shells are gone and the recipe was parked without a manifest
    await env.ctx.pool.reap(PLANNER_HANDLE)
    await env.ctx.pool.reap(WORKER_HANDLE)
    r = env.ctx.recipes.load(RECIPE_ID)
    r.suspended_at = _now().isoformat()
    env.ctx.recipes.save(r)
    assert not _manifest_path(env).exists()

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert isinstance(res, ToolOk), res
    assert res.data["manifest_found"] is False
    assert res.data["planners_respawned"] == 1
    assert res.data["planners_forked"] == 0, "nothing to fork from"
    assert _planner_spawns(env)[0]["resume_session"] is None
    assert env.ctx.recipes.load(RECIPE_ID).suspended_at is None


async def test_crash_path_forks_from_the_live_registry_when_the_pool_survived(
        env, recipe):
    """The neuron died but the pool did not: its registry still names the
    planner's pinned session, so a manifest-less resume can still fork."""
    sessions = await _plan_and_park_without_manifest(env)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert res.data["manifest_found"] is False
    assert res.data["planners_forked"] == 1
    assert _planner_spawns(env)[-1]["resume_session"] == sessions[PLANNER_HANDLE]


async def _plan_and_park_without_manifest(env):
    """A parked recipe whose planner row is still in the pool but NOT active."""
    await _plan_with_open_action(env)
    sessions = await _spawn(env)
    # the row survives (registry intact) but the shell is gone
    env.ctx.pool._dead.add(PLANNER_HANDLE)
    r = env.ctx.recipes.load(RECIPE_ID)
    r.suspended_at = _now().isoformat()
    env.ctx.recipes.save(r)
    return sessions


async def test_a_corrupt_manifest_degrades_to_the_crash_path(env, recipe):
    """A damaged optimization must never block a resume — but it is logged, not
    silently swallowed, because losing session continuity in silence looks
    exactly like a clean crash-resume."""
    await _park(env)
    _manifest_path(env).write_text("{not json", encoding="utf-8")

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert isinstance(res, ToolOk), res
    assert res.data["manifest_found"] is False
    assert res.data["planners_respawned"] == 1


async def test_unknown_recipe_is_a_precondition_error(env):
    res = await env.call("resume_recipe", recipe_id="no-such-recipe")
    assert isinstance(res, ToolError)
    assert "no recipe" in res.message


# ════════════════════════════════════════════════════════════════════════
# (c) workers: never forked, never re-dispatched, never force=true
# ════════════════════════════════════════════════════════════════════════
async def test_resume_spawns_no_workers_at_all(env, recipe):
    """Spec item 1e. Workers are disposable: reconcile returns their actions to
    `pending` and next_action re-dispatches them fresh. So resume cannot
    re-dispatch a done/needs_review action, and cannot pass `force=true` — there
    is no worker spawn on which either could be wrong."""
    await _park(env)

    await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert _worker_spawns(env) == []
    assert all("force" not in s for s in env.ctx.pool.spawns)


async def test_reconcile_returns_the_reaped_workers_action_to_pending(env,
                                                                      recipe):
    """The 'in-flight action statuses trued up from worklogs' half of step (b):
    suspend left the action `in_progress` on purpose; resume's plan-level
    reconcile is what hands it back to next_action."""
    await _park(env)
    assert env.ctx.plans.load(PLAN_ID).actions[0].status == "in_progress"

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert env.ctx.plans.load(PLAN_ID).actions[0].status == "pending"
    assert res.data["reconciled"] is True


@pytest.mark.parametrize("status", ["done", "needs_review"])
async def test_resume_never_redispatches_delivered_work(env, recipe, status):
    """A terminal-ish action is delivered work. Resume must not touch it — and
    must not reset it to pending either."""
    await _park(env)
    plan = env.ctx.plans.load(PLAN_ID)
    plan.actions[0].status = status
    env.ctx.plans.save(plan)

    await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert env.ctx.plans.load(PLAN_ID).actions[0].status == status
    assert _worker_spawns(env) == []


# ════════════════════════════════════════════════════════════════════════
# (d) IDEMPOTENCE — a second resume must not double-spawn a planner
# ════════════════════════════════════════════════════════════════════════
async def test_resume_twice_yields_one_live_planner_per_in_flight_step(env,
                                                                       recipe):
    """The recovery path for a crash between "spawn planners" and "clear
    suspended_at" is simply to run resume again. It must therefore ASK THE POOL
    which handles are live and skip them — not assume a second spawn would be
    refused. Also the in_progress dispatch window the W2 dup-guard misses."""
    await _park(env)

    first = await env.call("resume_recipe", recipe_id=RECIPE_ID)
    second = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert first.data["planners_respawned"] == 1
    assert first.data["planners_skipped_live"] == 0
    assert second.data["planners_respawned"] == 0
    assert second.data["planners_skipped_live"] == 1
    live = [s for s in _planner_spawns(env) if s["handle"] == PLANNER_HANDLE]
    assert len(live) == 1, "exactly one planner per in_progress step"


async def test_resume_after_an_interrupted_resume_completes_the_unpark(env,
                                                                       recipe):
    """Simulate the crash between (d) and (f): planners are back but the recipe
    is still stamped. Re-running resume must clear the stamp without spawning a
    second planner."""
    await _park(env)
    await env.ctx.pool.spawn_planner(RECIPE_ID, STEP_ID)   # (d) happened
    r = env.ctx.recipes.load(RECIPE_ID)
    r.suspended_at = _now().isoformat()                    # (f) did not
    env.ctx.recipes.save(r)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert res.data["planners_skipped_live"] == 1
    assert res.data["planners_respawned"] == 0
    assert env.ctx.recipes.load(RECIPE_ID).suspended_at is None
    assert len(_planner_spawns(env)) == 1


async def test_a_failing_planner_spawn_does_not_strand_the_recipe_parked(env,
                                                                         recipe,
                                                                         monkeypatch):
    """Individually non-fatal (suspend's discipline, inverted): a resume that
    aborts on one bad spawn leaves the recipe parked — and a parked recipe can
    dispatch NOTHING, including the retry."""
    await _park(env)

    async def refusing_spawn(*_a, **_kw):
        raise RuntimeError("pool at capacity")

    monkeypatch.setattr(env.ctx.pool, "spawn_planner", refusing_spawn)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert isinstance(res, ToolOk), "the resume completed despite the failure"
    assert res.data["planners_failed"] == 1
    assert res.data["planners_respawned"] == 0
    assert env.ctx.recipes.load(RECIPE_ID).suspended_at is None


# ════════════════════════════════════════════════════════════════════════
# (d2) the suspend/resume DIVERGENCE (d59, found live in a10)
#
# suspend snapshots ANY live planner from the pool registry; resume selects its
# respawn targets from `_in_flight_steps` (in_progress only). The two sets agree
# BY CONSTRUCTION on the sanctioned path — recipe_fsm stamps a step in_progress
# AT DISPATCH, before the planner spawns — and diverge off it. What shipped:
# the diverging row was dropped in SILENCE while the note claimed,
# unconditionally, that "planners of in-flight steps are back". The note was a
# reassuring string not guarded by the thing it asserted.
#
# The union is REJECTED, deliberately (see `_orphaned_planner_rows`): respawning
# a snapshot planner for a `pending` step would double-dispatch against
# next_action, and for a `done` step would resurrect finished work. So the drop
# STILL HAPPENS — it is merely no longer silent. These tests pin the reporting,
# and pin that the respawn set did NOT grow.
#
# Every assertion below was mutation-proved RED before being accepted green.
# ════════════════════════════════════════════════════════════════════════
DIVERGED_STEP_ID = "s2"
DIVERGED_HANDLE = f"{RECIPE_ID}:{DIVERGED_STEP_ID}"
ORPHAN_WARN = "resume_planner_row_orphaned"

# The note's three semantic markers. Asserting these (not the whole string) is
# what makes "did this resume read as a success?" a property, not a spelling.
_BACK = "are back"                       # emitted iff a planner was respawned
_NONE_BACK = "NO planners were put back"  # emitted iff none was
_NOT_RESPAWNED = "NOT respawned"         # emitted iff a live row was dropped


async def _park_planners(env, *planner_handles) -> dict[str, str]:
    """Suspend the saved recipe with exactly these LIVE planners and no worker.
    Drives the REAL suspend_recipe so the manifest is written by a5's writer."""
    sessions = await _spawn(env, planners=planner_handles, workers=())
    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID, reason="restart")
    assert isinstance(res, ToolOk), res
    return sessions


async def test_a_live_planner_on_a_done_step_is_warned_not_silently_dropped(
        env, logspy):
    """THE d59 SHAPE, as observed live in a10: a planner still ACTIVE at suspend
    whose step is already `done`. R6 lore is exactly why this row must not vanish
    quietly — a live planner on a done step may still be finalizing.

    The manifest pins its forkable `claude_session_id`; resume drops it. That
    drop is now REPORTED (WARN + counter), not silent."""
    env.ctx.recipes.save(
        _recipe(steps=_steps((STEP_ID, "in_progress"),
                             (DIVERGED_STEP_ID, "done"))))
    sessions = await _park_planners(env, PLANNER_HANDLE, DIVERGED_HANDLE)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert res.data["planners_respawned"] == 1, "only the in_progress step"
    assert res.data["planners_orphaned"] == 1

    warned = _warnings(logspy, ORPHAN_WARN)
    assert len(warned) == 1, "the dropped row is named, exactly once"
    assert warned[0]["handle"] == DIVERGED_HANDLE
    assert warned[0]["step_status"] == "done"
    # the WARN carries the fork anchor being dropped — a human can still fork it
    assert warned[0]["claude_session_id"] == sessions[DIVERGED_HANDLE]


async def test_the_orphaned_row_is_reported_but_never_respawned(env, logspy):
    """The union REJECTION, pinned. Respawning the `done` step's planner would
    resurrect finished work; respawning a `pending` step's would double-dispatch
    against next_action. So the respawn set must NOT grow — and resume must not
    stamp the step `in_progress` to make a union safe."""
    env.ctx.recipes.save(
        _recipe(steps=_steps((STEP_ID, "in_progress"),
                             (DIVERGED_STEP_ID, "done"))))
    await _park_planners(env, PLANNER_HANDLE, DIVERGED_HANDLE)

    await env.call("resume_recipe", recipe_id=RECIPE_ID)

    spawned = {s["handle"] for s in _planner_spawns(env)}
    assert spawned == {PLANNER_HANDLE}, "the diverged step gets NO planner"
    after = {s.step_id: s.status for s in env.ctx.recipes.load(RECIPE_ID).steps}
    assert after[DIVERGED_STEP_ID] == "done", "resume does not mutate the FSM"


async def test_a_pending_step_with_a_live_planner_row_is_also_warned(env, logspy):
    """The other divergence arm: a planner spawned OUTSIDE the sanctioned path,
    so its step never got the dispatch-time `in_progress` stamp. Same treatment —
    reported, not respawned (next_action will dispatch it, cold)."""
    env.ctx.recipes.save(_recipe(steps=_steps((STEP_ID, "pending"))))
    await _park_planners(env, PLANNER_HANDLE)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert res.data["planners_orphaned"] == 1
    assert _warnings(logspy, ORPHAN_WARN)[0]["step_status"] == "pending"
    assert _planner_spawns(env) == [], "next_action owns a pending step"


async def test_a_zero_planner_resume_with_an_orphan_does_not_read_as_success(
        env, logspy):
    """THE ORIGINAL DEFECT'S EXACT SHAPE (a10, verbatim): planners_respawned == 0
    while a live planner row is dropped. The old note said "planners of in-flight
    steps are back (forked onto their old sessions…)" REGARDLESS. A note
    conditioned only on respawned/forked would STILL read reassuringly here —
    so `planners_orphaned` must be one of the counters the note derives from."""
    env.ctx.recipes.save(_recipe(steps=_steps((STEP_ID, "done"))))
    await _park_planners(env, PLANNER_HANDLE)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)
    note = res.data["note"]

    assert res.data["planners_respawned"] == 0
    assert res.data["planners_orphaned"] == 1
    assert _BACK not in note, "nothing came back; the note must not say it did"
    assert _NONE_BACK in note
    assert _NOT_RESPAWNED in note, "the dropped row is named in the note itself"


async def test_a_resume_with_nothing_to_put_back_says_exactly_that(env):
    """The plain zero case: no in-flight step, no live planner row. The note must
    still refuse to read as success — a green-looking string is what made B2
    invisible for a whole recipe."""
    env.ctx.recipes.save(_recipe(steps=_steps((STEP_ID, "done"))))
    r = env.ctx.recipes.load(RECIPE_ID)
    r.suspended_at = _now().isoformat()
    env.ctx.recipes.save(r)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)
    note = res.data["note"]

    assert (res.data["planners_respawned"], res.data["planners_orphaned"]) == (0, 0)
    assert _BACK not in note
    assert _NONE_BACK in note
    assert _NOT_RESPAWNED not in note, "no row was dropped — do not cry wolf"


async def test_a_terminal_snapshot_planner_row_is_not_warned_about(env, logspy):
    """The WARN is scoped to `state == active` ON PURPOSE. The manifest snapshot
    is the PRE-REAP registry read, so it also carries the terminal rows of
    planners that closed normally on earlier steps. Warning about those would
    fire once per completed step on EVERY resume — noise that trains the reader
    to ignore the signal."""
    env.ctx.recipes.save(_recipe(steps=_steps((STEP_ID, "done"))))
    await _spawn(env, planners=(PLANNER_HANDLE,), workers=())
    env.ctx.pool._dead.add(PLANNER_HANDLE)   # it closed cleanly, long ago
    await env.call("suspend_recipe", recipe_id=RECIPE_ID, reason="restart")

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert _warnings(logspy, ORPHAN_WARN) == [], "a closed planner is not a drop"
    assert res.data["planners_orphaned"] == 0


async def test_the_note_still_reports_a_real_fork_when_one_happened(env, recipe):
    """The other half of the conditional: making the note honest about failure
    must not make it silent about success. A resume that DID fork says so, with
    the count."""
    await _park(env)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)
    note = res.data["note"]

    assert res.data["planners_forked"] == 1
    assert _BACK in note
    assert "1 forked onto the sessions suspend snapshotted" in note
    assert _NONE_BACK not in note
    assert _NOT_RESPAWNED not in note


async def test_the_note_says_cold_when_a_respawn_had_no_session_to_fork(env,
                                                                        recipe):
    """The crash path put a planner back, but from nothing — the note must not
    imply session continuity that does not exist."""
    await _plan_with_open_action(env)
    await _spawn(env)
    await env.ctx.pool.reap(PLANNER_HANDLE)
    await env.ctx.pool.reap(WORKER_HANDLE)
    r = env.ctx.recipes.load(RECIPE_ID)
    r.suspended_at = _now().isoformat()
    env.ctx.recipes.save(r)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert (res.data["planners_respawned"], res.data["planners_forked"]) == (1, 0)
    assert "started fresh (cold)" in res.data["note"]


async def test_a_failed_spawn_is_named_in_the_note_not_papered_over(env, recipe,
                                                                    monkeypatch):
    """`planners_failed` is a counter the old note ignored entirely: a resume
    where every spawn failed still announced the planners were back."""
    await _park(env)

    async def refusing_spawn(*_a, **_kw):
        raise RuntimeError("pool at capacity")

    monkeypatch.setattr(env.ctx.pool, "spawn_planner", refusing_spawn)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)
    note = res.data["note"]

    assert res.data["planners_failed"] == 1
    assert _BACK not in note
    assert "1 planner spawn(s) FAILED" in note


async def test_in_flight_steps_docstring_no_longer_asserts_pending_never_had_one(
):
    """The docstring's "they never had one" was the BUG'S PREMISE, not a comment:
    it is the reason the diverging row could be dropped without anyone noticing.
    A false claim in the one place a reader goes to understand the selection must
    not survive the fix."""
    doc = _tools._in_flight_steps.__doc__ or ""

    assert "never had one" not in doc
    assert "in_progress" in doc and "next_action" in doc


# ════════════════════════════════════════════════════════════════════════
# (e) the un-park: suspended_at cleared + recipe_resumed emitted
# ════════════════════════════════════════════════════════════════════════
async def test_suspended_at_is_cleared_and_the_fsm_state_untouched(env, recipe):
    await _park(env)
    assert env.ctx.recipes.load(RECIPE_ID).suspended_at

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    after = env.ctx.recipes.load(RECIPE_ID)
    assert after.suspended_at is None
    assert after.state.value == "executing", "suspension is orthogonal to the FSM"
    assert res.data["resumed_at"]


async def test_recipe_resumed_event_is_emitted(env, recipe):
    await _park(env)

    res = await env.call("resume_recipe", recipe_id=RECIPE_ID)

    resumed = [e for e in _events(env) if e["kind"] == _tools.RESUME_EVENT_KIND]
    assert len(resumed) == 1
    body = resumed[0]["body"]
    assert body["resumed_at"] == res.data["resumed_at"]
    assert body["manifest_found"] is True
    assert body["planners_respawned"] == 1


# ════════════════════════════════════════════════════════════════════════
# (f) the suspended-dispatch precondition — BOTH spawn tools
# ════════════════════════════════════════════════════════════════════════
async def test_pool_spawn_worker_refuses_while_suspended(env, recipe):
    await _park(env)

    res = await env.call("pool_spawn_worker", plan_id=PLAN_ID,
                         action_id=ACTION_ID)

    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert _tools.SUSPENDED_DISPATCH_REFUSAL in res.message
    assert _worker_spawns(env) == []


async def test_pool_spawn_planner_refuses_while_suspended(env, recipe):
    await _park(env)

    res = await env.call("pool_spawn_planner", recipe_id=RECIPE_ID,
                         step_id=STEP_ID)

    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert _tools.SUSPENDED_DISPATCH_REFUSAL in res.message
    assert _planner_spawns(env) == []


async def test_both_spawn_tools_succeed_once_the_recipe_is_resumed(env, recipe):
    """The other half of the guard: the refusal is a PARK, not a wedge.

    Dispatch a FRESH action (`a2`): `a1`'s worker was reaped by the suspend, and
    re-spawning onto a just-reaped handle trips PoolSpawnWorker's own
    launched-but-died liveness check — a different guard, and not the one under
    test here."""
    await _park(env)
    await env.call("add_action", plan_id=PLAN_ID, action_id="a2",
                   description="the next one")
    await env.call("resume_recipe", recipe_id=RECIPE_ID)

    planner = await env.call("pool_spawn_planner", recipe_id=RECIPE_ID,
                             step_id="s2")
    worker = await env.call("pool_spawn_worker", plan_id=PLAN_ID,
                            action_id="a2")

    assert isinstance(planner, ToolOk), planner
    assert isinstance(worker, ToolOk), worker


async def test_a_refused_worker_spawn_rolls_back_the_in_progress_prestamp(env,
                                                                          recipe):
    """s16 part 3: this refusal fires BEFORE launch. A racing planner steered
    mid-tool-call during the suspend grace window would otherwise strand a
    phantom `in_progress` action with no live worker."""
    await _park(env)
    plan = env.ctx.plans.load(PLAN_ID)
    plan.actions[0].status = "in_progress"   # the FSM's dispatch pre-stamp
    env.ctx.plans.save(plan)

    res = await env.call("pool_spawn_worker", plan_id=PLAN_ID,
                         action_id=ACTION_ID)

    assert isinstance(res, ToolError)
    assert env.ctx.plans.load(PLAN_ID).actions[0].status == "pending"


async def test_the_port_stays_open_while_the_tool_is_refused(env, recipe):
    """REQUIREMENT A — the guard is a TOOL-surface guard ON PURPOSE. resume must
    re-spawn while `suspended_at` is STILL SET, so it goes through the PORT.
    Pinning only the tool refusal would let someone "fix" the check onto the
    port and deadlock resume against its own guard. Only the PAIR states the
    contract, so assert both in one place."""
    await _park(env)
    assert env.ctx.recipes.load(RECIPE_ID).suspended_at

    tool = await env.call("pool_spawn_planner", recipe_id=RECIPE_ID,
                          step_id=STEP_ID)
    port = await env.ctx.pool.spawn_planner(RECIPE_ID, STEP_ID)

    assert isinstance(tool, ToolError), "the TOOL refuses a parked recipe"
    assert isinstance(port, ToolOk), "the PORT does not — resume depends on it"


async def test_reconcile_does_not_crash_recover_a_parked_planner(env, recipe):
    """A parked recipe's planner is dead BY DESIGN. Reading that as a crash
    would burn the step's single auto-re-dispatch budget (so a LATER genuine
    crash goes straight to CHILD_CRASHED) and flip the step to `pending`,
    leaving resume with no in-flight step to fork."""
    await _park(env)
    before = env.ctx.recipes.load(RECIPE_ID)
    assert before.steps[0].status == "in_progress"

    res = await env.call("reconcile", handle=RECIPE_ID, handle_type="recipe")

    assert isinstance(res, ToolOk), res
    after = env.ctx.recipes.load(RECIPE_ID)
    assert after.steps[0].status == "in_progress", "a park is not a crash"
    assert after.steps[0].attempt == 0, "the re-dispatch budget is intact"
    assert after.state.value == "executing"


# ════════════════════════════════════════════════════════════════════════
# (g) the FSM surface — recipe_context carries the parked flag
# ════════════════════════════════════════════════════════════════════════
def test_recipe_context_omits_suspension_when_the_recipe_is_live():
    """Conditional-add, like comprehension_recheck/consult_pending: the
    steady-state per-tick push stays lean, and absence means "not parked"."""
    assert "suspension" not in recipe_context(_recipe())


def test_recipe_context_surfaces_suspension_on_the_first_tick():
    stamped = _now().isoformat()
    ctx = recipe_context(_recipe(suspended_at=stamped))

    assert ctx["suspension"]["suspended"] is True
    assert ctx["suspension"]["suspended_at"] == stamped
    assert "resume_recipe" in ctx["suspension"]["note"]


def test_recipe_context_carries_the_flag_not_the_manifest():
    """RP-B made this push deliberately lean. A boolean + a timestamp, never the
    manifest — that is a file a resume reads once, not per-tick context."""
    ctx = recipe_context(_recipe(suspended_at=_now().isoformat()))

    assert set(ctx["suspension"]) == {"suspended", "suspended_at", "note"}
    for absent in ("sessions", "open_actions", "open_steps", "manifest"):
        assert absent not in ctx["suspension"]


async def test_a_resumed_recipe_stops_advertising_suspension(env, recipe):
    await _park(env)
    assert "suspension" in recipe_context(env.ctx.recipes.load(RECIPE_ID))

    await env.call("resume_recipe", recipe_id=RECIPE_ID)

    assert "suspension" not in recipe_context(env.ctx.recipes.load(RECIPE_ID))


# ════════════════════════════════════════════════════════════════════════
# (h) the NEURON-ONLY pin — all six role sets ENUMERATED, no spot-check
# ════════════════════════════════════════════════════════════════════════
# roles.py derives _NEURON = _ALL_TOOL_NAMES - SPECIALIST_ONLY - _CONSOLIDATED_OUT
# while the other five surfaces are EXPLICIT allowlists. suspend/resume therefore
# land in the neuron set CORRECTLY, but only IMPLICITLY — nothing states it. A
# future verb added to an allowlist, or a future subtraction from _NEURON, would
# move them silently. So state it, over every surface.
SUSPENSION_VERBS = ("suspend_recipe", "resume_recipe")
# s25/a4 took six roles to nine (curiosity/goal_keeper/pattern_observer gained
# rows); the owner ruling of 2026-08-04 took nine to SEVEN — goal_keeper and
# pattern_observer are DEAD and deleted — and the 2026-08-12 dead-surface
# retirement of the consult shell role took seven to SIX. The pin's job is
# unchanged: the suspension verbs must stay neuron-only across EVERY surface
# that exists.
ALL_ROLES = ("worker", "planner", "reviewer", "specialist", "neuron",
             "curiosity")


def test_the_six_role_sets_are_exactly_the_ones_enumerated_here():
    """Guard the guard: if a further role appears, the pin below silently stops
    covering it."""
    from edp_claude.tools.roles import ROLE_TOOLSETS

    assert set(ROLE_TOOLSETS) == set(ALL_ROLES)


@pytest.mark.parametrize("verb", SUSPENSION_VERBS)
def test_suspension_verbs_are_registered_tools(verb):
    assert any(cls.name == verb for cls in _tools.ALL_TOOL_CLASSES)


@pytest.mark.parametrize("verb", SUSPENSION_VERBS)
@pytest.mark.parametrize("role", ALL_ROLES)
def test_suspension_verbs_are_in_the_neuron_surface_and_no_other(verb, role):
    """Parking and un-parking a recipe is the recipe OWNER's call: it reaps
    every other shell, including the planner that would be asking."""
    from edp_claude.tools.roles import ROLE_TOOLSETS

    present = verb in ROLE_TOOLSETS[role]
    assert present is (role == "neuron"), (
        f"{verb!r} is {'in' if present else 'absent from'} the {role!r} "
        f"surface; it must be neuron-only")
