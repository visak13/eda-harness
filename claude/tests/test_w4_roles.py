"""DESIGN-v6 W4 — per-role tool surfaces, the build_mcp scoping seam, the
consolidated record_context verb, and lineage-scoped facts.

This module proves the W4 acceptance end-to-end over the REAL data tables
(tools/roles.py) and the REAL registration seam (mcp_server.build_mcp),
without a live spawn or network. It is FAST (pure in-process, tmp .memory).

ENV DISCIPLINE (documented false-signal): a WORKER shell runs with
EDP_ROLE=worker + EDP_HANDLE set, and pytest subprocesses INHERIT them.
build_mcp reads EDP_ROLE, and the fact-scope resolver reads EDP_ROLE +
lineage, so any test that leaves the ambient env in place would false-fail
(e.g. build_mcp would filter to the worker's 21 tools, breaking the
full-set assertion). EVERY env/role/lineage-sensitive test below therefore
controls the env EXPLICITLY via monkeypatch — never relying on inherited
state. The suite-wide autouse fixture in conftest.py clears it too. It must
be cleared IN-INTERPRETER: an `env -u EDP_ROLE …` prefix on the gate command
exits 127 on this host, which the acceptance gate reads as FAILED (d7/d8).
"""

import json
import string
from pathlib import Path

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Plan
from edp_claude.server import make_context
from edp_claude.stubs.file_memory import FileMemory
from edp_claude.tools import build_registry
from edp_claude.tools._tools import ALL_TOOL_CLASSES, _resolve_fact_write_scope
from edp_claude.tools.roles import (
    CRUD_OBJECT_SCOPE,
    RETIRED_VERBS,
    ROLE_TOOLSETS,
    SPECIALIST_ONLY,
    _CONSOLIDATED_OUT,
    _SUPERSEDED_OUT,
    _OPERATOR_RETIRED,
    toolset_for_role,
)

# The consolidated memory-write verb whose class DOES now exist in
# ALL_TOOL_CLASSES (a3 landed it); roles.py still references it by name.
RECORD_CONTEXT = "record_context"

# W4 count ceilings (DESIGN-v6). Derived assertions track the live tables;
# the ceilings are the design contract a reviewer enforces. Planner is 29
# post-W4-remediation (d14/d15): the regression trimmed update_object +
# delete_object BELOW the derived floor, so restoring them (the planner MUST
# mutate its own plan's actions/steps) raises the floor from 27 to 29 — the
# true derived floor, not a relaxation.
# W15: search_context is added to the worker/reviewer/planner surfaces (they
# can ASK the recipe instead of loading it), so the reviewer floor rises 14→15
# and the planner floor 29→30 — the derived floor of the new contract, not a
# relaxation. Worker stays 22 (search_context filled its remaining headroom).
# W5: `convene_consult` joins the PLANNER surface — DESIGN-v6 §W5 names the
# planner in the role table ("Callable by neuron, planner (role table), the
# user's foreground session, or W10's escalation path"), and W10's escalation
# ladder instructs the planner to call it on a stuck action. So the planner
# floor rises 30→31, the same derived-floor move as 29→30 and 14→15 above —
# a REQUIRED verb cannot be folded away the way prose can, and dropping the
# planner registration to stay under 30 would break the W5 contract. Not a
# guard relaxation, and orthogonal to the W6.4 tool-bloat effort (which
# retires SUPERSEDED verbs; a new required capability is a different axis).
# d17 (W11/a6, neuron ruling e0cdcfe2): `get_recipe_digest` joins the PLANNER
# surface, so the planner floor rises 31→32. THREE planner guides instruct the
# planner to call it (planner-phase-ground/drive/author) while it lived only in
# _CONSULT — under EDP_ROLE_SCOPE=enforce the planner's post-compaction reground
# would have been refused, and its only fallback (read_object('recipe'), 169k
# chars on a mature recipe) does not fit in a tool result. Same derived-floor
# move as 27→29, 14→15, 29→30 and 30→31 above: a verb a role's OWN guides
# REQUIRE it to call cannot be folded away the way prose can. It grants no new
# reach (the planner already has read_object/query_objects/search_context over
# the same recipe) — only a cheaper path to data it could already obtain.
# `test_every_tool_a_roles_own_guides_instruct_it_to_call_is_in_its_toolset`
# below is the test that would have CAUGHT this; no other ceiling moved.
# s25/a4 (B3): the SAME derived-floor move, twice more. The planner floor rises
# 32→34 (`status_ping` + `neuron_search`, both instructed by its own guides;
# neuron_search is load-bearing — PoolSpawnWorker's guard B refuses to spawn a
# specialist action while a declared specialization is unresolved) and the
# reviewer floor 15→16 (`propose_spec_learning`, instructed by reviewer.md:141).
# `broker_send` was NOT granted despite being instructed: it takes an arbitrary
# `to=`, so it fails the precedent's own "grants no new reach" precondition. Its
# two planner call sites address the planner's parent, which `notify_above` /
# `ask_above` already do — the GUIDE was fixed instead. Same for the specialist's
# `update_object`. A verb a guide instructs is a defect in EXACTLY ONE of the two
# artifacts; deciding which is the point of this section.
# s25/a4 (neuron ruling d62(a)): `assemble_ruleset` leaves SPECIALIST_ONLY — it
# is a PURE READ (idempotent=True; only ctx.specs.load), misfiled in a set
# defined by AUTHORING. Granted to worker (22→23) and reviewer (16→17), re-added
# explicitly to the specialist, and it flows into the derived _NEURON (77→78).
# W9 part 2: the reviewer floor 17→19 for `record_direction_verdict` and
# `record_context`, the two verbs the direction-mode section of reviewer.md
# instructs. Same derived-floor test as above, and the second one passes the
# "grants no new reach" precondition structurally rather than by argument:
# RecordRejectedOption lands EVERY constraint-bearing ban `status="proposed"`,
# and the sole activation verb (`confirm_direction_constraints`) is withheld
# from this surface — so a reviewer that records context cannot steer the
# build. NO NEW ROLE: ROLE_TOOLSETS' key set is unchanged (pinned in
# test_w9_direction_reviewer.py::test_t4_no_new_role_exists_in_role_toolsets).
#
# ════════════════════════════════════════════════════════════════════════
# W6.4 — THE FIRST TIME THESE CEILINGS HAVE EVER GONE *DOWN*.
#
# Every move above was a derived-floor RAISE: a verb a role's own guides REQUIRED
# could not be folded away, so the floor rose and the grant carried a no-new-reach
# argument. Consolidation is the opposite move — a superseded verb is retired from
# every surface — so the floor DROPS, and the ceiling drops with it. A ceiling left
# at the old number is not "headroom", it is slack that lets the surface regrow
# silently. These are the DERIVED FLOOR, not a budget:
#   worker   23 -> 21  (-get_specialist_doc, -propose_spec_learning)
#   reviewer 19 -> 18  (-propose_spec_learning)   [W6.4]
#            18 -> 17  (-record_direction_verdict) [s29/a2 — the direction-review
#                       removal took the verb AND its registry entry with it]
#   planner  34 -> 34  (holds NONE of the retired verbs — W6.4 does not touch it)
#
# THE DESIGN LINE IS STALE, AND THAT IS A FINDING, NOT A LICENCE (s29/a1).
# DESIGN-v6:340 targets "worker <= 22, reviewer <= 14, planner <= 28, neuron <= 45".
# Three of the four sit BELOW the current derived floor, because every raise since
# was made under a recorded decision — the ledger, cited inline above:
#   planner  27->29  d14/d15   (W4 remediation: the plan-CRUD restore)
#   reviewer 14->15  W15       (search_context)  |  planner 29->30, same verb
#   planner  30->31  W5        (convene_consult)
#   planner  31->32  d17       (get_recipe_digest; neuron ruling e0cdcfe2)
#   planner  32->34  s25/a4 APPLYING d62 (status_ping + neuron_search)
#   reviewer 15->16  s25/a4 APPLYING d62 (propose_spec_learning — now WITHDRAWN by
#                    W6.4 through d62's OTHER branch, (b) FIX THE GUIDE)
#   worker   22->23  d62(a)    (assemble_ruleset — a pure read, misfiled in the
#   reviewer 16->17  d62(a)     o7 authoring carve-out)
#   reviewer 17->19  W9 part 2 (record_direction_verdict + record_context)
# d62 is the RULE ("a derived-floor grant must confer NO NEW REACH; else fix the
# guide"), NOT the decision that moved any single number — s25/a4 APPLIED it. So
# the code has not drifted from a decision here; the DESIGN LINE has drifted from
# the code. Correcting that line is the W6.5 wording pass's job (s29/a3). A test
# must never quietly ratify a number nobody decided.
#
# THE NEURON HAS NO ROW HERE, AND ITS DESIGN CEILING WAS UNREACHABLE BY
# CONSTRUCTION. DESIGN-v6 said "neuron <= 45"; _NEURON is DERIVED — the registry
# MINUS SPECIALIST_ONLY MINUS RETIRED_VERBS — so no retirement short of gutting the
# registry reaches 45. No test has ever asserted a neuron ceiling, so nothing was
# relaxed to arrive here: the bound was never implemented. Deliberately NOT added
# as a row that would fail on landing; the DESIGN LINE was corrected instead
# (s29/a3b).
#
# NO ARITHMETIC IS SPELLED OUT HERE, ON PURPOSE. This comment used to read
# "the measured surface is 76 ... registry(88)" and it was STALE ONE ACTION LATER:
# s29/a2 deleted RecordDirectionVerdict from the registry (88 -> 87), dropping the
# derived neuron surface to 75 and the reviewer's derived floor to 17. A hard-coded
# total in a comment is a claim that rots the moment a sibling touches the registry
# — the exact stale-universal class this suite exists to catch, committed in the
# suite that catches it. Derive it; never re-spell it.
# ════════════════════════════════════════════════════════════════════════
# s29/a4 (REVIEW, planner ruling): reviewer 18 -> 17. a2 deleted
# RecordDirectionVerdict + its registry entry AFTER a1 measured the surface, so
# the derived reviewer floor fell to 17 while this number stayed at 18 — and the
# suite stayed GREEN (17 <= 18), leaving exactly the "slack that lets the surface
# regrow silently" the comment above forbids. MEASURED at review: registry 87,
# derived neuron 75, reviewer 17. The ceiling IS the floor.
# v7 P8: planner 34 -> 35 (+record_grounding_brief — the planner authors the
# shared code map its own guides mandate; writes only its OWN plan's
# sidecar/fields, no new reach beyond its existing plan CRUD).
# v7 P4.1: reviewer 17 -> 18 (+record_action_status, own-leg-guarded — the
# reviewer closes its OWN review leg so review legs can run as
# role="reviewer" instead of the d67/d100 role="worker" workaround; the
# in-tool guard refuses any action whose plan:action differs from
# EDP_HANDLE, so d30 independence over REVIEWED actions stands).
# v7 follow-up (2026-07-16): worker 21 -> 22 (+sol_author_asset — the worker
# delegates VISUAL/3D/image asset authoring to Sol, which it cannot verify by
# hand. NO new reach into the recipe/plan: Sol writes only under a validated
# asset dir OUTSIDE the code tree, enforced by the tool, never edp objects).
# Context-diet Phase 3b (2026-07-30): the neuron ceiling EXISTS at last —
# _NEURON became a POSITIVE list (61 = the audited 54-verb guide floor + 7
# operational verbs), so the DESIGN-v6 "<=45" bound is finally assertable
# territory. 61 today; the descent to 45 rides the Phase-5 guide triage
# (descriptive call-form mentions deleted from the corpus lower the floor
# and this ceiling TOGETHER — the ceiling is the floor, never headroom).
# 2026-08-12 dead-surface retirement: worker 27 -> 26 (-sol_author_asset —
# superseded by the route-gated delegate_generate the worker already holds;
# see roles.py _BRIDGE_SUPERSEDED). The consult surface was deleted whole with
# its role. The ceiling IS the floor.
CEILINGS = {"worker": 26, "reviewer": 23, "planner": 41, "neuron": 62}  # +reflex (v7 WS7 — shadow sovereignty seam; inert in unshadowed shells)  # +budget_status (planner/neuron, v7 §2.6c — read-only planned-vs-actual)  # +1 each for the v7 WS3 test-lineage verbs (record_test_lineage worker / test_lineage_report reviewer+planner, 2026-08-05 — graph-sidecar only, no object reach); before that +1 each for the v7 WS1 bridge verbs (delegate_generate / delegate_review / adversarial_challenge — route-gated in .bridge.json, so the verb grants nothing until a human routes it); before that +list_subscriptions +unobserve (2026-07-20 monitor CRUD)


# ── helpers (mirror tests/test_scoped_facts.py so patterns stay uniform) ────
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc)


def _all_names() -> set[str]:
    return {c.name for c in ALL_TOOL_CLASSES}


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


def _save_recipe(ctx, rid, domain="software_engineering"):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain=domain, state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now(),
    ))


def _save_plan(ctx, rid, plan_id, domain="software_engineering"):
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1", domain=domain,
        shape="parallel_multitool", goal="g", state="dispatching"))


def _clear_shell_env(mp):
    """Neutralise the inherited worker shell env so a test sees the SAME
    baseline whether run bare or under a worker's leaked env."""
    mp.delenv("EDP_ROLE", raising=False)
    mp.delenv("EDP_HANDLE", raising=False)


# ════════════════════════════════════════════════════════════════════════
# (1) MEMBERSHIP — every role name resolves to a real registered tool
# ════════════════════════════════════════════════════════════════════════
def test_every_role_toolset_name_is_a_registered_tool():
    all_names = _all_names()
    for role, toolset in ROLE_TOOLSETS.items():
        unknown = [
            n for n in toolset
            if n not in all_names and n != RECORD_CONTEXT
        ]
        assert not unknown, (
            f"role {role!r} names {unknown} that are not registered tools "
            "in ALL_TOOL_CLASSES (nor the record_context replacement)")
    # record_context is now a REAL class, so the union is fully resolved.
    assert RECORD_CONTEXT in all_names


def test_specialist_only_is_subset_of_specialist_and_absent_from_neuron():
    specialist = ROLE_TOOLSETS["specialist"]
    neuron = ROLE_TOOLSETS["neuron"]
    # o7 — authoring spec CONTENT is the specialist's job alone.
    assert SPECIALIST_ONLY <= specialist
    assert SPECIALIST_ONLY.isdisjoint(neuron)
    # spot-check the invariant on a representative verb.
    assert "write_specialist_doc" in specialist
    assert "write_specialist_doc" not in neuron


def test_consolidated_write_verbs_absent_from_every_role_but_record_context_present():
    # the four old memory-write verbs collapsed into record_context: they
    # appear in NO role surface, and record_context replaces them where a
    # role writes context (worker/planner/specialist/neuron).
    consolidated = {"record_decision", "record_assumption",
                    "record_rejected_option", "remember"}
    for role, toolset in ROLE_TOOLSETS.items():
        assert consolidated.isdisjoint(toolset), role
    for role in ("worker", "planner", "specialist", "neuron"):
        assert RECORD_CONTEXT in ROLE_TOOLSETS[role], role


def test_w6_4_every_retired_verb_is_absent_from_every_role_and_still_registered():
    """W6.4 — the retirement, over ALL NINE surfaces, including the DERIVED one.

    THE SURFACE THAT WOULD HAVE BEEN MISSED: `_NEURON` is derived by subtraction,
    so it held all four superseded verbs WITHOUT NAMING ANY OF THEM. A retirement
    that only edited the explicit role sets would have left them live on the one
    surface no one greps. Hence the assertion is over `ROLE_TOOLSETS.items()`, not
    over the sets a human hand-edited.

    v7 P0 (break-and-migrate, 2026-07-12) went further than W6.4: the retired
    classes are DEREGISTERED from ALL_TOOL_CLASSES — a retired verb no longer
    resolves ANYWHERE, not even on the absent-role fail-open full set. (The
    four memory-write bodies survive only as RecordContext's internal
    delegation targets.) The registration half of the old pin INVERTED:
    absence from the registry is now the invariant."""
    assert _SUPERSEDED_OUT == {"get_specialist_doc", "propose_spec_learning",
                               "resolve_spec_learning", "record_step"}
    # 2026-07-25: RETIRED_VERBS gained a THIRD source — `_OPERATOR_RETIRED`, for
    # verbs withdrawn by operator ruling rather than because a successor reaches
    # further. 2026-08-12: a FOURTH — `_BRIDGE_SUPERSEDED` (sol_consult /
    # sol_author_asset, superseded by the provider-bridge delegates). The union
    # is asserted against the same sets roles.py builds it from, so this stays
    # a real pin and not a tautology, while remaining open to a future
    # retirement without another test edit.
    from edp_claude.tools.roles import _BRIDGE_SUPERSEDED
    assert RETIRED_VERBS == (
        _CONSOLIDATED_OUT | _SUPERSEDED_OUT | _OPERATOR_RETIRED
        | _BRIDGE_SUPERSEDED)
    assert "convene_consult" in _OPERATOR_RETIRED
    assert _BRIDGE_SUPERSEDED == {"sol_consult", "sol_author_asset"}
    assert _CONSOLIDATED_OUT.isdisjoint(_SUPERSEDED_OUT)
    assert _OPERATOR_RETIRED.isdisjoint(_CONSOLIDATED_OUT | _SUPERSEDED_OUT)
    assert _BRIDGE_SUPERSEDED.isdisjoint(
        _CONSOLIDATED_OUT | _SUPERSEDED_OUT | _OPERATOR_RETIRED)

    for role, toolset in ROLE_TOOLSETS.items():
        leaked = sorted(RETIRED_VERBS & toolset)
        assert not leaked, f"role {role!r} still holds retired verb(s) {leaked}"

    # v7 P0: DEREGISTERED — a retired verb resolves nowhere at all
    assert RETIRED_VERBS.isdisjoint(_all_names()), sorted(
        RETIRED_VERBS & _all_names())

    # …and each retired verb's SUCCESSOR is really on the surface that lost it,
    # so the retirement removed a verb, never a capability.
    assert "get_specialist_docs" in ROLE_TOOLSETS["worker"]
    assert "get_specialist_docs" in ROLE_TOOLSETS["reviewer"]
    # spec flowback: the W3 auto-propose rides emit_recipe_event(kind="learning")
    for role in ("worker", "reviewer"):
        assert "emit_recipe_event" in ROLE_TOOLSETS[role], role
    assert "resolve_spec_learnings" in ROLE_TOOLSETS["specialist"]
    # record_step's guarded successors stay with the recipe owner
    assert {"add_step", "record_step_result"} <= ROLE_TOOLSETS["neuron"]
    # 2026-08-12: the bridge successors really stand where the sol verbs fell —
    # delegation for the worker, the cross-provider consult for the advisory role
    assert "delegate_generate" in ROLE_TOOLSETS["worker"]
    assert "consult_external" in ROLE_TOOLSETS["curiosity"]


# ════════════════════════════════════════════════════════════════════════
# (2) SIZE — per-role ceilings
# ════════════════════════════════════════════════════════════════════════
def test_role_sizes_within_ceilings():
    for role, ceiling in CEILINGS.items():
        assert len(ROLE_TOOLSETS[role]) <= ceiling, (
            f"{role} surface = {len(ROLE_TOOLSETS[role])} exceeds ceiling "
            f"{ceiling}")


# ════════════════════════════════════════════════════════════════════════
# (3) SEAM — build_mcp scopes the registered surface to EDP_ROLE
# ════════════════════════════════════════════════════════════════════════
def _build_mcp_names(tmp_path):
    """The CALLABLE surface: real tools only. Phase 3c registers off-scope
    tools as refusal STUBS under enforce (description '(not available to
    role=…)') so a mis-scoped call gets a structured refusal instead of an
    unknown-tool error — they grant nothing and are excluded here."""
    from edp_claude.mcp_server import build_mcp
    mcp = build_mcp(tmp_path)
    return sorted(t.name for t in mcp._tool_manager.list_tools()
                  if not (t.description or "").startswith(
                      "(not available to role="))


def test_seam_worker_role_scopes_to_worker_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE", "worker")
    # W4 remediation (d14/d15): FILTERING is now the ENFORCE-mode behaviour;
    # the shipped default is warn (register all + log off-set calls). This test
    # proves the enforce filter, so it opts in explicitly. Warn-mode
    # register-all + log-and-proceed is proven in tests/test_w4_role_scoping.py.
    monkeypatch.setenv("EDP_ROLE_SCOPE", "enforce")

    names = _build_mcp_names(tmp_path)
    assert set(names) == set(ROLE_TOOLSETS["worker"])
    assert len(names) <= CEILINGS["worker"]
    # positive + negative membership on the LIVE seam
    assert "pool_close_self" in names
    assert "record_context" in names
    assert "next_action" not in names          # planner-only
    assert "pool_spawn_worker" not in names     # planner-only
    assert "record_decision" not in names       # consolidated out


def test_seam_reviewer_role_scopes_to_reviewer_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    # enforce-mode filter (see the worker seam test) — warn is the default now.
    monkeypatch.setenv("EDP_ROLE_SCOPE", "enforce")

    names = _build_mcp_names(tmp_path)
    assert set(names) == set(ROLE_TOOLSETS["reviewer"])
    assert len(names) <= CEILINGS["reviewer"]
    assert "record_branch_verdict" in names
    assert "get_specialist_docs" in names


def test_seam_unset_role_registers_full_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    _clear_shell_env(monkeypatch)

    names = _build_mcp_names(tmp_path)
    assert len(names) == len(ALL_TOOL_CLASSES)
    assert set(names) == _all_names()


def test_seam_unknown_role_fails_open_to_full_set(tmp_path, monkeypatch):
    # a role NOT in the table must fail OPEN (register everything) — a shell
    # is never silently starved of tools.
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE", "totally-unknown-role")

    assert toolset_for_role("totally-unknown-role") is None
    names = _build_mcp_names(tmp_path)
    assert len(names) == len(ALL_TOOL_CLASSES)


def test_filter_logic_directly_worker_and_none(monkeypatch):
    # drive the pure filter (build_registry + toolset_for_role) without the
    # FastMCP SDK, exactly the membership set-op the seam applies.
    ctx = make_context  # unused sentinel to keep import obvious
    tools = [c.name for c in ALL_TOOL_CLASSES]
    allowed = toolset_for_role("worker")
    assert allowed is not None
    scoped = [n for n in tools if n in allowed]
    assert set(scoped) == set(ROLE_TOOLSETS["worker"])
    # absent role -> None -> full set (no filter)
    assert toolset_for_role(None) is None
    assert toolset_for_role("") is None


# ════════════════════════════════════════════════════════════════════════
# (4) RECORD_CONTEXT — routing + refusals
# ════════════════════════════════════════════════════════════════════════
async def test_record_context_routes_decision_to_recipe_store(tmp_path, monkeypatch):
    _clear_shell_env(monkeypatch)
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    _save_recipe(ctx, "recipe-dec-aaa")

    res = await t["record_context"].run({
        "kind": "decision", "recipe_id": "recipe-dec-aaa",
        "text": "chose the tables-as-data role surface", "rationale": "o7"})
    assert isinstance(res, ToolOk), res

    r = ctx.recipes.load("recipe-dec-aaa")
    assert any("tables-as-data" in d.text for d in r.context.decisions)
    # routed to decisions ONLY — assumptions/rejected untouched
    assert r.context.assumptions == []
    assert r.context.rejected_options == []


async def test_record_context_routes_fact_to_memory(tmp_path, monkeypatch):
    # neuron under a recipe writes a fact; it lands in the memory port and
    # recall surfaces it (routing proof, distinct from the decision store).
    monkeypatch.setenv("EDP_ROLE", "neuron")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    _save_recipe(ctx, "recipe-fact-aaa")

    res = await t["record_context"].run({
        "kind": "fact",
        "fact": {"text": "record_context delegates to Remember"},
        "scope": "recipe", "recipe_id": "recipe-fact-aaa",
        "domain": "software_engineering"})
    assert isinstance(res, ToolOk) and res.data["stored"] is True
    scoped = (tmp_path / ".memory" / "recipe" / "recipe-fact-aaa"
              / "facts.jsonl")
    assert scoped.exists()


async def test_record_context_refuses_decision_without_recipe_id(tmp_path, monkeypatch):
    _clear_shell_env(monkeypatch)
    t = _tools(make_context(tmp_path))
    res = await t["record_context"].run({
        "kind": "decision", "text": "no recipe given"})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "requires recipe_id" in res.message


async def test_record_context_refuses_decision_for_unknown_recipe(tmp_path, monkeypatch):
    _clear_shell_env(monkeypatch)
    t = _tools(make_context(tmp_path))
    res = await t["record_context"].run({
        "kind": "decision", "recipe_id": "no-such-recipe",
        "text": "stmt"})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "unknown recipe" in res.message


async def test_record_context_refuses_fact_without_body(tmp_path, monkeypatch):
    _clear_shell_env(monkeypatch)
    t = _tools(make_context(tmp_path))
    res = await t["record_context"].run({"kind": "fact"})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "requires a fact body" in res.message


async def test_record_context_rejects_invalid_kind(tmp_path, monkeypatch):
    _clear_shell_env(monkeypatch)
    t = _tools(make_context(tmp_path))
    res = await t["record_context"].run({"kind": "not-a-real-kind"})
    # the Literal InputModel refuses at validation (never reaches the body)
    assert isinstance(res, ToolError)
    assert res.ok is False
    assert "input_invalid" in res.code


async def test_record_context_north_star_neuron_only_and_landed_w1(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    _save_recipe(ctx, "r-ns")

    # a worker may NOT patch the immutable-goal north star (role guard first)
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    res = await t["record_context"].run({"kind": "north_star_update"})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "neuron-only" in res.message

    # W1 has LANDED: the neuron route now creates/updates the north star and
    # appends to evolution_log (no longer refuses-pending-W1).
    monkeypatch.setenv("EDP_ROLE", "neuron")
    # missing text is refused with a clear instruction
    miss = await t["record_context"].run(
        {"kind": "north_star_update", "recipe_id": "r-ns"})
    assert isinstance(miss, ToolError) and miss.code == "tool_precondition"
    assert "evolution_log" in miss.message
    # a valid update succeeds and materializes the north star
    ok = await t["record_context"].run(
        {"kind": "north_star_update", "recipe_id": "r-ns",
         "text": "initial shape", "title": "single-pass"})
    assert isinstance(ok, ToolOk)
    ns = ctx.north_star.load("r-ns")
    assert ns.user_goal_verbatim == "g"      # sourced from the recipe
    assert ns.current_shape == "single-pass"
    assert len(ns.evolution_log) == 1 and ns.evolution_log[0].text == "initial shape"


# ════════════════════════════════════════════════════════════════════════
# (5) SCOPED FACTS — isolation, neuron-only global, lineage default, legacy
# ════════════════════════════════════════════════════════════════════════
async def test_recipe_scoped_fact_isolated_across_recipes(tmp_path):
    # port-level (no env): a recipe-scoped fact is recalled in its recipe and
    # NOT in a different recipe's recall.
    mem = FileMemory(tmp_path / ".memory" / "facts.jsonl")
    await mem.remember(
        {"text": "r1 scoped secret", "durable": True}, "generic",
        scope="recipe", recipe_id="R1")

    in_r1 = await mem.recall("r1 scoped", recipe_id="R1")
    assert any("r1 scoped secret" in str(r) for r in in_r1)

    in_r2 = await mem.recall("r1 scoped", recipe_id="R2")
    assert not any("r1 scoped secret" in str(r) for r in in_r2)


def test_non_neuron_global_write_is_refused(tmp_path, monkeypatch):
    # the scope RESOLVER (single source of the guard) refuses a global write
    # from a non-neuron role.
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    err, scope, _rid, _dom = _resolve_fact_write_scope(
        ctx, scope="global", recipe_id="recipe-x", domain="software_engineering")
    assert err is not None
    assert isinstance(err, ToolError)
    assert "neuron-only" in err.message


def test_neuron_defaults_to_recipe_scope_not_global(tmp_path, monkeypatch):
    # lineage-first: a neuron with a recipe in hand DEFAULTS to recipe scope,
    # NOT the shared global namespace, even though it COULD write global.
    monkeypatch.setenv("EDP_ROLE", "neuron")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-neuron-aaa")

    err, scope, rid, _dom = _resolve_fact_write_scope(
        ctx, scope=None, recipe_id="recipe-neuron-aaa", domain=None)
    assert err is None
    assert scope == "recipe"
    assert rid == "recipe-neuron-aaa"

    # and the neuron IS allowed to promote to global explicitly
    err2, scope2, _rid2, _dom2 = _resolve_fact_write_scope(
        ctx, scope="global", recipe_id="recipe-neuron-aaa",
        domain="software_engineering")
    assert err2 is None and scope2 == "global"


async def test_recall_falls_back_to_legacy_flat_trail(tmp_path):
    # when NO scoped trail exists yet, recall still reads the pre-v6 flat
    # .memory/facts.jsonl (hydrate-on-read; no migration).
    mem = FileMemory(tmp_path / ".memory" / "facts.jsonl")
    legacy = tmp_path / ".memory" / "facts.jsonl"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps({"text": "legacy pre-v6 fact"}) + "\n", encoding="utf-8")

    got = await mem.recall("legacy pre-v6")
    assert any("legacy pre-v6 fact" in str(r) for r in got)


# ════════════════════════════════════════════════════════════════════════
# (6) d17 — THE GUIDE/TOOLSET INVARIANT
#
# The defect this section exists for: `get_recipe_digest` was instructed by
# three PLANNER guides but absent from the planner's toolset. A test that
# asserted the TOKEN ("get_recipe_digest in _PLANNER") would have been written
# only AFTER someone noticed. So assert the INVARIANT across the surfaces
# instead (W5/a5's durable lesson — "when an invariant spans N surfaces,
# enumerate the N surfaces"):
#
#     every tool a role's OWN guides instruct THAT role to CALL
#     is present in that role's toolset.
#
# ── The two discriminators, and why ────────────────────────────────────────
#
# (1) CORPUS — a role's OWN guides. A role's docs are its `.claude/commands/`
#     file plus the guides that file loads via `get_guide(...)`. But a guide
#     loaded by TWO OR MORE role command files is a role-NEUTRAL REFERENCE doc
#     (architecture-vocabulary, reactive-streams, loop-and-heartbeat): it
#     DESCRIBES the tool surface rather than instructing one role to use it, and
#     it is the dominant false-positive source — architecture-vocabulary names
#     `create_object(...)` in a sentence aimed at the neuron, which would
#     "prove" the worker needs it. Shared docs are therefore excluded, and the
#     rule is DERIVED (load-count >= 2), not a hand-kept list that drifts.
#
# (2) INSTRUCTED CALL vs MENTION — guides name tools NEGATIVELY too ("the only
#     remaining fork is re-training (`update_specialist`), which is the
#     neuron's call, not yours"). The discriminator is CALL FORM: the tool name
#     followed by an open paren. Two structural exclusions ride on top, both
#     IMPORTED from roles.py rather than re-spelled (a re-spelled constant is a
#     constant that drifts):
#       * _CONSOLIDATED_OUT — verbs deliberately absent from EVERY surface
#         (superseded by record_context). A guide still calling one is a STALE
#         GUIDE, not a toolset gap. (neuron-phase-d.md still says `remember(…)`.)
#       * SPECIALIST_ONLY, for non-specialist roles — the o7 invariant. When
#         planner-phase-author says "the WORKER's `assemble_ruleset(…)` errors",
#         it is describing another actor's call, not instructing its own.
#
# NOTE: no `re` module here. Coding-standard #7 forbids regex without user
# approval, and plain str.find with an identifier-boundary check is both
# sufficient and easier to read.
# ════════════════════════════════════════════════════════════════════════

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"
GUIDES_DIR = REPO_ROOT / "docs" / "guides"

# The command file that IS each role's entry-point brief. ALL NINE enumerated —
# the point of the exercise is to cover every surface, not spot-check one. The
# three advisory roles joined ROLE_TOOLSETS in s25/a4, and this map is what
# brings them under the d17 invariant too.
ROLE_COMMAND_FILE = {
    "worker": "worker.md",
    "planner": "agentic-plan.md",
    "reviewer": "reviewer.md",
    "specialist": "specialist.md",
    "neuron": "neuron.md",
    "curiosity": "curiosity.md",
    # goal_keeper / pattern_observer rows deleted with their DEAD roles
    # (owner ruling 2026-08-04); consult.md deleted with the retired consult
    # shell role (2026-08-12 dead-surface sweep).
}

# ── DECLARED corpus: guides that GOVERN a role but that the derived walk below
# cannot attribute to it (s25/a4, closing a1 blocker 5) ─────────────────────
# Two distinct reasons a governing guide escapes the derived rule, one entry for
# each. A declaration BYPASSES the shared-guide exclusion, so it is deliberately
# a short, reasoned list — never a dumping ground.
EXTRA_ROLE_GUIDES: dict[str, dict[str, str]] = {
    "specialist": {
        "specialist-training": (
            "The specialist's standing training rules. Reachable from NO command "
            "file (specialist.md calls get_guide zero times), so the derived walk "
            "never sees it — yet it is the specialist's own doctrine. This is the "
            "declaration that lets the gate see specialist-training.md:31."),
    },
    "planner": {
        "environment-discovery": (
            "A per-role cold-start table whose PLANNER ROW instructs planner calls "
            "(`status_ping('<plan_id>:<action_id>')` at :20). It is reachable only "
            "THROUGH architecture-vocabulary.md:220 — a shared reference doc — so "
            "the derived rule classes it role-neutral and excludes it. Declaring it "
            "for the PLANNER attributes the planner's own row to the planner "
            "WITHOUT dragging the doc into the worker/neuron corpora, where the "
            "same call forms are OTHER roles' rows (that misattribution is exactly "
            "the false positive a1 and a2 both warned against). Solved by "
            "declaration, not by an instruct-vs-describe heuristic — building that "
            "discriminator is design work and is out of scope here."),
    },
}

# ── the W4-ENFORCE-READINESS BACKLOG ───────────────────────────────────────
# Gaps this invariant surfaces that are NOT in scope for W11/a6 (the neuron's
# verbatim scope guard: "ONLY get_recipe_digest into the planner floor + the
# sync/test. Do NOT expand into a broader role-scope audit"). Each carries a
# REASON, because a bare allowlist becomes a dumping ground.
#
# The test asserts EXACT equality against this table, so the backlog cannot rot:
# a NEW gap fails the test, and FIXING a listed gap fails it too until the entry
# is removed. `("planner", "get_recipe_digest")` is deliberately ABSENT — that
# is the d17 defect, now fixed, and its absence is what makes the mutation check
# (remove it from _PLANNER → this test goes RED) meaningful.
#
# s25/a4 (B3) EMPTIED THIS TABLE. All seven entries were dispositioned, each as
# a defect in EXACTLY ONE of the two artifacts (the toolset or the guide):
#   GRANTED (derived floor — the role's own guides REQUIRE the verb and it
#   confers no new reach): planner += status_ping, neuron_search;
#   reviewer += propose_spec_learning; specialist += neuron_set_base_session,
#   neuron_set_status.
#   GUIDE FIXED (the verb was never the role's to call): planner broker_send —
#   it takes an ARBITRARY `to=` and so fails the derived-floor precedent's own
#   "no new reach" precondition. Both its call sites addressed the planner's
#   PARENT, which notify_above/ask_above already do (verified: `plan_closed` and
#   `question` are in edp_contracts.CORE_KINDS, and NotifyAbove sends to=parent
#   with an arbitrary kind), so planner-phase-drive.md:56,109 were rewritten to
#   the equivalent lineage-scoped verbs. reviewer get_specialist_doc → the guide
#   now names the plural (a pass-through superset). specialist update_object →
#   descriptive prose about append-only semantics; no role carries "spec" in
#   CRUD_OBJECT_SCOPE, so the verb would register and then be refused.
#
# The table stays as the mechanism: exact equality means a NEW gap fails the
# test, and a FIXED gap left listed fails it too. An EMPTY table is the strongest
# state it can be in — and `test_every_tool_a_roles_own_guides_instruct_it_to_call_is_in_its_toolset`
# is mutation-proved (remove a grant → RED; re-add a call form → RED), so empty
# means "no gaps in the scanned corpus", never "nothing is looked at".
KNOWN_GUIDE_TOOLSET_GAPS: dict[tuple[str, str], str] = {}

# ── COVERAGE, ASSERTED RATHER THAN ASSUMED ──────────────────────────────────
# A guide that no role reaches is scanned by nobody. Silence there reads as "no
# gaps" when it means "never looked" — the exact failure mode this whole section
# exists to kill. So the un-attributed guides are ENUMERATED with a reason, and
# `test_every_guide_is_either_scanned_shared_or_explicitly_unattributed` pins
# the set: adding a guide to docs/guides/ that no command file reaches FAILS
# until someone decides which role it governs (or declares it role-neutral).
#
# s26/a2 — THE ESCAPE HATCH, AND WHAT WAS DONE ABOUT IT (asked: tighten it or
# justify it in writing; ANSWER: BOTH, on different axes).
#
# THE HATCH, stated fairly: a future author could hide a gap by declaring a new
# guide unattributed with a >30-char reason. It would then be scanned by NOBODY,
# and its silence would read as "no gaps" — this section's own disease.
#
# JUSTIFIED (the role-attribution exemption is kept, and is legitimate): the
# entries below are NOT unattributed by oversight. Eight are compiled specialist
# STACK docs — project-independent craft a worker loads via
# `get_specialist_docs(spec_ids=[…])`; no role's toolset governs their content,
# and inventing an owner role for them would be fiction. `framework-ocak` is a
# RETIRED role. The remaining three are self-declared role-neutral in their own
# headers. Forcing a role attribution onto any of these would manufacture the
# false positives that `_shared_guides` exists to avoid.
#
# TIGHTENED (the hatch no longer buys INVISIBILITY, only role-exemption): a
# declared-unattributed guide is still read, in full, by
# `tests/test_s26_guide_tool_names.py`, which asserts that no live guide CALLS a
# verb that is not a registered tool. `test_unscanned_guides_escape_role_
# attribution_but_not_this_gate` pins that relationship, and
# `test_s26_corpus_is_a_strict_superset_of_the_w4_scanned_corpus` proves the
# containment rather than assuming it (d65). So the worst a future author can
# now buy with a >30-char reason is exemption from ROLE attribution — never
# exemption from tool-name validation.
#
# STILL OPEN, stated rather than closed over: nothing here forces a guide to be
# attributed to the role it actually governs. A guide that IS a role's doctrine
# but is parked in this table would still escape the d17 class-guard. Narrowing
# that needs an instruct-vs-describe discriminator (see EXTRA_ROLE_GUIDES's note
# — design work, deliberately out of scope). The hatch is smaller, not gone.
# REMOVED from this hatch by s29/a3b: "verification-craft".
# It is no longer "reached by declaration from no single role" — that reason went
# FALSE the moment the guide was linked. W6.5's wording pass gave
# planner-phase-drive.md a `get_guide("verification-craft")` pointer at the exact
# place a planner judges slow-vs-hung, because verification-craft carries the
# blind-instrument table ("name an instrument's blind spot BEFORE you reason from
# it") — the discipline whose absence let a planner "refute" a worker's permission
# freeze by citing output growth that could not see it. The guide is now
# PLANNER-ATTRIBUTED and therefore SCANNED by the d17 class-guard.
# This is a guard TIGHTENING, not a relaxation: the doc moves from role-EXEMPT into
# a role's corpus, so it gains toolset-gap checking it never had (it was already
# read by the s26 unregistered-tool gate, which reads every guide regardless).
UNSCANNED_GUIDES: dict[str, str] = {
    "provider-bridge": (
        "v7 WS1 (2026-08-05): OPERATOR-facing configuration note — how to add "
        ".bridge.json delegates (http backends, key env vars, routes). No role "
        "is instructed to read it; the bridge VERBS are governed by the owning "
        "roles' own guides and the tool docstrings."),
    "framework-ocak": (
        "OCAK is a RETIRED role — its tombstone card ocak.md was deleted "
        "2026-08-12; the audit questions live on for run_ocak_audit."),
    "reactive-streams-effects": (
        "Companion reference to the SHARED reactive-streams.md (:3, 'Companion "
        "to get_guide(\"reactive-streams\")'). Role-neutral: it documents the "
        "effect plane for every role."),
    "reactive-streams-reference": (
        "Companion reference to the SHARED reactive-streams.md (:3). "
        "Role-neutral operator/combinator catalogue."),
    # The eight compiled specialist stack docs. These are CRAFT docs a worker
    # loads via get_specialist_docs(spec_ids=[…]) — project-independent stack
    # rules, not role guides. No role's toolset governs their content.
    "specialist-actor-clarity": "Compiled specialist stack doc, not a role guide.",
    "specialist-actor-identifier": "Compiled specialist stack doc, not a role guide.",
    "specialist-concern-validator": "Compiled specialist stack doc, not a role guide.",
    "specialist-estimation": "Compiled specialist stack doc, not a role guide.",
    "specialist-feasibility": "Compiled specialist stack doc, not a role guide.",
    "specialist-goal-setter": "Compiled specialist stack doc, not a role guide.",
    "specialist-new-tech-detector": "Compiled specialist stack doc, not a role guide.",
    "specialist-role-clarity": "Compiled specialist stack doc, not a role guide.",
    "external-neuron": (
        "Operator/integration doc for running the NEURON ROLE ON A NON-CLAUDE "
        "HARNESS (v7 follow-up): its audience is a human wiring an external "
        "agent CLI + the out-of-process heartbeat driver, not a Claude shell "
        "loading discipline. No Claude role's toolset governs it; the MCP "
        "surface it names is enforced by EDP_ROLE=neuron at the server."),
}

_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_-")


def _guides_loaded_by(text: str) -> set[str]:
    """The guide names a command file loads via `get_guide("name")`. Tolerates
    the whitespace/newline a markdown line-wrap puts inside the parens."""
    token = "get_guide("
    out: set[str] = set()
    start = 0
    while (i := text.find(token, start)) >= 0:
        start = i + len(token)
        j = start
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        if j < len(text) and text[j] in "\"'":
            quote = text[j]
            end = text.find(quote, j + 1)
            if end > 0:
                out.add(text[j + 1:end])
    return out


def _called_in(text: str, names) -> set[str]:
    """The `names` that appear in CALL FORM — `name(` — in `text`.

    The preceding character must not be an identifier char, so `_observe(` and
    `xrecall(` do not count as `observe(` / `recall(`. A longer tool name that
    merely starts with a shorter one is handled by the paren check itself:
    `get_specialist_docs(` is not a call of `get_specialist_doc`."""
    found: set[str] = set()
    for name in names:
        start = 0
        while (i := text.find(name, start)) >= 0:
            start = i + 1
            if i and text[i - 1] in _IDENT_CHARS:
                continue
            j = i + len(name)
            while j < len(text) and text[j] in " \t":
                j += 1
            if j < len(text) and text[j] == "(":
                found.add(name)
                break
    return found


def _command_text(role: str) -> str:
    return (COMMANDS_DIR / ROLE_COMMAND_FILE[role]).read_text(encoding="utf-8")


def _guide_path(guide: str) -> Path:
    return GUIDES_DIR / f"{guide}.md"


def _shared_guides() -> set[str]:
    """Guides that TWO OR MORE role command files load DIRECTLY: role-NEUTRAL
    reference docs. They describe the surface; they do not instruct one role.

    Deliberately a ONE-HOP measure over the command files. A doc that two
    different roles are told to load at startup is by construction addressed to
    neither of them in particular. (Making this measure transitive instead is
    unsound — see `_reachable_guides`.)"""
    loads: dict[str, int] = {}
    for role in ROLE_COMMAND_FILE:
        for guide in _guides_loaded_by(_command_text(role)):
            loads[guide] = loads.get(guide, 0) + 1
    return {g for g, n in loads.items() if n >= 2}


def _reachable_guides(role: str) -> set[str]:
    """The role-SPECIFIC guides transitively reachable from a role's command
    file — the walk STOPS at a shared reference doc rather than descending
    through it.

    The old rule walked ONE hop, so the seven `planner-shape-*.md` guides —
    loaded by `planner-phase-author.md`, not by `agentic-plan.md` — and the five
    `neuron-phase-*.md` guides behind `orchestrator-launch.md` were scanned for
    nobody (a1 blocker 5). Transitivity fixes that.

    NOT DESCENDING INTO SHARED DOCS IS LOAD-BEARING, and it is the one thing
    that made the first version of this walk wrong. A role-neutral reference doc
    CATALOGUES the guide space: `architecture-vocabulary.md:231` is a table row
    naming `get_guide("orchestrator-launch")`, and `:220` points at
    `environment-discovery.md`. Descending through it makes every guide
    reachable from every role that loads the vocabulary, so `orchestrator-launch`
    and all five `neuron-phase-*` guides tip past the >=2 shared threshold and
    fall OUT of the neuron's own corpus. The walk would have made the gate
    BLINDER than the one-hop rule it replaced, while looking wider. A catalogue
    entry is not a load.

    A guide naming itself in its own "Load via `get_guide(...)`" header is
    absorbed by the visited set."""
    shared = _shared_guides()
    seen: set[str] = set()
    frontier = [g for g in _guides_loaded_by(_command_text(role))
                if g not in shared]
    while frontier:
        guide = frontier.pop()
        if guide in seen:
            continue
        seen.add(guide)
        path = _guide_path(guide)
        if path.exists():
            frontier.extend(
                g for g in _guides_loaded_by(path.read_text(encoding="utf-8"))
                if g not in shared and g not in seen)
    return seen


def _role_docs(role: str) -> list[Path]:
    """A role's OWN docs: its command file, the role-SPECIFIC guides it reaches
    transitively, and the guides explicitly DECLARED to govern it."""
    docs = [COMMANDS_DIR / ROLE_COMMAND_FILE[role]]
    names = set(_reachable_guides(role))
    # a declaration attributes a governing doc to ONE role and bypasses the
    # shared-guide exclusion; see EXTRA_ROLE_GUIDES for why each is listed.
    names |= set(EXTRA_ROLE_GUIDES.get(role, {}))
    for guide in sorted(names):
        path = _guide_path(guide)
        if path.exists():
            docs.append(path)
    return docs


def _gaps() -> dict[tuple[str, str], list[str]]:
    """(role, tool) -> the doc names that instruct that role to call it, for
    every tool MISSING from the role's toolset."""
    all_names = _all_names() | {RECORD_CONTEXT}
    gaps: dict[tuple[str, str], list[str]] = {}
    for role, toolset in ROLE_TOOLSETS.items():
        # structural exclusions — imported from roles.py, never re-spelled.
        # RETIRED_VERBS (W6.4) widens what was _CONSOLIDATED_OUT on the SAME
        # reasoning: a verb retired from EVERY surface can never be "missing
        # from a role's toolset" — a guide still calling one is a STALE GUIDE,
        # not a toolset gap, and the two defects want different remedies.
        # CONSEQUENCE, and it is why the W6.4 guard lives elsewhere: this test
        # CANNOT see a stale retired-verb call form, by construction. The gate
        # that owns it is test_s26_guide_tool_names.py::
        # test_no_live_guide_calls_a_retired_verb, over a strictly WIDER corpus
        # (every command + every guide, including the shared/unattributed docs
        # the role walk below drops). That is the test that is mutation-proved.
        exclude = set(RETIRED_VERBS)
        if role != "specialist":
            exclude |= set(SPECIALIST_ONLY)
        candidates = all_names - exclude
        for doc in _role_docs(role):
            text = doc.read_text(encoding="utf-8")
            for tool in _called_in(text, candidates) - toolset:
                gaps.setdefault((role, tool), []).append(doc.name)
    return gaps


def test_planner_phase_guides_are_inside_the_planner_corpus():
    """The mutation check is THEATRE unless the guide that instructs
    `get_recipe_digest(...)` is actually scanned. Pin the corpus explicitly, so
    a future exclusion rule cannot quietly sweep the planner's own phase guides
    out and leave the invariant test passing with the defect present."""
    corpus = {p.name for p in _role_docs("planner")}
    assert {"planner-phase-ground.md", "planner-phase-drive.md",
            "planner-phase-author.md"} <= corpus, corpus
    # and the one that carries the call form is really scanned for it
    ground = (GUIDES_DIR / "planner-phase-ground.md").read_text(encoding="utf-8")
    assert "get_recipe_digest" in _called_in(ground, {"get_recipe_digest"})


def test_shared_reference_guides_are_excluded_as_role_neutral():
    """The corpus rule is DERIVED (loaded by >= 2 role command files), not a
    hand-kept list. Pin both directions: the reference docs are out, a
    role-specific phase guide is in."""
    shared = _shared_guides()
    assert {"architecture-vocabulary", "reactive-streams",
            "loop-and-heartbeat"} <= shared
    assert "planner-phase-ground" not in shared
    assert "neuron-phase-d" not in shared


def test_call_form_discriminates_an_instructed_call_from_a_mention():
    """The heuristic itself, on the real false-positive shapes from the guides."""
    names = {"train_specialist", "update_specialist", "observe", "recall",
             "get_specialist_doc", "get_specialist_docs"}
    # a bare backticked MENTION is not a call
    assert _called_in("`train_specialist` is an orchestrator tool", names) == set()
    assert _called_in("the only fork is re-training (`update_specialist`), "
                      "which is the neuron's call, not yours", names) == set()
    # a call IS a call, with or without a space before the paren
    assert _called_in("call `observe(spec=…)` then", names) == {"observe"}
    assert _called_in("recall (query)", names) == {"recall"}
    # an identifier that merely CONTAINS a tool name is not that tool
    assert _called_in("_observe(x)", names) == set()
    # …and the plural verb is not a call of the singular one
    assert _called_in("get_specialist_docs(spec_ids=[…])", names) == {
        "get_specialist_docs"}


def test_every_tool_a_roles_own_guides_instruct_it_to_call_is_in_its_toolset():
    """THE d17 INVARIANT, over all six role surfaces.

    Exact equality with the backlog table: a NEW gap fails here, and so does a
    FIXED gap still listed. `(planner, get_recipe_digest)` is absent from the
    table, so deleting it from _PLANNER turns this RED — which is the whole
    point (a test that still passes with the defect present is not a test)."""
    found = _gaps()
    known = set(KNOWN_GUIDE_TOOLSET_GAPS)

    new = {k: v for k, v in found.items() if k not in known}
    assert not new, (
        "a role's own guides instruct it to CALL a tool that is NOT in its "
        "toolset. Under EDP_ROLE_SCOPE=enforce that call is refused and the "
        "guide cannot be followed. Either add the tool to the role's derived "
        "floor in tools/roles.py (and move its ceiling, with a rationale), or "
        "fix the guide. New gaps:\n" + "\n".join(
            f"  ({role}, {tool}) instructed by {', '.join(docs)}"
            for (role, tool), docs in sorted(new.items())))

    fixed = known - set(found)
    assert not fixed, (
        "these gaps are recorded in KNOWN_GUIDE_TOOLSET_GAPS but no longer "
        "exist — remove them from the table so the backlog stays honest: "
        f"{sorted(fixed)}")


def test_the_backlog_table_documents_a_reason_for_every_entry():
    """A bare allowlist becomes a dumping ground; a reason keeps it a backlog."""
    for key, reason in KNOWN_GUIDE_TOOLSET_GAPS.items():
        assert len(reason) > 40, f"{key} needs a real reason, got {reason!r}"
    # and every entry names a real role + a real registered tool
    for role, tool in KNOWN_GUIDE_TOOLSET_GAPS:
        assert role in ROLE_TOOLSETS
        assert tool in _all_names() | {RECORD_CONTEXT}


# ════════════════════════════════════════════════════════════════════════
# (7) s25/a4 — THE WIDENED CORPUS, AND THE FAIL-OPEN ROLES
# ════════════════════════════════════════════════════════════════════════
def test_widened_corpus_reaches_transitive_and_declared_guides():
    """The corpus bug a1 found (blocker 5): `_role_docs` walked ONE hop, so a
    guide loaded BY a guide was scanned for nobody. Pin every doc the widening
    was FOR — if a future exclusion rule sweeps one back out, the gate goes
    quietly blind again and this fails."""
    planner = {p.name for p in _role_docs("planner")}
    # transitive: the shape guides hang off planner-phase-author.md, never off
    # the command file — the one-hop rule never saw them.
    assert "planner-shape-linear-build.md" in planner, planner
    assert "planner-shape-poc-iterate-build.md" in planner, planner
    # declared: two hops out, behind a SHARED reference doc.
    assert "environment-discovery.md" in planner, planner

    # transitive: neuron-phase-*.md hang off orchestrator-launch.md.
    neuron = {p.name for p in _role_docs("neuron")}
    assert {"orchestrator-launch.md", "neuron-phase-c.md"} <= neuron, neuron

    # declared: specialist.md calls get_guide ZERO times, so its own standing
    # doctrine was unreachable. This is what exposed the eighth gap.
    specialist = {p.name for p in _role_docs("specialist")}
    assert "specialist-training.md" in specialist, specialist

    # transitive: worker.md loads coding-standards for ordinary (non-spec) work.
    assert "coding-standards.md" in {p.name for p in _role_docs("worker")}


def test_shared_reference_docs_are_not_descended_through():
    """The subtlety that made the first widening WRONG. A role-neutral doc
    CATALOGUES the guide space (architecture-vocabulary.md:231 names
    `get_guide("orchestrator-launch")` in a table row; :220 points at
    environment-discovery.md). Descending through it makes every guide reachable
    from every role that loads the vocabulary, tipping the neuron's OWN phase
    guides past the >=2 shared threshold and OUT of its corpus — a gate blinder
    than the one-hop rule it replaced. A catalogue entry is not a load."""
    shared = _shared_guides()
    # the role-neutral docs, and ONLY those, are shared. v7 bootdocs: terse
    # joined in the Phase-5 instruction diet (2026-07-30): every CRAFT command
    # file (worker/reviewer/specialist) loads it at boot, so it is by
    # construction addressed to no single role.
    assert shared == {"architecture-vocabulary", "reactive-streams",
                      "channel-coordination", "loop-and-heartbeat", "verification-craft"}, sorted(shared)
    # orchestrator-launch is reachable from architecture-vocabulary's TABLE,
    # but it belongs to the neuron alone and must stay in the neuron's corpus.
    assert "orchestrator-launch" not in shared
    assert "orchestrator-launch" in _reachable_guides("neuron")
    assert "orchestrator-launch" not in _reachable_guides("worker")
    # and the vocabulary's other catalogue target does not leak into the worker
    assert "environment-discovery" not in _reachable_guides("worker")


def test_every_guide_is_either_scanned_shared_or_explicitly_unattributed():
    """Coverage is ASSERTED, not assumed. A new guide that no role reaches is
    scanned by nobody, and its silence would read as 'no gaps'. Force a decision
    at the moment it is added."""
    scanned: set[str] = set()
    for role in ROLE_COMMAND_FILE:
        scanned |= {p.stem for p in _role_docs(role)}
    on_disk = {p.stem for p in GUIDES_DIR.glob("*.md")}
    unattributed = on_disk - scanned - _shared_guides()
    assert unattributed == set(UNSCANNED_GUIDES), (
        "a guide is attributed to no role and is not declared role-neutral. "
        "Decide which role it governs (add it to EXTRA_ROLE_GUIDES) or record "
        "why nobody scans it (UNSCANNED_GUIDES).\n"
        f"  unscanned but undeclared: {sorted(unattributed - set(UNSCANNED_GUIDES))}\n"
        f"  declared but now scanned: {sorted(set(UNSCANNED_GUIDES) - unattributed)}")
    for guide, reason in UNSCANNED_GUIDES.items():
        assert len(reason) > 30, f"{guide} needs a real reason, got {reason!r}"


def test_unscanned_guides_are_still_read_by_the_unregistered_tool_gate():
    """s26/a2 — THE TIGHTENING, pinned from this side too.

    `UNSCANNED_GUIDES` exempts a guide from ROLE attribution. It must never
    exempt it from TOOL-NAME validation: a guide parked here that CALLS a verb
    which is not a registered tool is exactly the gap the hatch could hide, and
    `_gaps()` cannot see it (its candidates come from the registry, so a
    nonexistent name is invisible BY CONSTRUCTION — d68/C9).

    Mutation-proved: drop a guide into docs/guides/ that calls a nonexistent
    verb and declare it here with a long reason. THIS test goes RED and names
    the file, where `test_every_tool_a_roles_own_guides_instruct_it_to_call_is_
    in_its_toolset` stays GREEN. (Imported inside the function:
    test_s26_guide_tool_names imports THIS module, so a module-level import back
    would be a cycle.)"""
    from test_s26_guide_tool_names import (
        live_shell_files,
        unregistered_call_sites,
    )

    covered = {p.stem for p in live_shell_files()}
    escaped = set(UNSCANNED_GUIDES) - covered
    assert not escaped, (
        "guide(s) declared unattributed AND outside the unregistered-tool "
        f"gate — the escape hatch is back: {sorted(escaped)}")

    hatch_files = {f"{g}.md" for g in UNSCANNED_GUIDES}
    in_hatch = {
        name: [s for s in sites if s.rsplit("/", 1)[-1].split(":")[0] in hatch_files]
        for name, sites in unregistered_call_sites().items()
    }
    offending = {n: s for n, s in in_hatch.items() if s}
    assert not offending, (
        "a guide exempted from role attribution CALLS a verb that is not a "
        "registered tool. The exemption buys freedom from role attribution, "
        "never from tool-name validation:\n" + "\n".join(
            f"  {n}(...) at {', '.join(s)}" for n, s in sorted(offending.items())))


def test_assemble_ruleset_is_a_read_verb_not_an_authoring_verb():
    """s25/a4, neuron ruling d62(a). SPECIALIST_ONLY is defined by AUTHORING
    (o7); `assemble_ruleset` authors nothing (AssembleRuleset is
    `idempotent = True`, "Pure lookup, byte-stable per inputs", and its only
    store access is `ctx.specs.load`). Under enforce, no worker could assemble
    the ruleset for a `concerns=[X]` action.

    THIS assertion — not the class-guard test — is what guards the worker and
    reviewer grants. Measured: removing `assemble_ruleset` from `_WORKER` or
    `_REVIEWER` leaves the class-guard test GREEN, because neither worker.md nor
    reviewer.md names it in CALL FORM (planner-phase-author.md describes the
    WORKER's call, and the matcher attributes a call site to the guide's own
    role; neuron-phase-e.md:58 writes it as a bare mention). A grant no test
    reacts to is the green-suite-guarding-nothing disease, so the grant is
    pinned here explicitly."""
    assert "assemble_ruleset" not in SPECIALIST_ONLY, (
        "assemble_ruleset writes nothing — it does not belong in the "
        "spec-AUTHORING carve-out")
    for role in ("worker", "reviewer", "specialist"):
        assert "assemble_ruleset" in ROLE_TOOLSETS[role], role
    # the specialist's grant is EXPLICIT, not inherited through | SPECIALIST_ONLY
    assert "assemble_ruleset" in ROLE_TOOLSETS["specialist"] - SPECIALIST_ONLY
    # Phase 3b (2026-07-30): _NEURON is a POSITIVE list now and deliberately
    # does NOT hold assemble_ruleset — composing a ruleset is CRAFT-role work
    # (worker/reviewer/specialist); the neuron delegates, it never assembles.
    # This inverted: the old derived surface inherited the verb automatically.
    assert "assemble_ruleset" not in ROLE_TOOLSETS["neuron"]
    # o7 still holds: the authoring verbs remain specialist-exclusive
    assert SPECIALIST_ONLY == {"add_spec_entry", "update_specialist",
                               "write_specialist_doc", "create_specialization"}
    for role in ("worker", "reviewer", "planner", "neuron", "curiosity"):
        assert SPECIALIST_ONLY.isdisjoint(ROLE_TOOLSETS[role]), role


def _pool_spawned_roles() -> set[str]:
    """The role strings `clients/http_pool.py` actually sends to the pool,
    read FROM ITS SOURCE — never re-spelled here. Each `self._spawn(` call
    passes the role as its first positional argument, a quoted literal.

    (str.find, not `re`: coding-standard #7 forbids regex without user
    approval, and this mirrors `_guides_loaded_by` above.)"""
    src = (REPO_ROOT / "src" / "edp_claude" / "clients" / "http_pool.py"
           ).read_text(encoding="utf-8")
    token = "self._spawn("
    roles: set[str] = set()
    start = 0
    while (i := src.find(token, start)) >= 0:
        start = i + len(token)
        j = start
        while j < len(src) and src[j] in " \t\r\n":
            j += 1
        if j < len(src) and src[j] in "\"'":
            quote = src[j]
            end = src.find(quote, j + 1)
            if end > 0:
                roles.add(src[j + 1:end])
    return roles


def test_every_pool_spawned_role_has_a_toolset():
    """a1 blocker 4 + blocker 6 — the three-role FAIL-OPEN over-grant, and the
    hyphen/underscore key trap that would have made the fix silently do nothing.

    `toolset_for_role` returns None for an unknown role and `build_mcp` then
    registers the FULL 86-tool registry — in BOTH warn and enforce. The pool
    stamps EDP_ROLE from the string http_pool sends, and three of those strings
    had no ROLE_TOOLSETS row, so those shells kept `close_recipe`,
    `delete_object`, `pool_spawn_planner` and the o7 SPECIALIST_ONLY verbs.

    THE TRAP: the derived doc heads these roles with HYPHENS
    (`## GOAL-KEEPER / PATTERN-OBSERVER`) and their activators are
    `/goal-keeper` / `/pattern-observer`, but EDP_ROLE is stamped with
    UNDERSCORES. A row keyed "goal-keeper" would never match and the fix would
    look landed while doing nothing. Deriving the keys from http_pool.py's
    source is what makes that unfalsifiable-by-typo."""
    sent = _pool_spawned_roles()
    # parser sanity — a silently-empty parse must not vacuously pass
    assert {"worker", "planner", "reviewer"} <= sent, sent
    missing = sent - set(ROLE_TOOLSETS)
    assert not missing, (
        f"http_pool.py spawns {sorted(missing)} but tools/roles.py has no "
        "ROLE_TOOLSETS row, so toolset_for_role returns None and build_mcp "
        "FAILS OPEN to the full registry for those shells")
    # the underscore form specifically — the trap, pinned
    assert "curiosity" in sent, sent
    assert toolset_for_role("curiosity") is not None
    assert CRUD_OBJECT_SCOPE["curiosity"] == frozenset(), (
        "curiosity must be read-only over the generic object-CRUD verbs")
    # goal_keeper / pattern_observer are DEAD (owner ruling 2026-08-04):
    # the pool no longer spawns them and no row may return for any key form.
    for dead in ("goal_keeper", "goal-keeper",
                 "pattern_observer", "pattern-observer"):
        assert dead not in sent, dead
        assert toolset_for_role(dead) is None, dead


def test_advisory_role_is_read_only_and_names_only_registered_tools():
    """The advisory row grants no authoring, no spawn, no mutation. And every
    name resolves: `build_mcp` fails CLOSED on drift (mcp_server.py:150-158) —
    a row naming an unregistered verb would take the MCP server down at startup
    for every shell. (goal_keeper / pattern_observer rows deleted with their
    dead roles, owner ruling 2026-08-04.)"""
    all_names = _all_names() | {RECORD_CONTEXT}
    forbidden = {"close_recipe", "suspend_recipe", "resume_recipe",
                 "delete_object", "create_object", "update_object",
                 "pool_spawn_planner", "pool_spawn_worker", "record_recipe"}
    surface = ROLE_TOOLSETS["curiosity"]
    assert surface <= all_names, sorted(surface - all_names)
    assert surface.isdisjoint(forbidden), sorted(surface & forbidden)
    assert surface.isdisjoint(SPECIALIST_ONLY)
    assert "pool_close_self" in surface
    assert "pattern_observer_analyze" not in all_names
