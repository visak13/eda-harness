"""P4 flowback — the recipe-scoped broadcast channel.

Workers/reviewers emit structured events (emit_recipe_event) onto the
recipe's events.jsonl; the neuron subscribes via rx.recipe_events and
receives them LIVE without the planner relaying. propose_spec_learning
surfaces a pointer event so the quarantined sidecar stops being
pull-only-invisible.
"""

import json

import reactivex as rx
from edp_contracts import ToolOk

from edp_claude.reactive import RxRuntime


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _scaffold(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="work"))
    return rid, sid, pid


def _events(env, rid):
    p = env.ctx.recipes.root / rid / "events.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
            if x.strip()]


# ── emit_recipe_event lineage resolution ────────────────────────────────────

async def test_worker_emit_resolves_recipe_via_plan(env, monkeypatch):
    rid, _, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    got = _ok(await env.call("emit_recipe_event", kind="learning",
                             body={"summary": "the cache key must be sha256"}))
    assert got["recipe_id"] == rid
    ev = [e for e in _events(env, rid) if e["kind"] == "learning"]
    assert len(ev) == 1
    e = ev[0]
    assert e["channel"] == "flowback" and e["agent_role"] == "worker"
    assert e["plan_id"] == pid and e["action_id"] == "a1"
    assert e["from"] == f"{pid}:a1"
    assert e["body"]["summary"].startswith("the cache key")


async def test_planner_emit_resolves_recipe_directly(env, monkeypatch):
    rid, sid, _ = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:{sid}")
    monkeypatch.setenv("EDP_ROLE", "planner")
    got = _ok(await env.call("emit_recipe_event", kind="status_ping",
                             body={"phase": "authoring"}))
    assert got["recipe_id"] == rid


async def test_neuron_emit_needs_explicit_recipe_id(env, monkeypatch):
    rid, _, _ = await _scaffold(env)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_ROLE", raising=False)
    res = await env.call("emit_recipe_event", kind="progress", body={})
    assert not isinstance(res, ToolOk)          # unresolvable → precondition
    got = _ok(await env.call("emit_recipe_event", kind="progress",
                             body={}, recipe_id=rid))
    assert got["recipe_id"] == rid


# ── rx.recipe_events composition (injected provider, no I/O) ────────────────

def _runtime_with(entries):
    def provider(name, **kw):
        assert name == "worklog" and kw.get("recipe_id")
        return rx.of(*entries)
    return RxRuntime(provider)


def _collect(obs):
    out = []
    obs.subscribe(on_next=out.append)
    return out


def test_rx_recipe_events_filters_flowback_channel():
    entries = [
        {"kind": "recipe_saved", "version": 3},                 # plumbing
        {"kind": "learning", "channel": "flowback", "b": 1},
        {"kind": "advisory_override", "op": "delete_step"},     # P3 audit
        {"kind": "message_received", "from": "x"},              # plumbing
        {"kind": "blocker", "channel": "flowback", "b": 2},
    ]
    rt = _runtime_with(entries)
    got = _collect(rt.recipe_events("r1"))
    assert [e["kind"] for e in got] == ["learning", "advisory_override",
                                       "blocker"]


def test_rx_recipe_events_kinds_narrowing():
    entries = [
        {"kind": "learning", "channel": "flowback"},
        {"kind": "status_ping", "channel": "flowback"},
        {"kind": "advisory_override"},
    ]
    rt = _runtime_with(entries)
    got = _collect(rt.recipe_events("r1", kinds=["learning"]))
    assert [e["kind"] for e in got] == ["learning"]


# ── a spec-scoped learning event auto-proposes + surfaces a pointer event ───
# (v7 P0 deleted the explicit propose_spec_learning verb; the LIVE path is
# the W3 auto-propose off emit_recipe_event(kind="learning", spec_id=…).)

async def test_spec_learning_event_auto_proposes_and_emits_pointer(
        env, monkeypatch):
    rid, _, pid = await _scaffold(env)
    nid = _ok(await env.call(
        "create_specialization", name="Py ML", subject="python ml",
        category="domain", description="python ml craft"))
    spec_id = nid["spec_id"]
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call(
        "emit_recipe_event", kind="learning",
        body={"summary": "never tensor-batch EasyOCR; cache+prefetch "
                         "instead",
              "spec_id": spec_id, "tag": "[required]"}))
    ev = [e for e in _events(env, rid)
          if e["kind"] == "spec_learning_proposed"]
    assert len(ev) == 1
    assert ev[0]["body"]["spec_id"] == spec_id
    # quarantine unchanged: the learning is only 'proposed'
    q = _ok(await env.call("list_spec_learnings", spec_id=spec_id))
    assert q["count"] == 1 and q["learnings"][0]["status"] == "proposed"


# ── read path: the channel is queryable too ─────────────────────────────────

async def test_flowback_events_readable_with_kind_filter(env, monkeypatch):
    rid, _, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call("emit_recipe_event", kind="learning",
                       body={"summary": "s"}))
    _ok(await env.call("emit_recipe_event", kind="status_ping",
                       body={"phase": "x"}))
    got = _ok(await env.call("read_object", type="worklog",
                             ids={"recipe_id": rid, "kinds": ["learning"]}))
    assert [e["kind"] for e in got["object"]] == ["learning"]
