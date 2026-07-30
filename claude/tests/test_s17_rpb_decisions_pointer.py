"""s17 RP-B — next_action FSM-focus + decisions POINTER (no per-tick dump).

Locks the flagship autonomy fix: `recipe_context` (pushed on every next_action)
no longer re-embeds the full `context.decisions` text. It ships an
`active_decisions` POINTER (count + id+title index + on-demand load), and the
FULL text is fetched once, on demand, via read_object('recipe'). Covers:
  1. steady-state: the push carries the index, NOT the bodies;
  2. FSM-advance equivalence: the next legal move is unchanged (the push is
     attached AFTER the move is decided — decisions never feed the transition);
  3. post-compact re-ground: a fresh shell detects the gap from the index/count
     and the on-demand read returns text BYTE-IDENTICAL to the old inline dump.
"""
from datetime import datetime, timezone

from edp_contracts import ToolOk

from edp_claude.fsm.recipe_fsm import (
    recipe_context, recipe_next_action, _decision_title,
)
from edp_claude.schemas import Recipe


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


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


def test_rpb_steady_state_ships_index_not_bodies():
    bodies = [
        "SCOPE LOCKED (curiosity converged): keep-only-agentic, latency, s10-s17.",
        "MiniLM is the settled embedder; never nomic — " + ("x" * 2000),
        "LATENCY DIRECTION — pin phi4-mini resident, keep 3 hops.",
    ]
    ctx = recipe_context(_recipe_with_decisions(bodies))

    # pointer present and correct
    ad = ctx["active_decisions"]
    assert ad["count"] == 3
    assert [e["id"] for e in ad["index"]] == ["d1", "d2", "d3"]
    # Phase 1d: the load hint steers to the CHEAP re-ground path (digest +
    # targeted search), never to a full-recipe hydration.
    assert "search_context" in ad["load"]
    assert "get_recipe_digest" in ad["load"]

    # the FULL bodies are NOT anywhere in the push (the pollution is gone)
    import json
    blob = json.dumps(ctx)
    assert "x" * 2000 not in blob, "full decision body leaked into the push"
    # decisions key removed from prior (no full-text dump)
    assert "decisions" not in ctx["prior"]
    # but the title (short handle) IS shipped so a steady-state shell recognises
    assert any("never nomic" in e["title"] for e in ad["index"])
    # recap carries the un-missable count for self-detection
    assert "decisions=3" in ctx["recap"]


def test_rpb_title_is_deterministic_and_bounded():
    assert _decision_title("MiniLM is the settled embedder; never nomic") \
        == "MiniLM is the settled embedder; never nomic"
    # clause boundary trims at the first separator
    assert _decision_title("SCOPE LOCKED. everything after is dropped") \
        == "SCOPE LOCKED"
    # long single-token line is capped with an ellipsis
    long = "Z" * 200
    out = _decision_title(long)
    assert len(out) <= 91 and out.endswith("…")
    # deterministic: same input -> same output
    assert _decision_title(long) == out


def test_rpb_fsm_move_unchanged_by_pointer():
    """Behavior-equivalence: the FSM next-move is decided BEFORE the context is
    attached, so swapping the dump for a pointer cannot change the transition.
    Two recipes identical except decision COUNT yield the same move."""
    few = _recipe_with_decisions(["only one decision"])
    many = _recipe_with_decisions([f"decision {i}" for i in range(30)])
    m_few = recipe_next_action(few)
    m_many = recipe_next_action(many)
    k = lambda m: (m.kind.value if hasattr(m.kind, "value") else m.kind)
    assert k(m_few) == k(m_many), (k(m_few), k(m_many))
    # and the move kind is stable across repeated calls (deterministic)
    assert k(recipe_next_action(few)) == k(m_few)


async def test_get_recipe_digest_active_decisions_bounded_at_scale(env):
    """s17 a2 — get_recipe_digest bounds active_decisions BY CONSTRUCTION.

    On a recipe with FAR more than WINDOW active load-bearing decisions, both
    the id+title `index` and the digest-form `load_bearing` list stay <= WINDOW
    (O(1) in decision count), while `count` / `load_bearing_count` still report
    the true totals and the cursors flag that more rows exist past the window.
    The full text remains one read_object('recipe') away."""
    from edp_claude.tools._bounds import WINDOW

    n = WINDOW * 5 + 7                       # 207 — comfortably past the window
    r = _recipe_with_decisions([f"decision {i} body" for i in range(n)])
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
    assert ad["count"] == n
    assert ad["load_bearing_count"] == n
    # a non-null cursor tells the reader more rows exist past the window
    assert ad["index_cursor"] is not None
    assert ad["load_bearing_cursor"] is not None
    # the recap still carries the un-missable count for self-detection
    assert f"decisions={n}" in data["recap"]["recap"]


async def test_rpb_post_compact_reground_is_byte_identical(env):
    """A fresh/compacted shell gets ONLY the pointer; the on-demand
    read_object('recipe').context.decisions returns the full text BYTE-IDENTICAL
    to the pre-RP-B inline dump ([d.text for d in r.context.decisions])."""
    bodies = [
        "DECISION ONE — settled embedder is MiniLM; never nomic.",
        "DECISION TWO — keep 3 hops; pursue code-level optimisation only.\n"
        "Multi-line body with detail that must survive verbatim.",
        "DECISION THREE — " + ("payload " * 500),
    ]
    r = _recipe_with_decisions(bodies)
    env.ctx.recipes.save(r)

    # what the steady-state push carries (the pointer)
    ctx = recipe_context(r)
    pushed_ids = [e["id"] for e in ctx["active_decisions"]["index"]]
    pushed_count = ctx["active_decisions"]["count"]

    # SELF-DETECTION: a fresh shell holds the index/count but NOT the bodies.
    # It can see the gap purely from the pointer (no body text present).
    import json
    assert ("payload " * 500) not in json.dumps(ctx)
    assert pushed_count == 3 and pushed_ids == ["d1", "d2", "d3"]

    # ON-DEMAND FETCH following the pointer -> full text, byte-identical to the
    # old inline dump.
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "recipe", recipe_id=r.recipe_id)
    fetched = [d["text"] for d in view["context"]["decisions"]]
    old_inline_dump = [d.text for d in r.context.decisions]   # the pre-RP-B push
    assert fetched == old_inline_dump
    assert fetched == bodies   # and equals the original text exactly
