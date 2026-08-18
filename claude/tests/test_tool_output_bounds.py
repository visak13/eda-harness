"""s17 a4 GUARDRAIL — tool-output bounds hold BY CONSTRUCTION at scale.

The a2/a3 work made the hot-path emitters (`recipe_context`, `get_recipe_digest`)
and the generic read/list surface (`read_object(detail='digest')`,
`query_objects`) bounded regardless of how many decisions/actions a recipe or
plan accumulates. This file is the regression tripwire that keeps them that way.

WHAT THIS LOCKS DOWN
  1. GROWTH BOUND (not a fixed ceiling): a recipe with 5000 active decisions
     pushes a `recipe_context` no bigger than a 50-decision one + WINDOW_SLACK.
     A monotonic-growth assertion catches reintroduced O(n) full-text bloat that
     a single static ceiling would silently permit to grow up to the ceiling.
  2. `get_recipe_digest` — the id+title `index` AND the digest-form
     `load_bearing` list each stay <= WINDOW at 5000 decisions, while `count` /
     `load_bearing_count` still report the true totals.
  3. `read_object(detail='digest')` — the projected `decisions` rows stay
     <= WINDOW at 5000 decisions.
  4. `query_objects('action')` — a 500-action plan returns a slice <= the limit
     (default WINDOW), with `count` reporting the full 500.
  5. P1 DEFAULT-UNCHANGED GUARANTEE — `read_object(detail='full')` still returns
     ALL rows (5000 decisions / 500 actions), and the count-first `recap`
     (`decisions=N`) is still carried by BOTH `recipe_context` and
     `get_recipe_digest`, so a compacted/fresh shell self-detects the gap.

WHY A GROWTH BOUND. A fixed ceiling (`size <= BUDGET`) passes any payload under
the budget — including one that has quietly regrown to O(n) but not yet crossed
the line. Comparing the 5000-decision payload to the 50-decision one instead
pins the *marginal* cost of extra decisions to ~zero (only larger count digits),
so any reintroduced per-decision full-text dump fails immediately, long before a
static ceiling would.

Deterministic, no LLM (principle-6): every fixture is code-built and every
assertion is an exact size/count comparison.

ENV DISCIPLINE (d7/d8). This file touches recipe/FSM internals; a worker shell
leaks EDP_ROLE/EDP_HANDLE into pytest, which can skew lineage/role-sensitive
paths. conftest's autouse `_clear_leaked_shell_env` already pops them for the
whole suite; the module-local autouse fixture below repeats the clear INSIDE the
interpreter (monkeypatch.delenv — never an `env` prefix, which returns exit 127
= a false-fail in the verify shell) so this file is robust even run in isolation.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from edp_contracts import BrokerMessage, ToolOk

from edp_claude.fsm.recipe_fsm import recipe_context
from edp_claude.schemas import NeuronRecord, Plan, Recipe
from edp_claude.tools._bounds import (
    BUDGET,
    INBOX_MAX_BYTES,
    WINDOW,
    approx_tokens,
    assert_bounded,
)

# The a2/a3 emitters window every unbounded list to a fixed WINDOW. Between a
# 50-decision and a 5000-decision recipe the ONLY legitimate growth is the
# count-first bookkeeping (larger `decisions=N` digits, the `count`/`superseded`
# integers) — a handful of characters. WINDOW_SLACK is that fixed-overhead
# headroom in approx-tokens: generous enough to never flake on digit growth, yet
# orders of magnitude below the ~25k tokens a reintroduced 5000-decision
# full-text dump would add, so the growth bound still trips on real bloat.
WINDOW_SLACK = 64


# ── env discipline (d7/d8) — belt-and-suspenders over conftest's autouse ──────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE"):
        monkeypatch.delenv(var, raising=False)


# ── fixtures: extend _recipe_with_decisions to arbitrary scale ────────────────
# The base builder is the same one the a2 pointer tests use. Import it so this
# file EXTENDS (not forks) that helper; fall back to a byte-identical local copy
# so the guardrail is self-contained even under an importlib collection mode
# where sibling test modules are not importable by bare name.
try:  # pragma: no cover - import-mode dependent
    from test_s17_rpb_decisions_pointer import _recipe_with_decisions
except Exception:  # pragma: no cover
    def _recipe_with_decisions(texts, *, state="executing"):
        decisions = [
            {"id": f"d{i+1}", "text": t, "rationale": "", "by": "user",
             "at": datetime.now(timezone.utc).isoformat(), "load_bearing": True}
            for i, t in enumerate(texts)
        ]
        return Recipe.model_validate(dict(
            recipe_id="recipe-rpb", user_goal_verbatim="g", domain="generic",
            state=state,
            comprehension={"branches": [],
                           "expected_outcomes": [{"id": "o1", "description": "d",
                                                  "verification": "v"}],
                           "curiosity_cleared": True},
            steps=[{"step_id": "s1", "kind": "work", "description": "d",
                    "status": "pending", "depends_on": [],
                    "execution": "spawn_planner"}],
            context={"decisions": decisions},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))


def _recipe_scaled(n, *, recipe_id="recipe-bounds"):
    """A recipe with `n` active load-bearing decisions, built on the shared
    _recipe_with_decisions helper (only the recipe_id is overridden so several
    scaled fixtures can coexist in one store)."""
    r = _recipe_with_decisions([f"decision {i} body" for i in range(n)])
    return r.model_copy(update={"recipe_id": recipe_id})


def _plan_with_actions(n, *, plan_id="plan-bounds", recipe_id="recipe-bounds"):
    """A dispatching plan carrying `n` pending actions (minimal but schema-valid
    rows) — the fixture for the query_objects('action') window bound."""
    return Plan.model_validate(dict(
        plan_id=plan_id, recipe_id=recipe_id, recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": f"a{i}", "description": f"action {i}",
                  "status": "pending", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "artifact", "expected": "exists"}}
                 for i in range(n)],
        context={},
    ))


# ════════════════════════════════════════════════════════════════════════════
# 1. recipe_context — GROWTH BOUND (monotonic, not a static ceiling)
# ════════════════════════════════════════════════════════════════════════════
def test_recipe_context_growth_bounded_50_to_5000():
    """The per-tick push for a 5000-decision recipe is no larger than for a
    50-decision one plus a fixed WINDOW_SLACK — the marginal cost of 4950 extra
    decisions is ~zero. A reintroduced O(n) full-text dump would blow this by
    thousands of tokens."""
    small = approx_tokens(recipe_context(_recipe_scaled(50, recipe_id="r-50")))
    big = approx_tokens(recipe_context(_recipe_scaled(5000, recipe_id="r-5000")))

    assert big <= small + WINDOW_SLACK, (
        f"recipe_context grew {big - small} approx-tokens from 50→5000 "
        f"decisions (small={small}, big={big}, slack={WINDOW_SLACK}) — a "
        "windowed pointer must be ~O(1) in decision count; this looks like a "
        "reintroduced per-decision full-text dump")
    # and the absolute payload is comfortably inside the shared token budget.
    assert_bounded(recipe_context(_recipe_scaled(5000, recipe_id="r-5000b")))


def test_recipe_context_window_is_capped_and_recap_reports_true_count():
    """At 5000 decisions the pointer's id+title index and load-bearing id list
    are each capped to WINDOW, while the recap still carries the TRUE count so a
    terse/compacted reader self-detects."""
    ctx = recipe_context(_recipe_scaled(5000, recipe_id="r-5000c"))
    ad = ctx["active_decisions"]
    assert len(ad["index"]) <= WINDOW
    assert len(ad["load_bearing_ids"]) <= WINDOW
    assert ad["count"] == 5000                     # true total still reported
    assert ad["cursor"] is not None                # more rows exist past window
    assert "decisions=5000" in ctx["recap"]        # un-missable self-detect flag


# ════════════════════════════════════════════════════════════════════════════
# 2. get_recipe_digest — index + load_bearing bounded at 5000 decisions
# ════════════════════════════════════════════════════════════════════════════
async def test_get_recipe_digest_index_and_load_bearing_bounded(env):
    r = _recipe_scaled(5000, recipe_id="r-digest-5000")
    env.ctx.recipes.save(r)

    res = await env.call("get_recipe_digest", recipe_id=r.recipe_id)
    assert isinstance(res, ToolOk), res
    data = res.data if isinstance(res.data, dict) else res.data.model_dump(
        mode="json")
    ad = data["active_decisions"]

    # bounded BY CONSTRUCTION — neither list grows with the decision count
    assert len(ad["index"]) <= WINDOW, len(ad["index"])
    assert len(ad["load_bearing"]) <= WINDOW, len(ad["load_bearing"])
    # ...but the true totals are still reported (count-first contract)
    assert ad["count"] == 5000
    assert ad["load_bearing_count"] == 5000
    # a non-null cursor tells the reader more rows exist past the window
    assert ad["index_cursor"] is not None
    assert ad["load_bearing_cursor"] is not None
    # the recap still carries the un-missable count for self-detection
    assert "decisions=5000" in data["recap"]["recap"]


# ════════════════════════════════════════════════════════════════════════════
# 3. read_object(detail='digest') — decision rows bounded at 5000 decisions
# ════════════════════════════════════════════════════════════════════════════
async def test_read_object_digest_decisions_bounded(env):
    r = _recipe_scaled(5000, recipe_id="r-rodigest-5000")
    env.ctx.recipes.save(r)

    got = await env.call("read_object", type="recipe",
                         ids={"recipe_id": r.recipe_id}, detail="digest")
    assert isinstance(got, ToolOk), got
    obj = got.data["object"]
    assert obj["_detail"] == "digest"
    decs = obj["context"]["decisions"]
    assert len(decs) <= WINDOW, len(decs)              # windowed by construction
    assert obj["context"]["decisions_count"] == 5000   # true total reported
    assert obj["context"]["decisions_cursor"] is not None


# ════════════════════════════════════════════════════════════════════════════
# 4. query_objects('action') — a 500-action plan windows to <= limit
# ════════════════════════════════════════════════════════════════════════════
async def test_query_objects_action_windowed_to_limit(env):
    plan = _plan_with_actions(500, plan_id="p-bounds-500")
    env.ctx.plans.save(plan)

    got = await env.call("query_objects", type="action",
                         scope={"plan_id": plan.plan_id})
    assert isinstance(got, ToolOk), got
    data = got.data if isinstance(got.data, dict) else got.data.model_dump(
        mode="json")
    assert len(data["objects"]) <= WINDOW, len(data["objects"])  # bounded slice
    assert data["count"] == 500                                  # full total
    assert data["cursor"] is not None                            # more to page

    # an explicit larger limit still honors its own bound (limit, not WINDOW).
    wide = await env.call("query_objects", type="action",
                          scope={"plan_id": plan.plan_id}, limit=100)
    wdata = wide.data if isinstance(wide.data, dict) else wide.data.model_dump(
        mode="json")
    assert len(wdata["objects"]) == 100
    assert wdata["count"] == 500


# ════════════════════════════════════════════════════════════════════════════
# 5. P1 DEFAULT-UNCHANGED — full detail returns ALL rows; recap self-detect
# ════════════════════════════════════════════════════════════════════════════
async def test_read_object_full_returns_all_5000_decisions(env):
    """Context-diet Phase 1d: a full read past 3x BUDGET degrades to the
    digest + a loud oversize note (a 5000-decision hydration blows a whole
    context window); the explicit confirm_oversize override still hands back
    every row — full fidelity stays one (deliberate) call away."""
    r = _recipe_scaled(5000, recipe_id="r-full-5000")
    env.ctx.recipes.save(r)

    got = await env.call("read_object", type="recipe",
                         ids={"recipe_id": r.recipe_id})   # detail defaults full
    assert isinstance(got, ToolOk), got
    obj = got.data["object"]
    assert obj["_detail"] == "digest" and obj["oversize"] is True
    assert "confirm_oversize" in obj["full_available_via"]

    got = await env.call("read_object", type="recipe",
                         ids={"recipe_id": r.recipe_id,
                              "confirm_oversize": True})
    obj = got.data["object"]
    assert "_detail" not in obj                             # NOT a digest
    assert len(obj["context"]["decisions"]) == 5000         # ALL rows returned


async def test_query_objects_action_full_fidelity_one_page_away(env):
    """Paging with an explicit limit spanning the full match returns all 500
    actions — the count-first window never loses data, it only defers it."""
    plan = _plan_with_actions(500, plan_id="p-full-500")
    env.ctx.plans.save(plan)

    got = await env.call("query_objects", type="action",
                         scope={"plan_id": plan.plan_id}, limit=500)
    data = got.data if isinstance(got.data, dict) else got.data.model_dump(
        mode="json")
    assert len(data["objects"]) == 500
    assert data["count"] == 500
    assert data["cursor"] is None                           # reached the end


def test_recap_decisions_count_present_in_both_emitters():
    """The count-first `decisions=N` self-detect flag is carried by BOTH the
    per-tick push AND the digest packet, so neither surface can silently drop
    the pointer that lets a compacted shell notice its context gap. (The digest
    half is asserted live in test 2; here we pin the recipe_context half at a
    distinct scale to keep the guarantee explicit on its own.)"""
    ctx = recipe_context(_recipe_scaled(500, recipe_id="r-recap-500"))
    assert "decisions=500" in ctx["recap"]


# ════════════════════════════════════════════════════════════════════════════
# s17 a7 — WHOLE-TOOL-LAYER SWEEP: the NON-recipe-size offenders.
#
# #18 has TWO output classes (neuron ruling, s17 a7):
#   (a) LIST outputs (one row per fact/neuron/message/open-recipe) MUST be a
#       bounded window+cursor, pull-on-demand.
#   (b) CONTENT / GROUNDING-DELIVERY outputs (a compiled doc / assembled
#       ruleset / spec dump the consumer applies IN FULL) MUST NOT be truncated
#       at delivery — they carry a NON-truncating {approx_tokens, oversize}
#       signal and are bounded at AUTHOR time instead.
# ════════════════════════════════════════════════════════════════════════════
def _data(res):
    assert isinstance(res, ToolOk), res
    return res.data if isinstance(res.data, dict) else res.data.model_dump(
        mode="json")


# ── (a) LIST tools — hard window + cursor ─────────────────────────────────────
async def test_recall_results_windowed(env):
    """recall fans out over global+recipe+domain, so the merged result set
    grows with the fact store — it must window to <=limit with a count-first
    cursor, and page the full set with a wider limit."""
    n = WINDOW * 2 + 5
    for i in range(n):
        await env.ctx.memory.remember(
            {"text": f"zzq bounded recall fact {i}", "durable": True},
            "generic", scope="global")

    got = _data(await env.call("recall", query="zzq"))
    assert len(got["results"]) <= WINDOW                 # bounded slice
    assert got["count"] >= WINDOW + 1                     # true total > a window
    assert got["cursor"] is not None                     # more to page

    wide = _data(await env.call("recall", query="zzq", limit=n + 100))
    assert len(wide["results"]) == wide["count"]          # full fidelity one page
    assert wide["cursor"] is None                         # reached the end


async def test_check_specialist_decay_stale_windowed(env):
    """The `stale` report is one row per neuron → windowed. `checked` and
    `count` still report the true totals; a wider limit pages them all."""
    now = datetime.now(timezone.utc)
    n = WINDOW + 10
    for i in range(n):
        env.ctx.neurons.create(NeuronRecord(
            neuron_id=f"stale-{i}", name=f"stale-{i}", description="d",
            category="domain", status="stable",
            created_at=now, updated_at=now,
            trained_at=now - timedelta(days=200)))

    got = _data(await env.call("check_specialist_decay", ttl_days=90))
    assert len(got["stale"]) <= WINDOW                   # bounded slice
    assert got["count"] == n                              # true stale total
    assert got["checked"] == n                            # all were scanned
    assert got["cursor"] is not None

    wide = _data(await env.call("check_specialist_decay",
                                ttl_days=90, limit=n + 100))
    assert len(wide["stale"]) == n and wide["cursor"] is None


async def test_read_object_memory_bounded_with_widen_escape(env):
    """read_object('memory') is a raw dump (a LIST) — bounded to WINDOW by
    default, with ids={'limit': N} as the full-fidelity-one-read escape."""
    n = WINDOW * 2
    for i in range(n):
        await env.ctx.memory.remember(
            {"text": f"zzq mem dump {i}", "durable": True},
            "generic", scope="global")

    default = _data(await env.call("read_object", type="memory",
                                   ids={}))["object"]
    assert len(default) <= WINDOW                         # bounded by default
    widened = _data(await env.call("read_object", type="memory",
                                   ids={"limit": n + 100}))["object"]
    assert len(widened) == n                              # escape returns all


async def test_check_inbox_byte_budget_is_default(env):
    """check_inbox applies INBOX_MAX_BYTES BY DEFAULT (no opt-in): a big
    retained inbox no longer dumps every full body — bodies past the budget
    become compact rows and the note flags the default budget. Full bodies
    stay one read_object('message') away."""
    rcpt = "plan-a7:act-1"
    big = "x" * 1500                                       # ~1.5 KB body each
    n = (INBOX_MAX_BYTES // 1500) + 20                     # comfortably over
    for i in range(n):
        await env.ctx.broker.send(BrokerMessage.model_validate({
            "msg_id": str(uuid.uuid4()),
            "ts": datetime.now(timezone.utc),
            "from": "sender", "to": rcpt, "kind": "answer",
            "body": {"i": i, "blob": big}}))

    got = _data(await env.call("check_inbox", handle=rcpt))
    msgs = got["messages"]
    # at least one message past the budget is a COMPACT ROW (no full body)
    rows = [x for x in msgs if "body" not in x and "body_bytes" in x]
    fulls = [x for x in msgs if "body" in x]
    assert rows, "default byte-budget did not summarize any oversize inbox"
    assert fulls, "budget must keep at least the oldest full body"
    assert got["note"] and "default inbox byte-budget" in got["note"]


async def test_resolve_recipe_open_recipes_windowed(env):
    """resolve_recipe.open_recipes is one row per OPEN recipe → windowed to
    WINDOW with the true total in open_recipes_count."""
    from edp_claude.schemas import Recipe as _R
    now = datetime.now(timezone.utc)
    n = WINDOW + 8
    for i in range(n):
        env.ctx.recipes.save(_R.model_validate(dict(
            recipe_id=f"open-{i}", user_goal_verbatim=f"goal {i}",
            domain="generic", state="executing",
            comprehension={"branches": [], "expected_outcomes": [
                {"id": "o1", "description": "d", "verification": "v"}],
                "curiosity_cleared": True},
            steps=[{"step_id": "s1", "kind": "work", "description": "d",
                    "status": "pending", "depends_on": [],
                    "execution": "spawn_planner"}],
            context={}, created_at=now, updated_at=now)))

    got = _data(await env.call("resolve_recipe", goal="something unmatched xyz"))
    assert len(got["open_recipes"]) <= WINDOW
    assert got["open_recipes_count"] == n                 # true total reported


# ── (b) CONTENT-delivery tools — NON-truncating guard, never windowed ─────────
async def _make_spec(env, name="Springy", subject="spring", desc="spring boot"):
    _data(await env.call("ensure_universal"))
    d = _data(await env.call("create_specialization",
                             name=name, subject=subject, description=desc))
    return d["spec_id"], d["neuron_id"]


async def test_content_tools_carry_nontruncating_guard(env):
    """get_specialist_doc / get_specialist_docs / get_specialization /
    assemble_ruleset / consult_specialist deliver an artifact applied IN FULL,
    so they carry a {approx_tokens, oversize} signal but never drop content."""
    sid, nid = await _make_spec(env)
    doc = "# compiled\n" + ("a real [required] rule line.\n" * 50)
    wrote = _data(await env.call("write_specialist_doc",
                                 spec_id=sid, content=doc))
    assert wrote["approx_tokens"] == approx_tokens(doc)
    assert wrote["oversize"] is False

    # (v7 P0 deleted the singular get_specialist_doc; the plural below is
    # the one live doc-delivery surface and carries the same guard.)
    docs = _data(await env.call("get_specialist_docs", spec_ids=[sid]))
    # F37#6: the provenance banner frames the grounding; the doc itself
    # still rides in full, never truncated.
    assert docs["grounding"].startswith("<!-- SPECIALIST GROUNDING")
    assert docs["grounding"].endswith(doc)
    assert docs["approx_tokens"] == approx_tokens(docs["grounding"])

    spec = _data(await env.call("get_specialization", spec_id=sid))
    assert spec["spec"] is not None and spec["approx_tokens"] is not None

    rules = _data(await env.call("assemble_ruleset", spec_id=sid))
    assert "approx_tokens" in rules and "oversize" in rules

    con = _data(await env.call("consult_specialist", specialist_id=nid,
                               query="how to build a controller"))
    assert con["knowledge"] and con["approx_tokens"] is not None


async def test_oversize_content_is_flagged_but_never_truncated(env):
    """The class-(b) invariant: even a doc OVER budget is delivered IN FULL —
    oversize=True is a review signal, not a truncation. Hard-truncating here
    would silently drop [required] rules and break the specialist worker."""
    sid, _ = await _make_spec(env, name="Big", subject="big", desc="big")
    huge = "L" * (BUDGET * 4 + 5000)                       # comfortably over
    wrote = _data(await env.call("write_specialist_doc",
                                 spec_id=sid, content=huge))
    assert wrote["oversize"] is True                       # author-time flag
    assert wrote["bytes"] == len(huge)

    docs = _data(await env.call("get_specialist_docs", spec_ids=[sid]))
    assert docs["grounding"].endswith(huge)               # bundler: full too
    assert docs["oversize"] is True
