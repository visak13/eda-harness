"""DESIGN-v6 W10b — model tiers + the stuck→consult escalation ladder.

The bar this pins:

* T1  NO row in MODEL_TIERS is status="measured". a4b owns any flip, and it
      owns it only once a real benchmark exists (d80: the design labelled a tier
      "measured" citing a MODEL-TIERING-BENCHMARK.md that did not exist).
* T2  a spawn WITHOUT allow_candidate_tier NEVER selects a candidate. ENUMERATED
      over the same table the resolver reads, plus the strict-superset property
      that makes the enumeration a LOAD and not a catalogue (d65).
* T3  a spawn WITH allow_candidate_tier=true launches the reviewer on
      claude-sonnet-5 — driven through the real branch_reviewer tool.
* T4  "haiku" appears NOWHERE in the tier table or its resolution path.
* T5  a tier row is `{model, status}` (+`benchmark_task`) and NOTHING else — the
      shape DESIGN-v6 line 490 specifies. The original T5 (every row declares
      `thinking` + `effort`) is WITHDRAWN: a4b measured that no production code
      reads either field, so the pin guaranteed a well-formed TABLE and was read
      as a guarantee about the SPAWNED SHELL. Both fields deleted, user ruling.
* T6  the escalation ladder. Two failed acceptance CYCLES emit ESCALATE_CONSULT
      with an auto-composed, non-empty, action-specific question — and ONE cycle
      reported through BOTH d30 seams counts ONCE and emits NOTHING.
* T6b the emission is LATCHED and ADVISORY: it fires once per signal crossing and
      the very next tick dispatches. An un-latched instruction would wedge the
      plan — the control mechanism d76 forbids.
* T7  NO cost_report tool is registered on the MCP surface (d77, user ruling).
* T8  the legacy fixture 0e7ca8 loads byte-identically with the new counter
      fields present (o6; lazy migration, no rewrite) — recipe AND its plans.
* T9  the residual W10a item is ALREADY LANDED. The brief (inheriting DESIGN-v6
      W10b) said the tool-level planner spawn "still doesn't accept/pass model".
      It does. Pinned rather than re-plumbed, so the claim cannot rot again.

Env discipline (d7): EDP_ROLE/EDP_HANDLE/EDP_TIER_WRITE leaking from the
launching worker shell are neutralised in-process by the autouse conftest
fixture. Every assertion is done in PYTHON — the verify shell has no `grep`
(d8/R11: PowerShell host, no POSIX tools).
"""

import copy
import inspect
import json
from pathlib import Path

from edp_contracts import ToolOk

from edp_claude.fsm.plan_fsm import (
    STUCK_VERIFY_FAILURES_THRESHOLD,
    bump_verify_failure,
    compose_consult_question,
    plan_next_action,
)
from edp_claude.schemas import InstructionKind, Plan, PlanState, Recipe
from edp_claude.tools import roles as roles_mod
from edp_claude.tools.roles import (
    DEFAULT_TASK_CLASS,
    HOST_DEFAULT_MODEL,
    MODEL_TIERS,
    SONNET,
    resolve_model_tier,
    spawn_model_for,
)

K = InstructionKind

_ROOT = Path(__file__).resolve().parents[1]
_RECIPES = _ROOT / ".recipes"
_PLANS = _ROOT / ".plans"
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# ── T1 ─────────────────────────────────────────────────────────────────────
def test_t1_no_row_is_measured_opus_is_the_default():
    """NO row may claim `measured` — Opus is the default, Sonnet is opt-in only.

    a4b DID run BENCH-WORKER-CODING (5 trials/arm, 2026-07-10) and once flipped
    ('worker','coding') to `measured`. But it measured `claude-sonnet-5`, and the
    tiered Sonnet is now `claude-sonnet-4-6` (USER RULING, 2026-07-16: "keep Opus
    as default and use Sonnet where it makes sense"). A measurement of one model
    is not a measurement of another (d80), so the row reverted to `candidate` and
    NO row is measured. This is the doc's own §8 ground-rule-1 honest negative,
    not an omission — MODEL-TIERING-BENCHMARK.md must say the flip is withheld."""
    measured = {k for k, v in MODEL_TIERS.items() if v["status"] == "measured"}
    assert measured == set(), (
        f"measured rows are {sorted(measured)}; Opus is the default and Sonnet "
        f"is opt-in only (USER RULING, 2026-07-16). a4b measured claude-sonnet-5, "
        f"but the Sonnet tier now resolves to claude-sonnet-4-6 — a different "
        f"model, so its measurement does not transfer (d80).")
    assert {v["status"] for v in MODEL_TIERS.values()} == {"default", "candidate"}

    # the safety net is NOT degraded: reviewer stays Opus, both classes
    for tc in (DEFAULT_TASK_CLASS, "spec"):
        assert MODEL_TIERS[("reviewer", tc)]["model"] == HOST_DEFAULT_MODEL, (
            "the reviewer's independent re-run IS the acceptance gate (d29/d30); "
            "degrade the safety net last")


def test_t1b_benchmark_doc_backs_every_measured_and_candidate_row():
    """The design's own gate: a tier needs a MODEL-TIERING-BENCHMARK.md entry.

    a4 wrote the honest stub ("no benchmark has been run"); a4b replaced it with
    a real entry. The doc must (a) name every candidate's benchmark task, (b) name
    every measured row's task, and (c) NOT launder the design's unverified
    `-40% / quality-delta ~0` into a measured result — a4b measured 24.8%."""
    doc = (_ROOT / "docs" / "design" / "MODEL-TIERING-BENCHMARK.md").read_text(
        encoding="utf-8")

    # the stub's claim is GONE — a benchmark has now run
    assert "NO BENCHMARK HAS BEEN RUN" not in doc

    # every candidate AND every measured row names its benchmark task in the doc
    for (role, tc), tier in MODEL_TIERS.items():
        if tier["status"] in ("candidate", "measured"):
            assert tier["benchmark_task"].split(":")[0] in doc, (
                f"{tier['status']} ({role},{tc}) names benchmark task "
                f"{tier['benchmark_task']!r} which the doc does not carry")

    # the unverified price ratio is never presented as the measured cost delta
    assert "24.8%" in doc, "the doc must carry the MEASURED cost saving"
    assert "unverified price ratio" in doc, (
        "the doc must still mark the design's -40% as unverified, not adopt it")


# ── T2 ─────────────────────────────────────────────────────────────────────
def test_t2_no_candidate_tier_is_ever_selected_without_the_flag():
    """NEVER, and the enumeration below is what proves the word.

    This docstring asserts a UNIVERSAL ("never"), which d75 says must be PINNED
    BY A TEST or deleted. It is pinned HERE, by enumerating `MODEL_TIERS.keys()`
    ITSELF — the exact same mapping `resolve_model_tier` reads — rather than a
    hand-maintained list of pairs that could silently fall behind it.

    d65 (A CATALOGUE ENTRY IS NOT A LOAD): enumerating the table the resolver
    reads is only a load if adding a row cannot widen the exclusion. So the
    STRICT-SUPERSET property is asserted explicitly below: every role appearing
    anywhere in the table must own a DEFAULT_TASK_CLASS row, or the fallback has
    nowhere to land and a new row would resolve to None — silently passing no
    model, which looks identical to "resolved to the host default" and is not."""
    assert MODEL_TIERS, "empty table would make this test vacuous"

    roles_in_table = {role for role, _ in MODEL_TIERS}
    # STRICT-SUPERSET: the fallback target must exist for every role present.
    missing = [r for r in roles_in_table
               if (r, DEFAULT_TASK_CLASS) not in MODEL_TIERS]
    assert not missing, (
        f"roles {missing} have tier rows but NO ({DEFAULT_TASK_CLASS!r}) "
        "default row to fall back to; a candidate row for them would resolve "
        "to None and silently bypass this guard")

    # ENUMERATED over the same table the resolver reads — not a spot check.
    #
    # a4b flipped ("worker","coding") to status="measured". A MEASURED row is
    # ADOPTED: it resolves WITHOUT the flag, by design — that is what "measured"
    # means and what the benchmark bought. The universal this test pins is
    # therefore about CANDIDATE rows, which is what its name says. Each status
    # gets its own explicit expectation, so a row silently changing status can
    # never slip through by matching a weaker branch.
    for (role, task_class), tier in MODEL_TIERS.items():
        got = resolve_model_tier(role, task_class)          # NO flag
        assert got is not None, (role, task_class)

        if tier["status"] == "measured":
            # ADOPTED: selected with no opt-in, and it DOES pass --model.
            assert got["status"] == "measured", (role, task_class)
            assert got["model"] == tier["model"] != HOST_DEFAULT_MODEL
            assert spawn_model_for(role, task_class) == tier["model"], (
                f"({role},{task_class}) is measured but passes no --model")
            # a measured row must be backed by a benchmark entry (T2 in
            # test_w10b_benchmark.py enforces the doc side of this)
            assert tier["benchmark_task"], (
                f"measured ({role},{task_class}) names no benchmark task")
            continue

        assert got["status"] == "default", (
            f"({role},{task_class}) resolved to a {got['status']} tier "
            "without allow_candidate_tier")
        assert got["model"] == HOST_DEFAULT_MODEL, (
            f"({role},{task_class}) resolved to {got['model']!r}; every "
            f"un-opted-in spawn must resolve to {HOST_DEFAULT_MODEL!r}")
        # and the wire stays byte-identical: no --model flag at all
        assert spawn_model_for(role, task_class) is None, (
            f"({role},{task_class}) would pass a --model flag on a default "
            "spawn, changing the pool body for an untiered role")

        # the candidate is reachable ONLY behind the flag
        if tier["status"] == "candidate":
            opted = resolve_model_tier(role, task_class,
                                       allow_candidate_tier=True)
            assert opted["status"] == "candidate"
            assert opted["model"] == SONNET
            assert spawn_model_for(role, task_class,
                                   allow_candidate_tier=True) == SONNET

    # an unknown task_class degrades to the SAFE tier, never to None
    assert spawn_model_for("worker", "no-such-class") is None
    assert resolve_model_tier("worker", "no-such-class")["model"] == \
        HOST_DEFAULT_MODEL
    # an unknown ROLE fails open to "no model flag" (host default)
    assert spawn_model_for("no-such-role") is None


def test_t2b_the_candidate_branch_runs_and_measured_is_dormant_by_design():
    """d66 — a guard that passes because the condition is absent guards nothing.

    T2's DEFAULT and CANDIDATE branches iterate real rows: every role has an Opus
    default, and ('worker','coding'/'narrow'/'verify') are live candidates, so
    neither universal is proved over an empty set. T2's `measured` branch is dead
    code — DELIBERATELY (USER RULING, 2026-07-16: Opus is the default, Sonnet is
    opt-in only). It is kept as a FORWARD guard: if a real 4.6 benchmark ever
    re-earns a measured row, that branch is already correct. This test asserts the
    dormancy is intentional, not an accident — no measured row exists to run it.

    RE-POINTED (d128/d132): ("reviewer", "direction") WAS the only reviewer
    candidate row; the direction reviewer is removed, so it went with it. The
    reviewer's absence from the candidate set is itself the assertion — it states
    the "degrade the safety net LAST" posture (d29/d30) as a property."""
    cands = [k for k, v in MODEL_TIERS.items() if v["status"] == "candidate"]
    assert cands, "no candidate rows: T2's candidate assertions never run"
    assert ("worker", "narrow") in cands
    assert ("worker", "coding") in cands   # demoted from measured 2026-07-16

    measured = [k for k, v in MODEL_TIERS.items() if v["status"] == "measured"]
    assert not measured, (
        f"a row is 'measured' ({sorted(measured)}) — but Opus is the default and "
        "Sonnet is opt-in only (USER RULING, 2026-07-16). a4b measured "
        "claude-sonnet-5; the tier now resolves to claude-sonnet-4-6, so no "
        "measurement backs a live row.")

    # NO reviewer class is a tiering candidate: the reviewer's independent re-run
    # IS the acceptance gate, so every reviewer spawn resolves to the Opus default.
    assert not [role for role, _tc in cands if role == "reviewer"]
    assert ("reviewer", "direction") not in MODEL_TIERS


# ── T3 ─────────────────────────────────────────────────────────────────────
async def _stable_specialist(env):
    """A stable specialist with a compiled doc — branch_reviewer's precondition."""
    c = _ok(await env.call("create_specialization", name="Java Expert",
                           subject="Java", description="java spring boot"))
    nid, sid = c["neuron_id"], c["spec_id"]
    _ok(await env.call("neuron_set_base_session", neuron_id=nid,
                       session_id="base-1"))
    _ok(await env.call("write_specialist_doc", spec_id=sid,
                       content="# Java\n- tests pass. [required]\n"))
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="pending_review"))
    _ok(await env.call("neuron_set_status", neuron_id=nid, status="stable"))
    return nid


async def _recipe_with_plan(env, goal="make the CSV totals line up"):
    rid = _ok(await env.call("start_recipe", goal=goal,
                             domain="framework"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="linear", goal="build it"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="do generic narrow work"))
    return rid, sid, pid


async def test_t3_candidate_flag_launches_the_spawn_on_sonnet(env):
    """Driven through a REAL spawn tool and read off the pool's recorded spawn —
    not off the resolver, which T2 already covers.

    RE-POINTED (d128/d132): this drove `branch_reviewer(scope="direction",
    allow_candidate_tier=True)`, the only reviewer candidate row. That row and
    that mode are gone. The PROPERTY under test is unchanged and still live —
    the opt-in flag really reaches the pool and selects the candidate model —
    so it is now driven through `pool_spawn_worker` on ("worker", "narrow"), the
    surviving candidate row."""
    _rid, _sid, pid = await _recipe_with_plan(env)

    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1",
                       task_class="narrow", allow_candidate_tier=True))
    spawned = [s for s in env.ctx.pool.spawns if s["role"] == "worker"]
    assert len(spawned) == 1
    assert spawned[0]["model"] == SONNET, (
        f"candidate spawn launched on {spawned[0]['model']!r}, expected "
        f"{SONNET!r} with allow_candidate_tier=True")


def test_t3b_default_reviewer_spawn_stays_opus_host_default():
    """The reviewer resolves NO model → host default (Opus). The safety net
    degrades last (d29/d30: the reviewer's re-run IS the gate).

    RE-POINTED TWICE: first (d128/d132) onto the SPEC reviewer, then again
    when `branch_reviewer` was deleted outright (owner ruling 2026-08-04) —
    the property survives the verb, so it is pinned at the resolver every
    reviewer spawn reads (`spawn_model_for`)."""
    from edp_claude.tools.roles import spawn_model_for

    assert spawn_model_for("reviewer", "spec") is None, (
        "the spec reviewer resolved a --model; it must carry none — it is "
        "the acceptance gate, not a candidate")
    # ...and even asking for the candidate tier cannot degrade it: no reviewer
    # candidate row exists to select.
    assert spawn_model_for(
        "reviewer", "spec", allow_candidate_tier=True) is None


async def test_t3c_default_worker_spawn_stays_opus_host_default(env):
    """And the worker dispatch path is byte-identical to pre-W10b."""
    _rid, _sid, pid = await _recipe_with_plan(env)
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1"))
    spawned = [s for s in env.ctx.pool.spawns if s["role"] == "worker"]
    assert len(spawned) == 1
    assert spawned[0]["model"] is None


# ── T4 ─────────────────────────────────────────────────────────────────────
def test_t4_haiku_appears_nowhere_in_the_tier_table_or_its_resolution_path():
    """d53: NEVER haiku — in any table, comment, or test. Asserted on SOURCE,
    case-insensitively, over the tier table and the two functions that resolve
    it. (Haiku 4.5 also rejects `effort` outright and carries a 200K window
    against our 1M, so d53 is right for a stronger reason than d53 states.)"""
    # the DATA
    blob = json.dumps(
        {f"{r}|{t}": v for (r, t), v in MODEL_TIERS.items()}).lower()
    assert "haiku" not in blob

    # the RESOLUTION PATH, read as source
    for fn in (roles_mod.resolve_model_tier, roles_mod.spawn_model_for):
        assert "haiku" not in inspect.getsource(fn).lower(), fn.__name__

    # and the whole module that owns the table, comments included
    src = Path(inspect.getfile(roles_mod)).read_text(encoding="utf-8").lower()
    # the ONLY sanctioned occurrences are the prohibitions themselves
    for line in src.splitlines():
        if "haiku" in line:
            assert ("never" in line or "not a tier" in line
                    or "forbids" in line or "excludes" in line
                    or "rejects" in line), (
                f"unsanctioned mention of haiku in roles.py: {line.strip()!r}")


# ── T5 (WITHDRAWN, replaced) ───────────────────────────────────────────────
def test_t5_a_tier_row_is_model_and_status_and_nothing_else():
    """T5 AS WRITTEN IS WITHDRAWN — its SUBJECT is withdrawn, not its reasoning.

    The old T5 pinned that every row set `thinking` and `effort` explicitly, to
    keep a4b's benchmark arms comparable. a4b ran, and found the pin guaranteed
    nothing it claimed: NO production code reads either field. `spawn_model_for`
    returns a model string and `pty_launcher.build_argv` emits only
    `["--model", model]`, so a row could declare `thinking="disabled"` while the
    spawned shell thought freely. The table was well-formed; the shell was
    unaffected. A pin on a field nothing consumes asserts a property of the
    TABLE and reads as a property of the SYSTEM.

    Both fields were DELETED (user ruling, 2026-07-10). DESIGN-v6 line 490
    specifies the row shape as `(role, task_class) -> {model, status}`. This test
    now pins THAT — the shape the design actually specifies — so the deleted
    fields cannot creep back in as inert declarations.

    Where do model/thinking/effort belong? The Claude Code settings+env surface
    the harness already owns. Not a new field here (d76/d77)."""
    allowed = {"model", "status", "benchmark_task"}
    for key, tier in MODEL_TIERS.items():
        assert set(tier) <= allowed, (
            f"tier {key} carries unexpected keys {sorted(set(tier) - allowed)}. "
            f"A row is {{model, status}} (+benchmark_task on a candidate). "
            f"`thinking`/`effort` were deleted because nothing consumed them; "
            f"do not re-add an inert field — wire the env surface instead.")
        assert "model" in tier and "status" in tier, f"tier {key} is malformed"
        assert "thinking" not in tier and "effort" not in tier, (
            f"tier {key} re-declares `thinking`/`effort`. NOTHING READS THEM "
            f"(pty_launcher.build_argv emits only --model). Re-adding them "
            f"recreates the declared-and-dropped field a4b deleted.")
        if tier["status"] == "candidate":
            assert tier["benchmark_task"], f"candidate {key} names no benchmark"


# ── T6 — the escalation ladder ─────────────────────────────────────────────
def _plan(**over) -> Plan:
    base = dict(
        plan_id="p-w10b", recipe_id="r-w10b", recipe_step_id="s1",
        domain="framework", shape="linear", goal="make the totals line up",
        state="dispatching",
        actions=[dict(
            action_id="a1", description="reconcile the CSV totals",
            status="in_progress", executor_mode="subagent",
            acceptance=dict(kind="tests_pass",
                            expected="totals match the invoice PDF",
                            actual=None),
        )],
    )
    base.update(over)
    return Plan.model_validate(base)


def _fail_cycle_via_worker(p, aid="a1"):
    """Seam (a): the worker ran the gate in its own shell and it failed."""
    a = next(x for x in p.actions if x.action_id == aid)
    return bump_verify_failure(a)


def _fail_cycle_via_reviewer(p, aid="a1"):
    """Seam (b): the reviewer independently re-ran the gate and it failed."""
    a = next(x for x in p.actions if x.action_id == aid)
    return bump_verify_failure(a)


def _redispatch(p, aid="a1"):
    """Open a fresh acceptance cycle, exactly as the FSM does at dispatch."""
    a = next(x for x in p.actions if x.action_id == aid)
    a.status = "pending"
    instr = plan_next_action(p)          # stamps in_progress, clears the latch
    assert instr.kind == K.DISPATCH_ACTION
    return instr


def test_t6a_one_failed_cycle_through_BOTH_seams_counts_once_and_is_silent():
    """The dual gate is the HEALTHY path, not a stuck one.

    A single failed acceptance cycle is REPORTED twice by design: the worker runs
    the gate and records `failed`, then the reviewer independently re-runs it
    (d30) and records a failing verdict. Naive per-report bumping would double-
    count, firing ESCALATE_CONSULT after ONE failed cycle — convening an Opus
    consult every time a worker fails once and a reviewer agrees.

    Mutation for this assertion: delete the `verify_failure_counted` guard in
    `bump_verify_failure` (the idempotence key) and this goes RED on the count."""
    p = _plan()
    assert _fail_cycle_via_worker(p) is True      # first report counts
    assert _fail_cycle_via_reviewer(p) is False   # same cycle → no-op

    a = p.actions[0]
    assert a.verify_failures == 1, (
        f"one failed cycle reported through both d30 seams counted "
        f"{a.verify_failures} times")
    assert plan_next_action(_plan(actions=[a.model_dump()])) is not None
    # and NOTHING escalates below the threshold
    p2 = _plan()
    _fail_cycle_via_worker(p2)
    _fail_cycle_via_reviewer(p2)
    instr = plan_next_action(p2)
    assert instr.kind != K.ESCALATE_CONSULT, (
        "ESCALATE_CONSULT fired after ONE failed acceptance cycle; the "
        f"threshold is {STUCK_VERIFY_FAILURES_THRESHOLD} DISTINCT cycles")


# ── T6i — the two seams above are the SAME HELPER; these are the real tools ──
#
# t6a proves `bump_verify_failure` is idempotent. It cannot prove that the two
# d30 seams both CALL it: `_fail_cycle_via_worker` and `_fail_cycle_via_reviewer`
# are the same one-line helper. A seam that forgot the call would leave t6a green
# and the escalation ladder mis-counting in production. Drive the actual tools.

async def _one_action_plan(env, action_id="a1"):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id=action_id,
                       description="do generic work"))
    return rid, pid


#: a verdict must clear the substance bar; rubber-stamping is refused.
_VERDICT = ("Re-ran the acceptance command in a fresh shell: 12 passed, "
            "0 failed. The mutation reddens test_x at the named site.")


def _action(env, pid, aid="a1"):
    return next(x for x in env.ctx.plans.load(pid).actions if x.action_id == aid)


def _post_grounding_echo(env, pid, aid="a1"):
    """v7 P3.1: a worker's terminal record is refused without the grounding
    echo — post the worklog line notify_above(kind='grounding') leaves."""
    env.ctx.plans.append_worklog(pid, {
        "kind": "message_sent", "agent_role": "worker",
        "to": pid, "msg_kind": "grounding",
        "from_handle": f"{pid}:{aid}",
        "summary": "{'restatement': 'do generic work'}",
    })


async def test_t6i_worker_seam_alone_counts_one_cycle(env, monkeypatch):
    """SEAM (a), in isolation: `record_action_status(status="failed")`."""
    _, pid = await _one_action_plan(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", "sess-1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _post_grounding_echo(env, pid)
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="failed", evidence="ran the gate: 1 failed"))
    assert _action(env, pid).verify_failures == 1, (
        "seam (a) record_action_status(failed) does not count a failed cycle")


async def test_t6i_reviewer_seam_alone_counts_one_cycle(env, monkeypatch):
    """SEAM (b), in isolation. THE NON-VACUITY GUARD for the combined test
    below: were `record_branch_verdict` to never call `bump_verify_failure`,
    the combined worker-then-reviewer test would STILL observe 1 — inherited
    from seam (a) — and pass while pinning nothing about seam (b)."""
    rid, pid = await _one_action_plan(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")   # NOT the action's own shell
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    _ok(await env.call("record_branch_verdict", recipe_id=rid, plan_id=pid,
                       branch_id="a1", verdict=_VERDICT, passed=False))
    assert _action(env, pid).verify_failures == 1, (
        "seam (b) record_branch_verdict(passed=False) does not count a cycle")


async def test_t6i_a_passing_reviewer_verdict_counts_nothing(env, monkeypatch):
    """`passed=True` is the gate HOLDING. Counting it would escalate on success.
    `passed=None` (every pre-W10b caller) says nothing and counts nothing."""
    rid, pid = await _one_action_plan(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    _ok(await env.call("record_branch_verdict", recipe_id=rid, plan_id=pid,
                       branch_id="a1", verdict=_VERDICT, passed=True))
    assert _action(env, pid).verify_failures == 0


async def test_t6i_one_cycle_through_BOTH_REAL_seams_counts_once(env, monkeypatch):
    """THE CLAIM, through the tools that actually carry it. The worker runs the
    gate in its own shell and reports `failed` (d30 seam a); the reviewer
    independently re-runs it and records a failing verdict (seam b). That is the
    dual gate WORKING — one failed cycle — and it must count ONCE.

    Mutation: delete the `verify_failure_counted` guard in `bump_verify_failure`
    → this observes 2, i.e. the ladder fires at half its stated threshold."""
    rid, pid = await _one_action_plan(env)

    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", "sess-1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _post_grounding_echo(env, pid)
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="failed", evidence="ran the gate: 1 failed"))

    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    _ok(await env.call("record_branch_verdict", recipe_id=rid, plan_id=pid,
                       branch_id="a1", verdict=_VERDICT, passed=False))

    a = _action(env, pid)
    assert a.verify_failures == 1, (
        f"one failed cycle reported through both REAL d30 seams counted "
        f"{a.verify_failures} times")
    assert a.verify_failure_counted is True   # the latch persisted


def test_t6b_two_distinct_failed_cycles_emit_escalate_consult():
    """Two DISTINCT cycles — each separated by a re-dispatch, which is the
    idempotence key — do emit, with an auto-composed action-specific question."""
    p = _plan()
    _fail_cycle_via_worker(p)                  # cycle 1
    _redispatch(p)                             # dispatch opens cycle 2
    _fail_cycle_via_worker(p)                  # cycle 2
    assert p.actions[0].verify_failures == STUCK_VERIFY_FAILURES_THRESHOLD

    instr = plan_next_action(p)
    assert instr.kind == K.ESCALATE_CONSULT, instr.kind

    q = instr.args["question"]
    assert q.strip(), "the auto-composed question is empty"
    # ACTION-SPECIFIC by construction, not a template
    assert "a1" in q and "p-w10b" in q
    assert "reconcile the CSV totals" in q          # the action's description
    assert "totals match the invoice PDF" in q      # the acceptance EXPECTED
    assert "failed acceptance cycles" in q          # the signal that fired
    assert instr.args["action_id"] == "a1"
    assert instr.args["recipe_id"] == "r-w10b"
    # consult -> opus, from the ONE table. Never auto-stronger.
    assert instr.args["model"] == HOST_DEFAULT_MODEL


def test_t6c_redispatch_churn_alone_escalates():
    """The design's FIRST signal, independent of the acceptance counter:
    `attempt` (crash re-dispatch). Distinct counters, distinct meanings."""
    p = _plan()
    p.actions[0].attempt = 2
    instr = plan_next_action(p)
    assert instr.kind == K.ESCALATE_CONSULT
    assert "re-dispatch churn" in instr.args["question"]


def test_t6d_parked_worker_escalates_and_is_a_caller_computed_input():
    """The THIRD signal enters the PURE FSM as an input, exactly as
    `live_action_ids` does (s27/C7). The FSM holds no clock and reads no
    broker."""
    p = _plan()
    instr = plan_next_action(p, frozenset(), frozenset({"a1"}))
    assert instr.kind == K.ESCALATE_CONSULT
    assert "parked on an unanswered question" in instr.args["question"]

    # without the input, the same plan does NOT escalate (the input is load-
    # bearing, not decorative)
    assert plan_next_action(_plan()).kind != K.ESCALATE_CONSULT


def test_t6e_escalation_is_LATCHED_and_the_next_tick_dispatches():
    """d76 — the FSM ADVISES. An un-latched escalation would re-emit every tick
    and never hand back a dispatch, which is a control mechanism the FSM is
    forbidden from being. Latched, it costs exactly one tick.

    Mutation for this assertion: drop the `p.escalation_emitted` write in
    `plan_escalation_instruction` and the second tick escalates again → RED."""
    p = _plan()
    p.actions[0].attempt = 2
    p.actions[0].status = "pending"

    first = plan_next_action(p)
    assert first.kind == K.ESCALATE_CONSULT
    assert p.escalation_emitted == {"a1": [2, 0, False]}

    second = plan_next_action(p)              # same signal state → latched
    assert second.kind == K.DISPATCH_ACTION, (
        f"escalation re-emitted on the next tick ({second.kind}); it would "
        "wedge the plan and never dispatch")

    # a signal ADVANCE re-arms it (another crash), and only that
    p.actions[0].status = "pending"
    p.actions[0].attempt = 3
    assert plan_next_action(p).kind == K.ESCALATE_CONSULT


def test_t6f_escalation_is_advice_and_convenes_nothing():
    """The instruction DESCRIBES an escalation. It does not make one: the FSM
    is pure (no IO, no pool, no broker).

    2026-07-25: the escalation used to name `convene_consult`, and this test
    asserted that name. The operator retired that verb (roles.py
    `_OPERATOR_RETIRED`), so the rationale now points at `ask_above` instead —
    because d14 forbids instructing a role to call a tool it cannot see, which
    is exactly what leaving the old wording would have done. The ADVISORY
    property this test exists to guard is unchanged and still asserted."""
    p = _plan()
    p.actions[0].attempt = 2
    instr = plan_next_action(p)
    assert instr.kind == K.ESCALATE_CONSULT
    # the escalation must name a verb that some role actually holds
    assert "ask_above" in instr.rationale
    assert "convene_consult(" not in instr.rationale
    assert "ADVICE" in instr.rationale
    src = inspect.getsource(
        __import__("edp_claude.fsm.plan_fsm", fromlist=["x"]))
    for forbidden in ("ctx.pool", "ctx.broker", "await ", "requests.",
                      "open("):
        assert forbidden not in src, (
            f"plan_fsm performs IO ({forbidden!r}); the FSM must stay pure")


def test_t6g_a_done_action_never_escalates():
    """A finished action is not stuck, however it got there."""
    p = _plan()
    p.actions[0].attempt = 5
    p.actions[0].verify_failures = 5
    p.actions[0].status = "done"
    p.actions[0].acceptance.actual = "evidence"
    assert plan_next_action(p).kind != K.ESCALATE_CONSULT


def test_t6h_composed_question_is_never_empty_even_with_nothing_recorded():
    """No template branch can yield an empty or generic question."""
    p = _plan()
    a = p.actions[0]
    a.acceptance.expected = ""
    a.acceptance.actual = None
    q = compose_consult_question(p, a, ["some signal"], worklog_tail=None)
    assert q.strip()
    assert "a1" in q and "EXPECTED" in q and "ACTUAL" in q
    assert "(none recorded)" in q and "(nothing recorded)" in q


async def test_t6i_both_seams_bump_through_the_real_tools(env):
    """The two seams are REAL tool paths, not just the helper. Drives
    record_action_status(status='failed') and record_branch_verdict(passed=False)
    through the registry and reads the counter off disk."""
    _rid, _sid, pid = await _recipe_with_plan(env)

    # seam (a): the worker ran its own acceptance gate and it failed
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="failed", evidence="pytest exited 1"))
    assert env.ctx.plans.load(pid).actions[0].verify_failures == 1

    # seam (b): the reviewer independently re-ran it and states it failed.
    # SAME cycle (no dispatch between) → idempotent no-op.
    _ok(await env.call(
        "record_branch_verdict", recipe_id=_rid, plan_id=pid, branch_id="a1",
        passed=False,
        verdict="I re-ran pytest in a fresh shell; the totals assertion still "
                "fails at test_totals.py:41. The deliverable does not meet the "
                "acceptance criteria."))
    a = env.ctx.plans.load(pid).actions[0]
    assert a.verify_failures == 1, (
        f"one cycle reported through both seams counted {a.verify_failures}x")
    assert a.review_verdict["passed"] is False

    # a PASSING verdict never counts a failure
    p = env.ctx.plans.load(pid)
    p.actions[0].verify_failure_counted = False   # simulate a fresh cycle
    env.ctx.plans.save(p)
    _ok(await env.call(
        "record_branch_verdict", recipe_id=_rid, plan_id=pid, branch_id="a1",
        passed=True,
        verdict="I re-ran pytest in a fresh shell and it exits 0; the totals "
                "now match the invoice PDF. The acceptance criteria are met."))
    assert env.ctx.plans.load(pid).actions[0].verify_failures == 1


async def test_t6j_the_parked_signal_is_actually_FED_in_production(env):
    """d68/C9 — A GREEN GATE IS NOT EVIDENCE THE WIRING EXISTS.

    T6d proves the FSM honours `parked_action_ids`. It proves NOTHING about
    whether anything ever computes that set in the live `next_action` path: a
    perfectly-wired pure function whose caller always passes `frozenset()` is
    dead code with a passing test. So this drives the REAL tool and asserts the
    escalation comes out of it, with the wait clock in the state a genuinely
    parked child would leave it in.

    Mutation: make `_parked_action_ids` return `frozenset()` unconditionally and
    this goes RED while T6d stays green — which is exactly the blind spot."""
    from edp_claude.tools import _tools as T

    _rid, _sid, pid = await _recipe_with_plan(env)
    p = env.ctx.plans.load(pid)
    p.state = PlanState.DISPATCHING     # the enum, not the raw string
    p.actions[0].status = "in_progress"
    env.ctx.plans.save(p)

    # the state two elapsed patience windows leave behind on this handle
    st = T._WaitState(sig=("x",), since=0.0)
    st.escalations = T._PARKED_ESCALATIONS
    T._WAIT_STATE[pid] = st
    try:
        out = _ok(await env.call("next_action", handle=pid,
                                 handle_type="plan"))
    finally:
        T._WAIT_STATE.pop(pid, None)

    assert out["kind"] == K.ESCALATE_CONSULT.value, (
        f"next_action returned {out['kind']!r}; the parked signal is not fed "
        "in the live path")
    assert "parked on an unanswered question" in out["args"]["question"]
    assert out["args"]["model"] == HOST_DEFAULT_MODEL

    # and the latch PERSISTED, so the next tick does not re-emit
    assert env.ctx.plans.load(pid).escalation_emitted == {"a1": [0, 0, True]}


# ── T7 ─────────────────────────────────────────────────────────────────────
def test_t7_no_cost_report_tool_is_registered(env):
    """d77 (USER RULING, verbatim): "cost report is not shell count. I dont want
    you to build a dumb harness and hardcode the requirements... This discipline
    should exist within its role."

    W10b keeps model tiering + the escalation ladder; cost_report is DROPPED from
    the build. This asserts the ABSENCE — the prose belongs in the orchestrator
    guide and rides Phase 5, not in a tool that computes a number the model then
    obeys (d76: the framework advises, the model decides)."""
    names = set(env.tools)
    assert "cost_report" not in names
    offenders = sorted(n for n in names if "cost" in n.lower())
    assert offenders == [], f"cost-shaped tools registered: {offenders}"

    # and nothing in the source builds a Phoenix query client for it
    src = (_ROOT / "src" / "edp_claude" / "tools" / "_tools.py").read_text(
        encoding="utf-8")
    assert "class CostReport" not in src


# ── T8 — the o6 standing bar ───────────────────────────────────────────────
def test_t8_legacy_fixture_loads_byte_identically_with_the_new_counters():
    """o6: the new counter fields default-populate on legacy records WITHOUT
    rewriting them. Migration stays LAZY. Asserted on the RECIPE and — because
    the counters live on `Action` — on the legacy PLANS, which is where they
    would actually leak.

    Mutation for this assertion (d64: a clean corpus cannot prove its own guard):
    RE-INTRODUCE the offending form by removing the emission gate for
    `verify_failures`/`verify_failure_counted` in `Action._ser_legacy_shape`, and
    every legacy plan gains two unrequested keys → RED."""
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )
    import os
    os.environ.pop("EDP_TIER_WRITE", None)

    rdir = _RECIPES / LEGACY_RID
    assert (rdir / "recipe.json").exists(), "legacy fixture 0e7ca8 missing"
    original = (rdir / "recipe.json").read_text(encoding="utf-8")
    raw = json.loads(original)
    model = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        payload = dehydrate_recipe_payload(model.model_dump(mode="json"),
                                           Path(td))
    assert json.dumps(payload, indent=2) == original, \
        "legacy 0e7ca8 recipe round-trip is NOT byte-identical after W10b"

    # THE PLANS ARE WHERE THE NEW FIELDS LIVE — `Action` carries the counters, so
    # a leaked key would surface in legacy PLAN json, not in recipe.json.
    #
    # WHAT IS ASSERTED, AND WHY IT IS NOT FULL BYTE-IDENTITY. Exactly one legacy
    # action (…-s16, RP-6c-B2) re-serializes with `actual_ref` and `verify`
    # TRANSPOSED inside its `acceptance` — it was written by an older schema whose
    # field order differed. That drift PREDATES W10b and is untouched by it (the
    # W10b keys appear nowhere in the diff). Asserting raw byte-identity here
    # would be asserting a property this repo has never had, and "fixing" the
    # order would rewrite a legacy record — the exact thing o6's lazy-migration
    # bar forbids. So this asserts CONTENT identity (order-insensitive), which is
    # the property the emission gate actually owns, plus an explicit no-new-keys
    # check. The order drift is recorded as a finding, not masked.
    plan_files = sorted(_PLANS.glob(f"{LEGACY_RID}-s*.json"))
    assert plan_files, "no legacy 0e7ca8 plan JSON to guard"
    for pf in plan_files:
        text = pf.read_text(encoding="utf-8").rstrip("\n")
        orig = json.loads(text)
        p = Plan.model_validate(orig)
        # the fields EXIST on the model (default-populated, lazily, no rewrite)…
        for a in p.actions:
            assert a.verify_failures == 0
            assert a.verify_failure_counted is False
        assert p.escalation_emitted is None
        # …and are ABSENT from the re-serialized bytes
        out = p.model_dump(mode="json")
        for a in out["actions"]:
            assert "verify_failures" not in a, pf.name
            assert "verify_failure_counted" not in a, pf.name
        assert "escalation_emitted" not in out, pf.name
        assert (json.dumps(out, indent=2, sort_keys=True)
                == json.dumps(orig, indent=2, sort_keys=True)), (
            f"legacy plan {pf.name} does not round-trip content-identically "
            "after W10b")
    assert len(plan_files) >= 1


def test_t8b_the_counters_DO_serialize_once_they_carry_a_value():
    """The emission gate must omit at the DEFAULT, not always — otherwise the
    counter would never persist and the ladder would reset every reload."""
    p = _plan()
    p.actions[0].verify_failures = 2
    p.actions[0].verify_failure_counted = True
    p.escalation_emitted = {"a1": [0, 2, False]}
    out = p.model_dump(mode="json")
    assert out["actions"][0]["verify_failures"] == 2
    assert out["actions"][0]["verify_failure_counted"] is True
    assert out["escalation_emitted"] == {"a1": [0, 2, False]}
    # and it survives a round trip
    assert Plan.model_validate(out).actions[0].verify_failures == 2


# ── T9 — the residual W10a item was already landed ─────────────────────────
async def test_t9_planner_spawn_already_accepts_and_passes_model(env):
    """AN HONEST NEGATIVE, PINNED.

    This action's brief said: "RESIDUAL W10a: the TOOL-level planner-spawn entry
    point in _tools.py still does not accept/pass `model`. Thread it." It does.
    The brief inherited that from DESIGN-v6 W10b, which named a stale line number
    (_tools.py:1934) for a passthrough the code comment at `_SpawnPlannerIn`
    already describes as landed.

    Nothing was re-plumbed. The claim is pinned here instead, so it cannot rot
    back into a to-do — and so a reader who finds the design's sentence knows the
    code, not the sentence, is authoritative."""
    rid, sid, _pid = await _recipe_with_plan(env)

    # accepts it, and passes it through to the pool verbatim
    _ok(await env.call("pool_spawn_planner", recipe_id=rid, step_id=sid,
                       model=SONNET))
    planners = [s for s in env.ctx.pool.spawns if s["role"] == "planner"]
    assert planners[-1]["model"] == SONNET

    # and omitting it still means "host default" (no flag), unchanged
    _ok(await env.call("pool_spawn_planner", recipe_id=rid, step_id=sid))
    planners = [s for s in env.ctx.pool.spawns if s["role"] == "planner"]
    assert planners[-1]["model"] is None
