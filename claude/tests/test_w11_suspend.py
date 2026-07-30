"""W11 a5 (DESIGN-v6 §W11) — `suspend_recipe`: park the planners, reap the rest.

Suspension is a COORDINATED shutdown, not a kill. The bar this module pins:

  * a `steer` park message reaches EVERY live planner (and NO worker);
  * a planner that overruns the bounded grace window is force-reaped — the
    straggler branch is EXERCISED, not merely present (s22/a6: a guard whose
    body never runs is not a guard);
  * a planner that closes within the window is NOT reaped;
  * workers are reaped outright, never steered, never marked failed — their
    `in_progress` actions are what `reconcile` trues up on resume;
  * `sessions(recipe_id=…)` is FORWARDED (asserted via
    `StubPool.last_sessions_filter`) and the returned rows are never re-filtered
    on RECIPE MEMBERSHIP. The pool's own filter is what finds a crash-orphaned
    worker whose stored `recipe_id` is None; a client-side membership predicate
    would silently strand exactly that orphan. LIVENESS is a different axis: a
    terminal (`state != "active"`) row names a shell the pool already closed and
    must not be reaped;
  * one failing reap must not abort the suspend — the park steers have already
    gone out, so a half-done suspend strands live shells;
  * `neuron_session_id` resolution order: a stamped `recipe.neuron_session_id`
    BEATS the foreground log's last entry; the log is used only as a fallback;
    the source is recorded either way, and the launcher is bound to the session
    id that was actually chosen (never borrowed from another shell's record
    without saying so);
  * the resume command renders as `claude-personal --resume <id>` from a
    captured personal `config_dir`, and is OMITTED WITH A REASON when no session
    id (or no launcher) resolves — never a bare `claude --resume`, which finds
    nothing because transcripts live under CLAUDE_CONFIG_DIR;
  * `suspended_at` + `neuron_session_id` are stamped through the normal store
    path and a `recipe_suspended` event is emitted.

SAFETY (assumption a5/RP-A + a3): every test builds its OWN recipe in `tmp_path`.
No real recipe is ever suspended — writing `suspended_at` into a live
recipe.json before the coordinated restart would wedge it against every still-
running pre-W11 `extra='forbid'` reader, and suspending THIS recipe would park
the planner that dispatched the work.

Env discipline (d7/d8): the autouse conftest fixture clears the leaked
EDP_ROLE/EDP_HANDLE; every assertion is pure Python (the acceptance verify shell
has no `env` binary — an `env -u VAR …` prefix exits 127).
"""

import json
from datetime import datetime, timezone

import pytest
from edp_contracts import Tool, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.tools import _tools

RECIPE_ID = "r-suspend"
STEP_ID = "s1"
PLAN_ID = f"{RECIPE_ID}-{STEP_ID}"
PLANNER_HANDLE = f"{RECIPE_ID}:{STEP_ID}"          # pool session handle (colon)
PLANNER_INBOX = f"{RECIPE_ID}-{STEP_ID}"           # broker inbox (dash plan_id)
WORKER_HANDLE = f"{PLAN_ID}:a1"
PERSONAL_CONFIG_DIR = r"C:\Users\me\.claude-personal"


def _now():
    return datetime.now(timezone.utc)


# ── a temp fixture recipe — NEVER a real one ─────────────────────────────────
def _steps(*specs: tuple[str, str]) -> list[dict]:
    """`(step_id, status)` pairs → step dicts, so a test can spell a step that is
    NOT `in_progress` (the divergence shape) without repeating the boilerplate."""
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
    """Collapse the bounded wait so the straggler branch runs without sleeping.

    Grace 0 → the loop reads the registry ONCE, finds the planner still active,
    and returns it as a straggler. The branch is exercised, not skipped."""
    monkeypatch.setattr(_tools, "SUSPEND_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(_tools, "SUSPEND_POLL_SECS", 0.0)


@pytest.fixture(autouse=True)
def _no_foreground_log(monkeypatch):
    """Default: an EMPTY registry. A test that wants records opts in via
    `foreground()`. Without this the reader would read the REAL repo log."""
    monkeypatch.setattr(_tools, "latest_foreground_session", lambda: None)
    monkeypatch.setattr(_tools, "foreground_session_by_id", lambda _sid: None)


@pytest.fixture
def foreground(monkeypatch):
    """Install a fake foreground registry (oldest → newest)."""
    def _install(records: list[dict]):
        monkeypatch.setattr(_tools, "latest_foreground_session",
                            lambda: records[-1] if records else None)

        def _by_id(session_id):
            for rec in reversed(records):
                if rec["session_id"] == session_id:
                    return rec
            return None

        monkeypatch.setattr(_tools, "foreground_session_by_id", _by_id)
    return _install


@pytest.fixture
def recipe(env):
    """A saved temp recipe + a plan carrying one in_progress action."""
    env.ctx.recipes.save(_recipe())
    return env.ctx.recipes.load(RECIPE_ID)


async def _plan_with_open_action(env):
    await env.call("create_plan", recipe_id=RECIPE_ID, step_id=STEP_ID,
                   shape="linear", goal="do the thing")
    await env.call("add_action", plan_id=PLAN_ID, action_id="a1",
                   description="build it")
    plan = env.ctx.plans.load(PLAN_ID)
    plan.actions[0].status = "in_progress"
    env.ctx.plans.save(plan)


async def _spawn(env, *, planners=(PLANNER_HANDLE,), workers=(WORKER_HANDLE,)):
    """Populate the stub pool's registry with live planner/worker rows."""
    for handle in planners:
        rid, step = handle.split(":", 1)
        await env.ctx.pool.spawn_planner(rid, step)
    for handle in workers:
        pid, action = handle.rsplit(":", 1)
        await env.ctx.pool.spawn_worker(pid, action)


def _steers(env) -> list:
    return [m for inbox in env.ctx.broker.inboxes.values()
            for m in inbox if m.kind == "steer"]


def _manifest(env) -> dict:
    path = env.ctx.recipes.root / RECIPE_ID / _tools.SUSPEND_MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8"))


def _events(env) -> list[dict]:
    path = env.ctx.recipes.root / RECIPE_ID / "events.jsonl"
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── (a) a park steer reaches every live planner — and no worker ──────────────
async def test_park_steer_sent_to_each_live_planner(env, recipe):
    second = f"{RECIPE_ID}:s2"
    await _spawn(env, planners=(PLANNER_HANDLE, second))

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID, reason="restart")

    assert isinstance(res, ToolOk)
    assert res.data["planners_steered"] == 2
    steers = _steers(env)
    assert len(steers) == 2
    # addressed to the planner's DASH plan_id inbox, not its colon handle
    assert {m.to for m in steers} == {PLANNER_INBOX, f"{RECIPE_ID}-s2"}
    body = steers[0].body
    assert body["action"] == "suspend"
    assert body["recipe_id"] == RECIPE_ID
    # the park asks for a clean close: persist, then close yourself
    assert "pool_close_self" in body["instruction"]


async def test_workers_are_reaped_not_steered(env, recipe):
    """Workers are disposable. Steering one would ask it to persist state that
    `reconcile` re-derives anyway — and it must NOT be marked failed."""
    await _spawn(env)

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert [m.to for m in _steers(env)] == [PLANNER_INBOX]
    assert WORKER_HANDLE not in env.ctx.broker.inboxes
    assert res.data["others_reaped"] == 1
    assert WORKER_HANDLE in env.ctx.pool._dead


async def test_worker_action_is_left_in_progress_not_failed(env, recipe):
    await _plan_with_open_action(env)
    await _spawn(env)

    await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    action = env.ctx.plans.load(PLAN_ID).actions[0]
    assert action.status == "in_progress", "reconcile trues this up on resume"


# ── (b) the straggler branch: a planner that overruns the grace is reaped ────
async def test_straggler_planner_is_reaped_after_grace(env, recipe):
    """The stub planner never closes itself, so it IS the straggler. Grace is 0,
    so this exercises the reap branch on the first registry re-read."""
    await _spawn(env, workers=())

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["planners_steered"] == 1
    assert res.data["planners_reaped"] == 1
    assert PLANNER_HANDLE in env.ctx.pool._dead


async def test_planner_that_closes_within_grace_is_not_reaped(env, recipe,
                                                              monkeypatch):
    """The happy path: the steered planner closed itself, so nothing is killed.
    Reaping a shell that already parked would be a pointless force-kill."""
    monkeypatch.setattr(_tools, "SUSPEND_GRACE_SECONDS", 5.0)
    await _spawn(env, workers=())

    reaped: list[str] = []
    pool = env.ctx.pool
    real_sessions, real_reap = pool.sessions, pool.reap

    async def closing_sessions(recipe_id=None):
        rows = await real_sessions(recipe_id=recipe_id)
        # the FIRST read (the tool's initial listing) sees it live; the grace
        # loop's re-read sees it closed, exactly as pool_close_self leaves it.
        if closing_sessions.calls:
            rows = [{**r, "state": "done"} for r in rows]
        closing_sessions.calls += 1
        return rows
    closing_sessions.calls = 0

    async def tracking_reap(handle):
        reaped.append(handle)
        return await real_reap(handle)

    monkeypatch.setattr(pool, "sessions", closing_sessions)
    monkeypatch.setattr(pool, "reap", tracking_reap)

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["planners_steered"] == 1
    assert res.data["planners_reaped"] == 0
    assert reaped == [], "a planner that parked cleanly must not be force-killed"


# ── (c) the registry filter is the SERVER's; liveness is ours ───────────────
async def test_suspend_forwards_recipe_id_to_sessions(env, recipe):
    """FORWARDING, not filtering: StubPool records the filter and returns rows
    unchanged. Which rows belong to a recipe is edp-pool's semantics (its
    `_row_matches_recipe` also matches a crash-orphaned worker whose stored
    recipe_id is None) and is asserted in edp-pool's own suite."""
    await _spawn(env)

    await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert env.ctx.pool.last_sessions_filter == RECIPE_ID


async def test_every_live_row_is_reaped_without_membership_refiltering(env,
                                                                       recipe):
    """A row the server returned whose handle does NOT look like it belongs to
    this recipe is STILL reaped — that is the crash-orphaned worker whose
    recipe_id was stored as None. A client-side membership predicate would drop
    it and leave it running against a suspended recipe."""
    await _spawn(env, workers=(WORKER_HANDLE,))
    await env.ctx.pool.spawn_worker("some-other-plan", "a9")  # orphan-shaped

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["others_reaped"] == 2
    assert env.ctx.pool._dead >= {WORKER_HANDLE, "some-other-plan:a9"}
    assert env.ctx.pool.spawns == [], "every live row was reaped"


async def test_terminal_rows_are_not_reaped(env, recipe, monkeypatch):
    """The listing includes rows already `done`. Reaping one asks the pool to
    kill a session it has forgotten — a guess about someone else's error
    semantics. Only `active` rows name a running shell."""
    await _spawn(env)
    reaped: list[str] = []

    async def rows_with_a_dead_worker(recipe_id=None):
        return [
            {"handle": PLANNER_HANDLE, "role": "planner", "state": "active",
             "session_id": "planner:1", "claude_session_id": "cs-planner"},
            {"handle": WORKER_HANDLE, "role": "worker", "state": "done",
             "session_id": "worker:1", "claude_session_id": None},
        ]

    async def tracking_reap(handle):
        reaped.append(handle)
        return Tool.ok(_tools.BaseModel())

    monkeypatch.setattr(env.ctx.pool, "sessions", rows_with_a_dead_worker)
    monkeypatch.setattr(env.ctx.pool, "reap", tracking_reap)

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert reaped == [PLANNER_HANDLE], "a terminal row must not be reaped"
    assert res.data["others_reaped"] == 0
    # …but the manifest still snapshots it: a resume reads the full registry
    assert {s["handle"] for s in _manifest(env)["sessions"]} == {
        PLANNER_HANDLE, WORKER_HANDLE}


async def test_one_failing_reap_does_not_abort_the_suspend(env, recipe,
                                                           monkeypatch):
    """The park steers have already gone out, so a suspend that aborts halfway
    strands the remaining live shells — strictly worse than one that reaps
    nothing. Every reap is individually non-fatal."""
    await _spawn(env, workers=("p:w1", "p:w2", "p:w3"))
    reaped: list[str] = []
    real_reap = env.ctx.pool.reap

    async def flaky_reap(handle):
        if handle == "p:w1":
            raise RuntimeError("pool refused")
        reaped.append(handle)
        return await real_reap(handle)

    monkeypatch.setattr(env.ctx.pool, "reap", flaky_reap)

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert isinstance(res, ToolOk), "the suspend completed despite the failure"
    assert set(reaped) == {PLANNER_HANDLE, "p:w2", "p:w3"}
    assert res.data["reap_failures"] == 1  # reported, never swallowed
    # and the recipe is still parked + manifested
    assert env.ctx.recipes.load(RECIPE_ID).suspended_at
    assert _manifest(env)["recipe_id"] == RECIPE_ID


# ── (d) the manifest ────────────────────────────────────────────────────────
MANIFEST_KEYS = {
    "recipe_id", "suspended_at", "reason", "grounding_epoch", "open_steps",
    "open_actions", "sessions", "pending_assumptions", "pending_spec_learnings",
    "neuron_session_id", "neuron_session_source", "launcher_source",
    "resume_command", "resume_command_omitted_reason",
}


async def test_manifest_written_with_all_required_keys(env, recipe, foreground):
    foreground([{"session_id": "neuron-1", "config_dir": PERSONAL_CONFIG_DIR}])
    await _plan_with_open_action(env)
    await _spawn(env)

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID, reason="restart")
    manifest = _manifest(env)

    assert set(manifest) == MANIFEST_KEYS
    assert manifest["recipe_id"] == RECIPE_ID
    assert manifest["reason"] == "restart"
    assert manifest["suspended_at"] == res.data["suspended_at"]
    assert manifest["grounding_epoch"]
    assert manifest["open_steps"] == [{"step_id": STEP_ID,
                                       "status": "in_progress"}]
    assert manifest["open_actions"] == [
        {"plan_id": PLAN_ID, "action_id": "a1", "status": "in_progress"}]
    assert manifest["pending_assumptions"] == 0
    assert manifest["pending_spec_learnings"] == {}
    # the session-registry snapshot carries handles + their claude session ids
    by_handle = {s["handle"]: s for s in manifest["sessions"]}
    assert set(by_handle) == {PLANNER_HANDLE, WORKER_HANDLE}
    assert by_handle[PLANNER_HANDLE]["claude_session_id"], "forkable planner"
    assert by_handle[WORKER_HANDLE]["claude_session_id"] is None  # disposable
    # the manifest is a FILE, so its lists are full-fidelity; the TOOL payload
    # stays O(1) in domain size (#18) — counts, never rows.
    assert res.data["planners_steered"] == 1 and res.data["others_reaped"] == 1
    assert "sessions" not in res.data and "open_actions" not in res.data


async def test_manifest_snapshots_sessions_before_they_are_reaped(env, recipe):
    """Read the registry BEFORE reaping — afterwards the shells a resume must
    re-launch are gone from the pool."""
    await _spawn(env)

    await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert env.ctx.pool.spawns == []                      # all reaped
    assert len(_manifest(env)["sessions"]) == 2           # still recorded


async def test_manifest_snapshots_a_live_planner_whose_step_is_not_in_flight(
        env):
    """The SNAPSHOT half of the suspend/resume divergence (d59, seen live in
    a10). suspend derives its planner set from the POOL REGISTRY — any LIVE
    planner — while resume derives its respawn set from the recipe's
    `in_progress` steps. Off the sanctioned dispatch path the two disagree.

    Suspend's half is CORRECT and must stay that way: a planner alive on a step
    the recipe already calls `done` is still a real shell holding a real,
    forkable claude session (R6 — a live planner on a done step may still be
    finalizing). It is steered, reaped, and — the part that matters here —
    RECORDED, with its `state` so a reader can tell a live row from a long-closed
    one. Resume is where the row is then dropped; `test_w11_resume.py` (d2) pins
    that the drop is WARN-logged rather than silent."""
    env.ctx.recipes.save(_recipe(steps=_steps((STEP_ID, "done"))))
    await _spawn(env, workers=())

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["planners_steered"] == 1, "liveness, not step status, selects"
    rows = [s for s in _manifest(env)["sessions"] if s["role"] == "planner"]
    assert len(rows) == 1, "the row a resume would otherwise drop in silence"
    assert rows[0]["handle"] == PLANNER_HANDLE
    assert rows[0]["state"] == "active", "snapshotted PRE-reap; the WARN scopes on this"
    assert rows[0]["claude_session_id"], "the fork anchor is preserved on disk"


# ── (e) neuron_session_id resolution order ─────────────────────────────────
async def test_stamped_neuron_session_beats_the_log_fallback(env, foreground):
    """The log's LAST entry is merely the newest foreground shell in this repo —
    any other shell the user opened lands there. A stamped id is the authority."""
    env.ctx.recipes.save(_recipe(neuron_session_id="stamped-1"))
    foreground([{"session_id": "some-other-shell",
                 "config_dir": PERSONAL_CONFIG_DIR}])

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["neuron_session_id"] == "stamped-1"
    assert res.data["neuron_session_source"] == "recipe.neuron_session_id"
    assert _manifest(env)["neuron_session_id"] == "stamped-1"


async def test_log_fallback_used_only_when_the_stamp_is_unset(env, recipe,
                                                              foreground):
    foreground([{"session_id": "old", "config_dir": PERSONAL_CONFIG_DIR},
                {"session_id": "newest", "config_dir": PERSONAL_CONFIG_DIR}])

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["neuron_session_id"] == "newest"
    assert res.data["neuron_session_source"] == "foreground_log"


async def test_launcher_is_matched_to_the_resolved_session(env, foreground):
    """A stamped id that IS in the registry takes THAT entry's config_dir —
    correct by construction, not the latest shell's launcher."""
    env.ctx.recipes.save(_recipe(neuron_session_id="stamped-1"))
    foreground([
        {"session_id": "stamped-1", "config_dir": PERSONAL_CONFIG_DIR},
        {"session_id": "later-shell", "config_dir": r"C:\Users\me\.claude-other"},
    ])

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["launcher_source"] == _tools._LAUNCHER_MATCHED
    assert res.data["resume_command"] == "claude-personal --resume stamped-1"


async def test_launcher_inferred_is_recorded_as_such(env, foreground):
    """A session stamped BEFORE the capture hook existed has no registry entry
    (the current neuron's case). Borrowing the latest launcher is allowed — but
    the manifest must say it was inferred, not matched."""
    env.ctx.recipes.save(_recipe(neuron_session_id="pre-hook"))
    foreground([{"session_id": "someone-else",
                 "config_dir": PERSONAL_CONFIG_DIR}])

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)
    manifest = _manifest(env)

    assert res.data["neuron_session_id"] == "pre-hook"
    assert manifest["launcher_source"] == _tools._LAUNCHER_INFERRED
    assert manifest["resume_command"] == "claude-personal --resume pre-hook"


# ── (f) the resume command: rendered, or omitted with a reason ──────────────
async def test_resume_command_rendered_for_a_personal_config_dir(env, recipe,
                                                                 foreground):
    foreground([{"session_id": "neuron-1", "config_dir": PERSONAL_CONFIG_DIR}])

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["resume_command"] == "claude-personal --resume neuron-1"
    assert res.data["resume_command_omitted_reason"] is None
    assert _manifest(env)["resume_command"] == \
        "claude-personal --resume neuron-1"


async def test_manifest_omits_the_command_and_says_why_without_a_session(env,
                                                                         recipe):
    """No stamp, no registry entry → no id. A guessed one resumes the wrong
    shell, so the command is OMITTED and the reason recorded."""
    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)
    manifest = _manifest(env)

    assert res.data["neuron_session_id"] is None
    assert res.data["neuron_session_source"] is None
    assert manifest["resume_command"] is None
    assert "no neuron session id resolved" in \
        manifest["resume_command_omitted_reason"]


async def test_manifest_omits_the_command_when_no_launcher_can_be_named(
        env, recipe, foreground):
    """A plain `claude` launch captured `config_dir: null`. A bare
    `claude --resume` finds nothing (transcripts live under CLAUDE_CONFIG_DIR),
    so say so rather than print a command that fails opaquely."""
    foreground([{"session_id": "neuron-1", "config_dir": None}])

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    assert res.data["neuron_session_id"] == "neuron-1"   # the id resolved fine
    assert res.data["resume_command"] is None
    assert "CLAUDE_CONFIG_DIR" in res.data["resume_command_omitted_reason"]


@pytest.mark.parametrize("config_dir,expected", [
    (r"C:\Users\me\.claude-personal", "claude-personal"),
    ("/home/me/.claude-personal", "claude-personal"),
    ("/home/me/.claude-personal/", "claude-personal"),
    ("/home/me/.claude-work", "claude-work"),
    (None, None),
    ("", None),
    (r"C:\Users\me\.claude", None),      # the bare `claude` launcher: forbidden
])
def test_launcher_is_derived_from_the_config_dir_never_hardcoded(config_dir,
                                                                 expected):
    assert _tools._launcher_for_config_dir(config_dir) == expected


def test_planner_inbox_is_the_dash_plan_id():
    """A planner's session handle is `<recipe>:<step>`; its broker inbox is the
    DASH plan_id. Recipe ids contain dashes but never a colon, so only the
    single separator is swapped."""
    assert _tools._planner_inbox("recipe-a-b-c:s23") == "recipe-a-b-c-s23"


# ── (g) the recipe is stamped + the event emitted ───────────────────────────
async def test_suspended_at_and_neuron_session_id_are_stamped(env, recipe,
                                                              foreground):
    foreground([{"session_id": "neuron-1", "config_dir": PERSONAL_CONFIG_DIR}])
    before = env.ctx.recipes.load(RECIPE_ID)
    assert before.suspended_at is None and before.neuron_session_id is None

    res = await env.call("suspend_recipe", recipe_id=RECIPE_ID)

    after = env.ctx.recipes.load(RECIPE_ID)
    assert after.suspended_at == res.data["suspended_at"]
    assert after.neuron_session_id == "neuron-1"
    # tz-aware UTC ISO, and the FSM state is untouched — suspension is orthogonal
    stamped = datetime.fromisoformat(after.suspended_at)
    assert stamped.tzinfo is not None
    assert after.state.value == "executing"


async def test_recipe_suspended_event_is_emitted(env, recipe, foreground):
    foreground([{"session_id": "neuron-1", "config_dir": PERSONAL_CONFIG_DIR}])

    await env.call("suspend_recipe", recipe_id=RECIPE_ID, reason="phase-3 restart")

    suspended = [e for e in _events(env)
                 if e["kind"] == _tools.SUSPEND_EVENT_KIND]
    assert len(suspended) == 1
    body = suspended[0]["body"]
    assert "phase-3 restart" in body["summary"]
    assert body["resume_command"] == "claude-personal --resume neuron-1"
    assert body["manifest"].endswith(_tools.SUSPEND_MANIFEST_NAME)


async def test_unknown_recipe_is_a_precondition_error(env):
    res = await env.call("suspend_recipe", recipe_id="no-such-recipe")
    assert not res.ok
    assert "no recipe" in res.message


# ── (h) neuron-only by DERIVATION: no explicit allowlist names it ───────────
def test_suspend_recipe_is_registered_and_neuron_only():
    from edp_claude.tools.roles import ROLE_TOOLSETS

    assert any(cls.name == "suspend_recipe" for cls in _tools.ALL_TOOL_CLASSES)
    for role, surface in ROLE_TOOLSETS.items():
        if role == "neuron":
            assert "suspend_recipe" in surface
        else:
            assert "suspend_recipe" not in surface, role
