"""Neuron DB — the unified specialization registry (vision phases 2+3).

Covers: create_specialization bootstraps neuron + spec; neuron_search
ranks by description match (StubEmbed deterministic); lifecycle
transitions are validated (the HITL gate); flow-back base pointer;
touch/flag decay signals; the spec recipe builds incrementally and is
loadable.
"""

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _mk(env, name, subject, description, category="domain"):
    d = _ok(await env.call("create_specialization", name=name,
                           subject=subject, description=description,
                           category=category))
    return d["neuron_id"], d["spec_id"]


async def _approve(env, nid):
    # trained → pending_review → stable (the HITL gate path)
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="pending_review"))
    _ok(await env.call("neuron_set_status", neuron_id=nid, status="stable"))


async def test_create_specialization_bootstraps_neuron_and_spec(env):
    nid, sid = await _mk(env, "Java Expert",
                         "Java / DDD / Spring Boot",
                         "domain-driven design and Spring Boot services")
    assert nid == "java-expert" and sid == "spec-java-expert"
    rec = env.ctx.neurons.get(nid)
    assert rec.status == "trained"   # SME authored it; not yet usable
    assert rec.spec_id == sid
    assert rec.category == "domain"
    spec = env.ctx.specs.load(sid)
    assert spec.neuron_id == nid and spec.subject.startswith("Java")
    assert spec.entries == []


async def test_neuron_search_ranks_by_description(env):
    await _mk(env, "Java Expert", "Java / Spring",
              "domain driven design spring boot java services")
    await _mk(env, "React Expert", "React / TS",
              "react hooks typescript tailwind frontend components")
    res = _ok(await env.call("neuron_search",
                             query="spring boot java backend", top_k=2))
    assert res["mode"] == "embedding"
    assert res["matches"][0]["neuron_id"] == "java-expert"
    # the React expert should rank below for a Java query
    assert res["matches"][0]["score"] >= res["matches"][1]["score"]


async def test_search_text_fallback_when_embed_down(env, monkeypatch):
    await _mk(env, "Java Expert", "Java", "spring boot java services")

    async def boom(_text):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(env.ctx.embed, "embed", boom)
    res = _ok(await env.call("neuron_search", query="java spring", top_k=1))
    assert res["mode"] == "text-fallback"
    assert res["matches"][0]["neuron_id"] == "java-expert"


async def test_status_transitions_validated(env):
    nid, _ = await _mk(env, "X", "x", "x specialist")
    assert env.ctx.neurons.get(nid).status == "trained"
    # trained -> stable is NOT legal (must pass the HITL gate first)
    skip = await env.call("neuron_set_status", neuron_id=nid,
                          status="stable")
    assert isinstance(skip, ToolError)
    assert "illegal transition" in skip.message.lower()
    # trained -> pending_review -> stable (the gate path)
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="pending_review"))
    _ok(await env.call("neuron_set_status", neuron_id=nid, status="stable"))
    assert env.ctx.neurons.get(nid).status == "stable"
    # stable -> trained is NOT legal
    bad = await env.call("neuron_set_status", neuron_id=nid,
                         status="trained")
    assert isinstance(bad, ToolError)
    # stable -> pending_review (re-validation on decay) IS legal
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="pending_review"))
    # archived from pending_review is legal; archived is terminal
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="archived"))
    term = await env.call("neuron_set_status", neuron_id=nid,
                          status="stable")
    assert isinstance(term, ToolError)


async def test_flow_back_base_session_and_decay_signals(env):
    nid, _ = await _mk(env, "X", "x", "x specialist")
    # flow-back: promote a fork session to base (decision #2)
    out = _ok(await env.call("neuron_set_base_session", neuron_id=nid,
                             session_id="sess-abc"))
    assert out["neuron"]["base_session_id"] == "sess-abc"
    assert out["neuron"]["trained_at"] is not None
    # touch + flag (decay signals, decision #4)
    _ok(await env.call("neuron_touch", neuron_id=nid))
    _ok(await env.call("neuron_touch", neuron_id=nid))
    f = _ok(await env.call("neuron_flag", neuron_id=nid))
    assert f["neuron"]["use_count"] == 2
    assert f["neuron"]["flag_count"] == 1


async def test_archived_neuron_excluded_from_search(env):
    nid, _ = await _mk(env, "Old Skill", "old", "obsolete legacy thing")
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="archived"))
    res = _ok(await env.call("neuron_search", query="obsolete legacy",
                             top_k=5))
    assert all(m["neuron_id"] != nid for m in res["matches"])


async def test_neuron_list_filters(env):
    n1, _ = await _mk(env, "A", "a", "alpha domain")
    n2, _ = await _mk(env, "B", "b", "beta comprehension", "comprehension")
    await _approve(env, n1)
    stable = _ok(await env.call("neuron_list", status="stable"))
    assert [n["neuron_id"] for n in stable["neurons"]] == [n1]
    comp = _ok(await env.call("neuron_list", category="comprehension"))
    assert [n["neuron_id"] for n in comp["neurons"]] == [n2]


async def test_get_unknown_neuron_returns_null(env):
    out = _ok(await env.call("neuron_get", neuron_id="nope"))
    assert out["neuron"] is None
