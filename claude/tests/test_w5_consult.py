"""W5 PART 1 (DESIGN-v6 §W5) — consult/steer delivery + reconcile drain +
steer-ack re-surface + W2 reground re-delivery.

The bar this pins (a1_delivery_wiring):

* `reconcile` (NOT `next_action`, which is zero-external-IO by design) polls
  the recipe's OWN inbox and stashes every kind=consult/steer message as a
  compact pending record onto `recipe.consult_pending` (msg_id/kind/from/ts/
  preview) with a `consult_cursor` high-water so a drained message is never
  re-added.
* `recipe_context` (push plane) and `get_recipe_digest` (re-ground plane)
  SURFACE the undrained consult/steer as one shared bounded window+cursor
  view (#18).
* steer-ack: a drained steer whose msg_id is NOT referenced by a subsequent
  `record_context` decision RE-SURFACES every tick; once a decision references
  it, it clears and never resurrects (the cursor prevents re-add).
* W2 reground (post-compaction) RE-DELIVERS an undrained consult — the
  reground block reuses `get_recipe_digest`, so `consult_pending` rides along.
* o6 / RP-A: the legacy fixture 0e7ca8 still loads byte-identically AND a
  consult-free recipe serializes WITHOUT the new keys (emission-gated).

Env discipline (d7): EDP_ROLE/EDP_HANDLE/EDP_TIER_WRITE that leak from a
launching worker shell are neutralised IN-PROCESS by the autouse conftest
fixture; every assertion is done in PYTHON (the acceptance verify shell has
neither `env` nor `grep`).
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from edp_contracts import BrokerMessage, ToolError, ToolOk

from edp_claude.clients import HttpPool
from edp_claude.fsm import recipe_context
from edp_claude.schemas import Recipe
from edp_claude.server import make_http_context
from edp_claude.stubs.stub_broker import StubBroker
from edp_claude.tools import build_registry
from edp_claude.tools._tools import ALL_TOOL_CLASSES, CONSULT_DEFAULT_MODEL
from edp_claude.tools.roles import ROLE_TOOLSETS


def _now():
    return datetime.now(timezone.utc)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _mk_recipe(env, rid="r-consult"):
    """A PLANNING recipe with one pending step (past COMPREHENDING, so the
    invariant validator is satisfied) — reconcile's recipe branch runs the
    consult drain regardless of state, and the other syncs are no-ops here."""
    _save_recipe(env.ctx, rid)
    return rid


def _save_recipe(ctx, rid="r-consult"):
    """Same recipe, addressed by ctx — PART 2 builds its own context (a real
    HttpPool over a fake transport), so it has no `env` to borrow."""
    ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="software_engineering",
        state="planning",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "pending", "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": [], "assumptions": [], "rejected_options": []},
        created_at=_now(), updated_at=_now(),
    )))
    return rid


async def _send(env, rid, kind, *, msg_id, body, from_="user", ts=None):
    """Post a consult/steer to the recipe's OWN inbox (the durable recipe_id
    recipient the neuron observes — no separate consult recipient)."""
    return _ok(await env.ctx.broker.send(BrokerMessage(
        msg_id=msg_id, ts=ts or _now(), from_=from_, to=rid,
        kind=kind, body=body)))


async def _reconcile(env, rid, **kw):
    return _ok(await env.call("reconcile", handle=rid, handle_type="recipe",
                              **kw))


# ── 1. reconcile drains a consult → consult_pending + digest/push surface it ──
async def test_reconcile_drains_consult_and_surfaces_it(env):
    rid = _mk_recipe(env)
    await _send(env, rid, "consult", msg_id="c-1",
                body={"question": "should we use X?"})

    data = await _reconcile(env, rid)
    assert data["changed"] is True

    r = env.ctx.recipes.load(rid)
    assert len(r.consult_pending) == 1
    entry = r.consult_pending[0]
    assert entry["msg_id"] == "c-1"
    assert entry["kind"] == "consult"
    assert entry["from"] == "user"
    assert "should we use X" in entry["preview"]
    assert r.consult_cursor is not None

    # digest (re-ground plane) surfaces it
    dg = _ok(await env.call("get_recipe_digest", recipe_id=rid))
    assert dg["consult_pending"]["count"] == 1
    assert dg["consult_pending"]["kinds"].get("consult") == 1
    assert dg["consult_pending"]["items"][0]["msg_id"] == "c-1"

    # recipe_context (push plane) surfaces the SAME view
    ctx = recipe_context(r)
    assert ctx["consult_pending"]["count"] == 1
    assert ctx["consult_pending"]["kinds"].get("consult") == 1


# ── 2. steer re-surfaces until a decision references it, then clears for good ─
async def test_steer_resurfaces_until_referenced_then_clears(env):
    rid = _mk_recipe(env)
    await _send(env, rid, "steer", msg_id="steer-9",
                body={"text": "stop doing X"})

    # tick 1: drained + surfaced
    await _reconcile(env, rid)
    r = env.ctx.recipes.load(rid)
    assert [e["msg_id"] for e in r.consult_pending] == ["steer-9"]

    # tick 2: still surfaced (unacked steer re-surfaces) and NOT double-added
    d2 = await _reconcile(env, rid)
    assert d2["changed"] is False        # nothing new; entry persists as-is
    r = env.ctx.recipes.load(rid)
    assert [e["msg_id"] for e in r.consult_pending] == ["steer-9"]

    # a subsequent decision references the steer msg_id
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="Per steer steer-9, we stop doing X.",
                       by="neuron"))

    # tick 3: acked → cleared
    d3 = await _reconcile(env, rid)
    assert d3["changed"] is True
    r = env.ctx.recipes.load(rid)
    assert r.consult_pending == []

    # tick 4: STAYS cleared — the cursor prevents resurrection from the window
    await _reconcile(env, rid)
    r = env.ctx.recipes.load(rid)
    assert r.consult_pending == []

    # digest reflects the cleared state ({} == none pending)
    dg = _ok(await env.call("get_recipe_digest", recipe_id=rid))
    assert dg["consult_pending"] == {}
    # and the push plane omits the key entirely when nothing pends
    assert "consult_pending" not in recipe_context(r)


# ── 3. W2 reground (post-compaction) re-delivers an undrained consult ────────
async def test_undrained_consult_redelivered_on_reground(env):
    rid = _mk_recipe(env)
    await _send(env, rid, "consult", msg_id="c-42",
                body={"question": "which db?"})

    # a single reground tick both DRAINS (before the reground payload is built)
    # and RE-DELIVERS via the digest block the reground reuses.
    data = await _reconcile(env, rid, reground=True)
    assert data["reground"] is not None
    cp = data["reground"]["digest"]["consult_pending"]
    assert cp["count"] == 1
    assert cp["items"][0]["msg_id"] == "c-42"


# ── 4. both kinds drain together; the view reports true per-kind totals ──────
async def test_consult_and_steer_drain_together(env):
    rid = _mk_recipe(env)
    await _send(env, rid, "consult", msg_id="c-a", body={"question": "q?"})
    await _send(env, rid, "steer", msg_id="s-b", body={"text": "redirect"})
    # a non-consult message must be ignored by the drain
    await _send(env, rid, "progress", msg_id="p-c", body={"note": "n"})

    await _reconcile(env, rid)
    r = env.ctx.recipes.load(rid)
    kinds = {e["kind"] for e in r.consult_pending}
    assert kinds == {"consult", "steer"}
    assert {e["msg_id"] for e in r.consult_pending} == {"c-a", "s-b"}

    view = recipe_context(r)["consult_pending"]
    assert view["count"] == 2
    assert view["kinds"] == {"consult": 1, "steer": 1}


# ── 4b. a tz-naive ts degrades gracefully; it NEVER crashes the tick ────────
async def test_naive_ts_consult_drains_without_crashing_the_tick(env):
    """N1 (a5 review) — `BrokerMessage.ts` is documented tz-aware UTC but NO
    validator enforces it. The high-water `max(...)` and the `newest > cursor`
    compare used to sit OUTSIDE the broker-poll guard, so one naive ts raised
    TypeError and failed the WHOLE reconcile tick — the heartbeat spine —
    contradicting this drain's own "broker down ≠ tick failure" contract.
    Both sides of the compare are now read as UTC, and the advance is its own
    best-effort guard: the message still drains, the cursor stays orderable."""
    rid = _mk_recipe(env)
    naive = datetime(2026, 1, 1, 12, 0, 0)                       # tz-UNAWARE
    aware = datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)  # well-formed
    await _send(env, rid, "consult", msg_id="c-naive",
                body={"question": "naive ts?"}, ts=naive)
    await _send(env, rid, "steer", msg_id="s-aware",
                body={"text": "redirect"}, ts=aware)
    posted = {m.msg_id: m.ts.tzinfo for m in await env.ctx.broker.poll(rid)}
    assert posted["c-naive"] is None, "the fixture must post a truly naive ts"

    data = await _reconcile(env, rid)          # must NOT raise
    assert data["changed"] is True

    # the naive entry drained alongside the well-formed one
    r = env.ctx.recipes.load(rid)
    assert {e["msg_id"] for e in r.consult_pending} == {"c-naive", "s-aware"}
    # the cursor is orderable (aware) and took the newest ts, read as UTC
    assert r.consult_cursor == aware
    assert r.consult_cursor.tzinfo is not None

    # a later tick also survives, and strict '>' never resurrects/duplicates
    d2 = await _reconcile(env, rid)
    assert d2["changed"] is False
    r = env.ctx.recipes.load(rid)
    assert {e["msg_id"] for e in r.consult_pending} == {"c-naive", "s-aware"}


# ── 5. o6 emission-gate: a consult-free recipe serializes WITHOUT the keys ───
def test_consult_fields_emission_gated(env):
    rid = _mk_recipe(env)
    r = env.ctx.recipes.load(rid)
    dumped = r.model_dump(mode="json")
    assert "consult_pending" not in dumped
    assert "consult_cursor" not in dumped


# ── 6. o6 REGRESSION BAR: legacy fixture 0e7ca8 loads byte-identically ───────
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
RECIPES = Path(__file__).resolve().parents[1] / ".recipes"


def test_o6_legacy_fixture_byte_identical(monkeypatch, tmp_path):
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)   # tiering OFF
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )

    rdir = RECIPES / LEGACY_RID
    assert (rdir / "recipe.json").exists(), (
        f"legacy fixture {LEGACY_RID} missing under {RECIPES}")
    original = (rdir / "recipe.json").read_text(encoding="utf-8")

    raw = json.loads(original)
    model = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))
    # a9: dehydrate into tmp_path, never the live fixture dir. For an
    # already-reffed field dehydrate ALWAYS re-writes the sidecar
    # (tiering.py:97), so pointing it at `rdir` rewrites 370 real files
    # per run and races test_w1_context_diet's copytree. The payload is
    # root-independent, so this changes nothing the test ASSERTS.
    payload = dehydrate_recipe_payload(model.model_dump(mode="json"), tmp_path)
    reserialized = json.dumps(payload, indent=2)
    assert reserialized == original, (
        "legacy fixture round-trip is NOT byte-identical — a W5 consult field "
        "leaked into the schema")


# ════════════════════════════════════════════════════════════════════════
# W5 PART 2 (a2_convene_consult) — the `convene_consult` tool, the
# http_pool consult spawn, and .claude/commands/consult.md.
#
# The bar this pins:
#
# * `convene_consult` builds the CORRECT /v1/spawn body — role="consult",
#   mode="monitor" (a visible console), model defaulting to opus and an
#   explicit override honoured — against a REAL HttpPool driven by a fake
#   httpx client. No pool, no network, no shell is ever spawned.
# * ZERO edp-pool changes are required: the body rides the generic
#   /v1/spawn contract (capacity cap is worker-only; activation_text falls
#   back to `/consult`).
# * The BRIEF is posted to the consult's inbox BEFORE the spawn, so the
#   shell's Step-1 check_inbox can never race an empty inbox.
# * `.claude/commands/consult.md` exists and honours its contract
#   (get_recipe_digest grounding, answers to the asker, record_context).
# * The tool is registered for the roles W5 names: neuron + planner (the
#   user's foreground session gets the full registry via the absent-role
#   fail-open, and W10's escalation ladder drives planner/neuron).
# ════════════════════════════════════════════════════════════════════════

COMMANDS = Path(__file__).resolve().parents[1] / ".claude" / "commands"
CONSULT_MD = COMMANDS / "consult.md"


class _Resp:
    """Minimal httpx-response stand-in (mirrors tests/test_http_pool.py)."""

    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._p = payload or {"session_id": "consult:sess-1"}

    def json(self):
        return self._p


class _Client:
    """Fake httpx client: captures the posted /v1/spawn body. No network."""

    def __init__(self, post=None):
        self._post = post or _Resp()
        self.last_json = None
        self.posts = 0

    async def post(self, url, json=None):
        self.last_json = json
        self.posts += 1
        return self._post


def _http_env(tmp_path, client=None, rid="r-consult"):
    """A context whose pool is a REAL HttpPool over the fake client — so the
    assertions below are on the ACTUAL spawn body convene_consult produces,
    not on a stub's recollection of it."""
    client = client or _Client()
    ctx = make_http_context(
        tmp_path, broker=StubBroker(), pool=HttpPool("http://p", client))
    _save_recipe(ctx, rid)
    tools = {t.name: t for t in build_registry(ctx)}

    async def call(_name, **inp):
        return await tools[_name].run(inp)

    return ctx, client, call

# ── 7-11. the spawn-behaviour tests, RETIRED with the verb they exercised ───
def test_the_convene_consult_spawn_path_is_unreachable(tmp_path):
    """Blocks 7-11 asserted the spawn body, the model override, the
    brief-before-spawn ordering, error propagation and the unknown-recipe
    refusal. All five drove the tool THROUGH the registry, and on 2026-07-25
    the operator retired it, so every one failed on a registry lookup rather
    than on a claim about behaviour.

    They are replaced by this assertion rather than repaired: a test that
    constructed the deregistered class directly would pass forever while
    proving nothing about a path no role can reach. The unreachability is the
    thing now worth pinning.

    The ConveneConsult CLASS stays intact and importable in _tools.py; only its
    registration was withdrawn. Restore these five from version control if the
    operator ever restores the verb."""
    ctx = make_http_context(
        tmp_path, broker=StubBroker(), pool=HttpPool("http://p", _Client()))
    assert "convene_consult" not in {t.name for t in build_registry(ctx)}


# ── 12. the client spawn path is DELETED with the role ──────────────────────
def test_spawn_consult_client_path_is_deleted():
    """2026-08-12 dead-surface sweep: `HttpPool.spawn_consult` (and its port /
    stub siblings) went with the consult shell role — its only caller was the
    deregistered ConveneConsult tool. A surviving client method would be a
    spawn path to a role with no toolset row (the fail-open over-grant trap
    test_w4_roles guards)."""
    assert not hasattr(HttpPool, "spawn_consult")
    from edp_claude.stubs.stub_pool import StubPool
    assert not hasattr(StubPool, "spawn_consult")
    # POSITIVE CONTROL: the sibling spawn methods survive.
    assert hasattr(HttpPool, "spawn_reviewer")


# ── 13. the activator card is DELETED with the role ─────────────────────────
def test_consult_command_file_is_gone():
    """The card was the `/consult` activation target; with the spawn path
    deleted no shell can ever receive it, and a live-looking card for an
    unreachable role is exactly the dead surface the 2026-08-12 sweep
    retired."""
    assert not CONSULT_MD.exists(), (
        f"{CONSULT_MD} is back — the consult shell role was retired 2026-08-12")
    # POSITIVE CONTROL: the sweep looked at the real commands dir.
    assert (COMMANDS / "worker.md").exists()


# ── 14. registered for exactly the roles W5 names ───────────────────────────
def test_convene_consult_is_retired_everywhere():
    """INVERTED 2026-07-25 by operator ruling. This test previously pinned the
    W5 contract that `convene_consult` was registered and callable by the
    planner and the neuron. The operator retired the SPAWNED consult shell
    ("I found it useless and will burn tokens"), so the contract is now its
    opposite and is pinned just as tightly — a retirement nobody asserts is a
    retirement that quietly regrows.

    Per the v7 P0 break-and-migrate rule a retired verb must resolve NOWHERE,
    so deregistration is asserted alongside absence from every role surface.
    The retirement is recorded in roles.py `_OPERATOR_RETIRED` with its reason,
    its disclosed cost (W10's escalation ladder loses its only response to a
    stuck action) and the two-line path back."""
    from edp_claude.tools.roles import RETIRED_VERBS
    assert "convene_consult" in RETIRED_VERBS
    # v7 P0: deregistered outright, not merely off the role surfaces.
    assert "convene_consult" not in {c.name for c in ALL_TOOL_CLASSES}
    for role in ROLE_TOOLSETS:
        assert "convene_consult" not in ROLE_TOOLSETS[role], role
    # UNTOUCHED by this retirement: the inline specialist read and the
    # persistent comprehension neuron. Only the spawned shell went.
    assert "consult_specialist" in ROLE_TOOLSETS["planner"]
    assert "consult_curiosity" in ROLE_TOOLSETS["neuron"]


# ── 15. the role itself is gone (2026-08-12 dead-surface sweep) ─────────────
def test_consult_role_row_is_gone_with_its_role():
    """Block 15 pinned that the consult surface covered its own command file.
    Both are deleted now — the verb retirement of 2026-07-25 left the role
    unreachable, and the 2026-08-12 sweep removed the toolset row, the card,
    the seat mapping and the spawn client together (atomicity: a row without a
    spawn path is the fail-open trap in reverse)."""
    assert "consult" not in ROLE_TOOLSETS
    from edp_claude.tools.roles import CRUD_OBJECT_SCOPE, toolset_for_role
    assert toolset_for_role("consult") is None
    assert "consult" not in CRUD_OBJECT_SCOPE
