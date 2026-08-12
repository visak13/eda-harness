"""DESIGN-v6 W15 — search_context retrieval + kind=note worklog routing.

Covers the a3 acceptance surface:
  • search_context ranks a seeded decision in the top-3 (semantic retrieval
    into recipe context memory, via the embeddings sidecar);
  • the embeddings sidecar is written at record_context WRITE time and
    steady-state search reads it WITHOUT loading recipe.json (o6);
  • kind=note lands in the WORKLOG (plan worklog for a plan-scoped caller,
    the recipe worklog for a plan-less neuron caller) and NEVER reaches the
    recipe digest or the grounding_epoch;
  • search never mutates recipe.json (o6 byte-identical);
  • token-overlap fallback when the embed backend is down;
  • search_context is registered for workers/reviewers/planners.

Deterministic + offline: the default context uses StubEmbed (token-overlap
bag-of-words), so a query that shares a decision's tokens ranks it top.
"""

import json
from pathlib import Path

from edp_contracts import ToolOk

from edp_claude.store.atomic import read_jsonl
from edp_claude.tools._tools import _context_embeddings_path


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _scaffold(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="work"))
    return rid, sid, pid


# ── (1) retrieval: seeded decision ranks top-3 ─────────────────────────────

async def test_search_context_ranks_seeded_decision_top3(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    for text in [
        "The sky is blue and the clouds are white today",
        "Kill the JSON mandate: the gemma model emits RAW content, never "
        "format=schema serialization",
        "Lunch options are tacos, burritos, and salad",
        "Deploy the frontend on a CDN with long cache headers",
    ]:
        _ok(await env.call("record_context", kind="decision",
                           recipe_id=rid, text=text))

    got = _ok(await env.call(
        "search_context", recipe_id=rid,
        query="gemma raw content serialization json mandate",
        kinds=["decision"], top_k=3))

    ids = [m["id"] for m in got["matches"]]
    assert "d2" in ids, got                       # the JSON-mandate decision
    assert len(got["matches"]) <= 3
    assert got["matches"][0]["kind"] == "decision"
    assert all(m["provenance"].startswith("recipe:") for m in got["matches"])
    assert got["mode"] == "embedding"


# ── (2) sidecar written at record_context write time ───────────────────────

async def test_embeddings_sidecar_written_at_record_context_time(env):
    rid = _ok(await env.call("start_recipe", goal="my recipe goal",
                             domain="api"))["recipe_id"]
    path = _context_embeddings_path(env.ctx, rid)
    assert not path.exists()

    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="first decision about auth tokens"))

    assert path.exists()
    recs = read_jsonl(path)
    keys = {r["key"] for r in recs}
    assert "decision:d1" in keys
    assert "north_star:north_star" in keys        # goal seeded once
    d1 = next(r for r in recs if r["key"] == "decision:d1")
    assert isinstance(d1["embedding"], list) and d1["embedding"]


# ── (3) kind=note → plan worklog, never digest/epoch (plan-scoped caller) ───

async def test_note_lands_in_plan_worklog_not_digest_or_epoch(env, monkeypatch):
    rid, _sid, pid = await _scaffold(env)
    before = _ok(await env.call("get_recipe_digest", recipe_id=rid))
    epoch_before = before["recent_events"]["grounding_epoch"]

    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call("record_context", kind="note",
                       text="user away till Monday"))

    wl = _ok(await env.call("read_worklog", plan_id=pid))
    assert any(e.get("kind") == "note" and "Monday" in e.get("text", "")
               for e in wl["entries"]), wl

    after = _ok(await env.call("get_recipe_digest", recipe_id=rid))
    assert after["recent_events"]["grounding_epoch"] == epoch_before
    assert "note" not in after["recent_events"]["counts_by_kind"]
    assert all(e["kind"] != "note" for e in after["recent_events"]["recent"])
    assert "user away till Monday" not in json.dumps(after)


# ── (4) kind=note plan-less (neuron) → recipe worklog, excluded from digest ─

async def test_note_plan_less_goes_to_recipe_worklog_excluded_from_digest(env):
    # conftest clears EDP_ROLE/EDP_HANDLE → a neuron-like, plan-less caller.
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="use the settled minilm embedder", load_bearing=True))
    before = _ok(await env.call("get_recipe_digest", recipe_id=rid))
    epoch_before = before["recent_events"]["grounding_epoch"]
    total_before = before["recent_events"]["total"]

    _ok(await env.call("record_context", kind="note", recipe_id=rid,
                       text="user away till Monday"))

    events = read_jsonl(Path(env.ctx.recipes.root) / rid / "events.jsonl")
    assert any(e.get("kind") == "note" and "Monday" in e.get("text", "")
               for e in events), events

    after = _ok(await env.call("get_recipe_digest", recipe_id=rid))
    assert after["recent_events"]["grounding_epoch"] == epoch_before
    assert "note" not in after["recent_events"]["counts_by_kind"]
    assert after["recent_events"]["total"] == total_before   # note not counted
    assert "user away till Monday" not in json.dumps(after)


# ── (5) o6: search never mutates recipe.json ───────────────────────────────

async def test_search_context_does_not_mutate_recipe_json(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    for t in ["decision about the caching layer",
              "decision about auth tokens"]:
        _ok(await env.call("record_context", kind="decision",
                           recipe_id=rid, text=t))
    rjson = Path(env.ctx.recipes.root) / rid / "recipe.json"
    before = rjson.read_bytes()

    _ok(await env.call("search_context", recipe_id=rid,
                       query="caching auth", top_k=5))     # default kinds

    assert rjson.read_bytes() == before


# ── (6) steady-state search reads the sidecar WITHOUT loading recipe.json ───

async def test_steady_state_search_does_not_load_recipe(env, monkeypatch):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="gemma raw content serialization mandate"))

    calls = {"n": 0}
    orig = env.ctx.recipes.load

    def spy(rid_):
        calls["n"] += 1
        return orig(rid_)

    monkeypatch.setattr(env.ctx.recipes, "load", spy)
    got = _ok(await env.call("search_context", recipe_id=rid,
                             query="gemma serialization", top_k=3))

    assert calls["n"] == 0, "steady-state search must not load recipe.json"
    assert any(m["id"] == "d1" for m in got["matches"]), got


# ── (7) legacy recipe (no sidecar) is backfilled on first search ───────────

async def test_legacy_recipe_backfilled_on_first_search(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="gemma raw content serialization mandate"))
    # simulate a pre-indexing legacy recipe: drop the sidecar.
    path = _context_embeddings_path(env.ctx, rid)
    path.unlink()
    assert not path.exists()

    got = _ok(await env.call("search_context", recipe_id=rid,
                             query="gemma serialization mandate",
                             kinds=["decision"], top_k=3))

    assert any(m["id"] == "d1" for m in got["matches"]), got
    assert path.exists()                          # backfill re-created it


# ── (8) token-overlap fallback when the embed backend is down ──────────────

async def test_search_context_text_fallback_when_embed_down(env, monkeypatch):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="gemma raw content serialization mandate"))
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="unrelated lunch tacos burritos"))

    async def boom(text, kind="document"):
        raise RuntimeError("embed backend down")

    monkeypatch.setattr(env.ctx.embed, "embed", boom)
    got = _ok(await env.call("search_context", recipe_id=rid,
                             query="gemma serialization mandate",
                             kinds=["decision"], top_k=2))

    assert got["mode"] == "text-fallback"
    assert got["matches"][0]["id"] == "d1", got


# ── (9) per-role registration ──────────────────────────────────────────────

def test_search_context_registered_for_worker_reviewer_planner():
    from edp_claude.tools.roles import ROLE_TOOLSETS
    for role in ("worker", "reviewer", "planner", "neuron"):
        assert "search_context" in ROLE_TOOLSETS[role], role
