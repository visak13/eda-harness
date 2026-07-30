"""W9 part 2 — RE-POINTED (d128 user correction; d129 Part A item 1; d132).

This file used to pin `scope="direction"` — a second MODE on `branch_reviewer`
in which the NEURON spawned a reviewer to read deliverable files against the
verbatim goal. **That mode is removed.** The reviewer is the PLANNER's subagent
and is never available to the neuron; a mode only the neuron could call was a
subagent the neuron does not own. Its every caller was neuron-facing (the FSM
checkpoint and the pool spawn nag, both removed with it), so the path went
whole.

TWO THINGS SURVIVE, and this file is now their pin:

1. THE PLANNER'S REVIEWER (`scope="spec"`) IS UNTOUCHED. It is the objective
   acceptance gate (d29/d30) — the guard this removal must not weaken. T2/T3
   exercise it end-to-end and pin its brief against a literal.

2. THE CONSTRAINT PROPOSAL -> CONFIRMATION -> TEETH CHAIN IS UNTOUCHED.
   `confirm_direction_constraints` is NOT part of the direction-review surface
   despite its name: it is the ONLY proposed->active path for a
   constraint-bearing rejected_option FROM ANY CALLER. Deleting it by name-match
   would have disabled constraint activation wholesale — removing a live guard
   while claiming to remove a dead feature. (Its NAME is a defect: it implies a
   scope it does not have. Reported as a finding; renaming it is not this
   action's business.)

Tests REMOVED (subject genuinely no longer exists — d66: never delete a test to
turn red green; state the reason):
  * T1  — the direction brief carries the verbatim goal + harvested paths. There
    is no direction brief.
  * T1b — the harvest states its own bounds (`harvest_artifact_paths`). The
    method is deleted: it was the direction brief's only caller, and its
    `Path().glob(pattern)` is RELATIVE-ONLY, which is the HARVEST BUG (d127/d124)
    — an absolute Windows acceptance path raised "Non-relative patterns are
    unsupported", so the direction reviewer could not run on this host at all.
    Deleting the only caller retires the bug.
  * T1c — the harvest and the checkpoint counter share one reachability
    predicate. Both halves are gone; there is nothing left to keep in agreement.
  * test_non_off_track_verdict_does_not_surface — `record_direction_verdict` has
    no producer once the direction reviewer is gone, and is removed with it.
  Their replacement pins (the surface is GONE and stays gone) live in
  test_w9_direction_checkpoint.py, alongside the rest of the regression suite.

Env discipline (d7/d8): the autouse conftest fixture clears the leaking
EDP_ROLE/EDP_HANDLE/EDP_TIER_WRITE. Every assertion is done in PYTHON — the
verify shell has no `grep` (R11).
"""

import json
from pathlib import Path

from edp_contracts import ToolError, ToolOk

from edp_claude.guards import check_constraints
from edp_claude.tools.roles import MODEL_TIERS, ROLE_TOOLSETS

_SRC = Path(__file__).resolve().parents[1] / "src" / "edp_claude"
_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"

_GOAL = "make the CSV totals line up with the invoice PDF, nothing else"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _stable_specialist(env, *, with_doc=True):
    c = _ok(await env.call("create_specialization", name="Java Expert",
                           subject="Java", description="java spring boot"))
    nid, sid = c["neuron_id"], c["spec_id"]
    _ok(await env.call("neuron_set_base_session", neuron_id=nid,
                       session_id="base-1"))
    if with_doc:
        _ok(await env.call("write_specialist_doc", spec_id=sid,
                           content="# Java\n- tests pass. [required]\n"))
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="pending_review"))
    _ok(await env.call("neuron_set_status", neuron_id=nid, status="stable"))
    return nid


async def _recipe_with_plan(env, *, goal=_GOAL, action_ids=("a1",)):
    rid = _ok(await env.call("start_recipe", goal=goal,
                             domain="framework"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="linear", goal="build it"))["plan_id"]
    for aid in action_ids:
        _ok(await env.call("add_action", plan_id=pid, action_id=aid,
                           description="do generic narrow work"))
    return rid, sid, pid


# ══════════════════════════════════════════════════════════════════════════
# T2 — THE GUARD THIS CHANGE MUST NOT WEAKEN: the planner's spec reviewer
#      still spawns, and its brief is byte-identical to the pre-removal one.
# ══════════════════════════════════════════════════════════════════════════
async def test_t2_spec_reviewer_still_spawns_with_a_byte_identical_brief(env):
    """EXERCISED, not asserted. The spec review IS the acceptance gate (d29/d30);
    if this removal touched it, the framework loses its objective check."""
    nid = await _stable_specialist(env)
    spec_id = env.ctx.neurons.get(nid).spec_id

    async def _brief(**extra):
        out = _ok(await env.call(
            "branch_reviewer", neuron_id=nid,
            target="/path/TimeController.java",
            criteria="GET /time returns 200 + ISO-8601 JSON",
            concerns=["security"], handle="recipe-x", **extra))
        msgs = await env.ctx.broker.poll(out["reviewer_id"])
        return out, msgs[0].body

    out_omitted, body_omitted = await _brief()
    out_explicit, body_explicit = await _brief(scope="spec")

    assert body_omitted == body_explicit, "scope='spec' must equal the default"
    # PINNED against a literal: a new key in the spec brief fails here.
    assert body_omitted == {
        "task": "domain-review",
        "target": "/path/TimeController.java",
        "criteria": "GET /time returns 200 + ISO-8601 JSON",
        "neuron_id": nid,
        "spec_id": spec_id,
        "concerns": ["security"],
        "caller": "recipe-x",
    }
    # the RESULT shape is unchanged by the removal (the two direction-only
    # fields were emission-gated, so a spec result never carried them anyway)
    assert set(out_omitted) == {"reviewer_id", "fork_session_id", "note"}
    assert out_omitted["reviewer_id"].startswith(f"review-{nid}-")

    # a REAL reviewer shell was spawned, in the reviewer role
    sp = [s for s in env.ctx.pool.spawns
          if s["handle"] == out_omitted["reviewer_id"]]
    assert len(sp) == 1 and sp[0]["role"] == "reviewer"


# ══════════════════════════════════════════════════════════════════════════
# T3 — the input contract: spec's preconditions intact, direction REFUSED
# ══════════════════════════════════════════════════════════════════════════
async def test_t3_spec_preconditions_intact_and_direction_is_refused(env):
    rid, sid, pid = await _recipe_with_plan(env)
    c = _ok(await env.call("create_specialization", name="X", subject="x",
                           description="x"))

    # (a) spec: neuron_id absent → refused (unchanged)
    r1 = await env.call("branch_reviewer", target="/t.java", handle=rid)
    assert isinstance(r1, ToolError) and "neuron_id" in r1.message

    # (b) spec: an unstable neuron → refused (unchanged)
    r2 = await env.call("branch_reviewer", neuron_id=c["neuron_id"],
                        target="/t.java", handle=rid)
    assert isinstance(r2, ToolError) and "stable" in r2.message

    # (c) spec: a stable neuron with no target → refused (unchanged)
    nid = await _stable_specialist(env)
    r3 = await env.call("branch_reviewer", neuron_id=nid, handle=rid)
    assert isinstance(r3, ToolError) and "target" in r3.message

    # (d) THE REMOVAL: scope="direction" is REFUSED, loudly. The Literal is
    #     held at one value on purpose — a stale caller must fail validation,
    #     not be silently ignored (pydantic's default) and quietly run a SPEC
    #     review it never asked for.
    r4 = await env.call("branch_reviewer", scope="direction", handle=rid)
    assert isinstance(r4, ToolError), (
        "branch_reviewer(scope='direction') was accepted — the direction "
        "reviewer is back")

    # ...and it is refused even when it would otherwise look well-formed
    r5 = await env.call("branch_reviewer", scope="direction", handle=rid,
                        neuron_id=nid, target="/t.java")
    assert isinstance(r5, ToolError)


def test_t3b_the_direction_path_and_its_verdict_verb_are_gone_from_source():
    """Symbols, not just call sites — nothing survives to be re-wired."""
    import edp_claude.tools._tools as tools

    assert hasattr(tools, "BranchReviewer")          # the spec reviewer lives
    assert not hasattr(tools, "RecordDirectionVerdict")
    assert not hasattr(tools, "_DIRECTION_RUBRIC")
    assert not hasattr(tools.BranchReviewer, "_run_direction")

    # the verb is off every role surface, and out of the registry
    for role, verbs in ROLE_TOOLSETS.items():
        assert "record_direction_verdict" not in verbs, role

    # and no reviewer model-tier row references the dead task class
    assert ("reviewer", "direction") not in MODEL_TIERS
    assert ("reviewer", "spec") in MODEL_TIERS        # the survivor


# ══════════════════════════════════════════════════════════════════════════
# T4 — NO NEW ROLE (o7), and none removed either
# ══════════════════════════════════════════════════════════════════════════
def test_t4_no_new_role_exists_in_role_toolsets():
    """o7 pins the role SET. The removal must not add or drop a role either."""
    assert set(ROLE_TOOLSETS) == {
        "worker", "planner", "reviewer", "specialist", "consult", "neuron",
        "curiosity", "goal_keeper", "pattern_observer",
    }
    assert "direction_reviewer" not in ROLE_TOOLSETS
    assert not any("direction" in role for role in ROLE_TOOLSETS)
    assert (_CMD / "reviewer.md").exists()
    assert not (_CMD / "direction-reviewer.md").exists()


# ══════════════════════════════════════════════════════════════════════════
# T5 — THE OTHER SURVIVOR: a constraint-shaped finding is PROPOSED, has no
#      teeth, and bites only once the NEURON confirms it.
#      (This chain is why confirm_direction_constraints was NOT deleted.)
# ══════════════════════════════════════════════════════════════════════════
async def test_t5_a_proposed_constraint_has_no_teeth_until_the_neuron_confirms(
        env):
    rid, sid, pid = await _recipe_with_plan(env, action_ids=("a1", "a2"))

    prop = _ok(await env.call(
        "record_context", kind="rejected_option", recipe_id=rid,
        text="hand-rolled HTML generation in the totals pipeline",
        reason="the goal asks for reconciliation, not a report renderer",
        by="reviewer",
        constraint={"match": "HTML_HEADER", "match_kind": "substring",
                    "applies_to": ["action_result"],
                    "message": "no hand-rolled HTML in the totals pipeline"}))
    assert prop["status"] == "proposed", "a reviewer must not activate a ban"

    r = env.ctx.recipes.load(rid)
    ro = r.context.rejected_options[0]
    assert ro.status == "proposed" and ro.constraint is not None
    # PROPOSED HAS NO TEETH: the guard ignores it...
    assert check_constraints(r, "action_result", "I added HTML_HEADER") == []
    # ...and a matching completion lands, unblocked.
    ok = await env.call("record_action_status", plan_id=pid, action_id="a2",
                        status="done", evidence="I added HTML_HEADER again")
    assert isinstance(ok, ToolOk), ok

    # ── the NEURON confirms, in one batch. Only now do the W2 guards bite.
    p = env.ctx.plans.load(pid)
    p.actions[1].status = "pending"
    env.ctx.plans.save(p)
    conf = _ok(await env.call("confirm_direction_constraints", recipe_id=rid,
                              ids=[ro.id], action="activate"))
    assert conf["activated"] == [ro.id] and conf["unknown"] == []

    r = env.ctx.recipes.load(rid)
    assert r.context.rejected_options[0].status == "active"
    assert len(check_constraints(r, "action_result", "I added HTML_HEADER")) == 1

    refused = await env.call("record_action_status", plan_id=pid,
                             action_id="a2", status="done",
                             evidence="I added HTML_HEADER again")
    assert isinstance(refused, ToolError) and refused.code == "tool_precondition"
    assert ro.id in refused.message
    assert "hand-rolled HTML" in refused.message
    # fail-closed: nothing recorded
    assert env.ctx.plans.load(pid).actions[1].status != "done"


async def test_t5b_discard_drops_a_proposal_and_it_can_never_bite(env):
    rid, sid, pid = await _recipe_with_plan(env)
    prop = _ok(await env.call(
        "record_context", kind="rejected_option", recipe_id=rid, text="t",
        reason="r", constraint={"match": "HTML_HEADER",
                                "match_kind": "substring",
                                "applies_to": ["action_result"],
                                "message": "m"}))
    out = _ok(await env.call("confirm_direction_constraints", recipe_id=rid,
                             ids=[prop["id"]], action="discard"))
    assert out["discarded"] == [prop["id"]]
    r = env.ctx.recipes.load(rid)
    ro = r.context.rejected_options[0]
    assert ro.constraint is None                # the teeth are gone
    assert ro.text == "t"                       # the honest record remains
    assert check_constraints(r, "action_result", "HTML_HEADER") == []
    # a discarded proposal cannot be re-activated by this verb
    again = _ok(await env.call("confirm_direction_constraints", recipe_id=rid,
                               ids=[prop["id"]], action="activate"))
    assert again["not_proposed"] == [prop["id"]] and again["activated"] == []


async def test_t5c_every_caller_of_the_ban_write_path_lands_proposed(env):
    """"Regardless of caller" is a UNIVERSAL (d66/d75): enumerate and pin it,
    or do not write the word. The caller set is derived FROM SOURCE, so a
    third caller added later fails here rather than hiding behind the
    docstring.

    THIS is why `confirm_direction_constraints` survived the removal: the
    proposals it dispositions come from ANY caller, not from a direction
    reviewer. Delete it and no constraint can ever gain teeth."""
    src = (_SRC / "tools" / "_tools.py").read_text(encoding="utf-8")
    call_sites = src.count("RecordRejectedOption(self.ctx)")
    assert call_sites == 1, (
        "a new in-process caller of RecordRejectedOption appeared; add it to "
        "the enumeration in its docstring and drive it below")

    rid, sid, pid = await _recipe_with_plan(env)
    c = {"match": "nomic", "match_kind": "substring",
         "applies_to": ["action_result"], "message": "m"}

    # caller 1: the routed verb (the only one on any role surface)
    routed = _ok(await env.call("record_context", kind="rejected_option",
                                recipe_id=rid, text="t1", reason="r",
                                constraint=c))
    # caller 2: the legacy verb directly (registered, off every role surface)
    direct = _ok(await env.call("record_context", kind="rejected_option", recipe_id=rid,
                                text="t2", reason="r", constraint=c))
    assert routed["status"] == "proposed"
    assert direct["status"] == "proposed"

    # and a ban with NO constraint keeps its pre-W9 "active" shape
    plain = _ok(await env.call("record_context", kind="rejected_option",
                               recipe_id=rid, text="t3", reason="r"))
    assert plain["status"] == "active"
    r = env.ctx.recipes.load(rid)
    assert [x.status for x in r.context.rejected_options] == [
        "proposed", "proposed", "active"]
    # the legacy one is emission-gated out of the serialized shape
    raw = json.loads(json.dumps(r.model_dump(mode="json")))
    assert "status" not in raw["context"]["rejected_options"][2]
    assert raw["context"]["rejected_options"][0]["status"] == "proposed"


def test_t5d_only_the_neuron_can_reach_the_activation_verb():
    """The reviewer proposes; the NEURON disposes. Asserted against the real
    toolset in both directions, not stated in a comment.

    `record_context` SURVIVES on the reviewer's floor on its own merits (a
    reviewer proposes constraint-shaped findings, and every such write lands
    "proposed" — see T5c). `record_direction_verdict` does NOT: its producer
    went with the direction reviewer."""
    assert "record_context" in ROLE_TOOLSETS["reviewer"]
    assert "record_direction_verdict" not in ROLE_TOOLSETS["reviewer"]
    assert "confirm_direction_constraints" not in ROLE_TOOLSETS["reviewer"]
    assert "confirm_direction_constraints" in ROLE_TOOLSETS["neuron"]
    # no non-neuron role may activate a ban
    for role, tools in ROLE_TOOLSETS.items():
        if role != "neuron":
            assert "confirm_direction_constraints" not in tools, role


async def test_t5e_constraint_on_a_non_ban_kind_is_refused_not_dropped(env):
    """The defect this action found: `record_context` accepted `constraint`
    and stored nothing (no `m.constraint` read existed anywhere in src), so a
    caller believed W2's teeth had landed. A silent drop is the disease; a
    refusal is the cure."""
    rid, sid, pid = await _recipe_with_plan(env)
    res = await env.call("record_context", kind="decision", recipe_id=rid,
                         text="use MiniLM", rationale="settled",
                         constraint={"match": "nomic",
                                     "match_kind": "substring",
                                     "applies_to": ["action_result"],
                                     "message": "m"})
    assert isinstance(res, ToolError) and "dropped silently" in res.message
    assert env.ctx.recipes.load(rid).context.decisions == []


async def test_t5f_an_uncompilable_regex_ban_is_refused_at_write_time(env):
    """guards._hit treats an un-compilable stored pattern as a NO-HIT, so a bad
    regex lands a ban that can never fire — a constraint that lies about
    guarding. Refuse it where it is written."""
    rid, sid, pid = await _recipe_with_plan(env)
    res = await env.call("record_context", kind="rejected_option",
                         recipe_id=rid, text="t", reason="r",
                         constraint={"match": "[unclosed(", "match_kind":
                                     "regex", "applies_to": ["action_result"],
                                     "message": "m"})
    assert isinstance(res, ToolError) and "compilable regex" in res.message
    assert env.ctx.recipes.load(rid).context.rejected_options == []


# ══════════════════════════════════════════════════════════════════════════
# Docs: reviewer.md no longer carries a direction mode, and still mandates
#       the inline fix
# ══════════════════════════════════════════════════════════════════════════
def test_reviewer_md_has_no_direction_mode_and_keeps_the_inline_fix():
    b = (_CMD / "reviewer.md").read_text(encoding="utf-8")
    low = b.lower()

    # the direction MODE is gone (the callee half of the removed path)
    assert 'scope="direction"' not in b
    assert "scope='direction'" not in b
    assert "record_direction_verdict" not in b
    assert "direction-review" not in low or "no direction-review mode" in low
    assert "## Step 3.5" not in b

    # the SPEC review, and d76's inline-fix mandate, are untouched
    assert "compiled doc" in low and "specialist" in low
    assert "fix" in low and "same session" in low


def test_philosophy_phases_5_and_6_are_marked_superseded():
    p = (Path(__file__).resolve().parents[1] / "docs" / "design" /
         "philosophy" / "team-architecture-restoration.md")
    text = p.read_text(encoding="utf-8")
    assert text.count("superseded_by: DESIGN-v6 W9") >= 2, (
        "Phase 5 (blocking pre-sign-off critic) and Phase 6 (FSM-gated "
        "goal-keeper/pattern-observer) must BOTH be stamped")
