"""list_subscriptions + unobserve (2026-07-20): the monitor plane's read
and delete verbs, completing CRUD (observe = create/overwrite)."""

import asyncio

import pytest

from edp_claude.reactive.handle_index import (
    register_subscription,
    sids_for_handle,
    unregister_subscription,
)


def _mk_sub(root, handle, sid, spec="rx.broker(me)"):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{sid}.spec").write_text(spec, encoding="utf-8")
    (root / f"{sid}.bindings.json").write_text(
        '{"me": "%s"}' % handle, encoding="utf-8")
    register_subscription(root, handle, sid)


def test_unregister_subscription_roundtrip(tmp_path):
    root = tmp_path / ".reactive"
    _mk_sub(root, "rec-x:s1", "sub-aaa")
    assert sids_for_handle(root, "rec-x:s1") == ["sub-aaa"]
    assert unregister_subscription(root, "rec-x:s1", "sub-aaa") is True
    assert sids_for_handle(root, "rec-x:s1") == []
    assert unregister_subscription(root, "rec-x:s1", "sub-aaa") is False


@pytest.fixture
def ctx_tools(tmp_path, monkeypatch):
    from edp_claude.tools._tools import ListSubscriptions, Unobserve
    from edp_claude.store.plan_store import PlanStore
    from edp_claude.store.recipe_store import RecipeStore

    class _Ctx:
        recipes = RecipeStore(tmp_path / "home" / ".recipes")
        plans = PlanStore(tmp_path / "home" / ".plans")
    ctx = _Ctx()
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return tmp_path / "home" / ".reactive",         ListSubscriptions(ctx), Unobserve(ctx)


def test_list_and_unobserve_scoped_to_owner(ctx_tools, monkeypatch):
    root, ls, un = ctx_tools
    _mk_sub(root, "rec-x:s1", "sub-mine")
    _mk_sub(root, "rec-y:s9", "sub-other")
    monkeypatch.setenv("EDP_HANDLE", "rec-x:s1")

    out = asyncio.run(ls._run(ls.InputModel()))
    body = out.body if hasattr(out, "body") else out
    data = getattr(out, "data", None) or body
    text = str(data)
    assert "sub-mine" in text and "sub-other" not in text

    ref = asyncio.run(un._run(un.InputModel(subscription_id="sub-other")))
    assert "not indexed" in str(ref)

    ok = asyncio.run(un._run(un.InputModel(subscription_id="sub-mine")))
    assert "sub-mine" in str(ok)
    assert sids_for_handle(root, "rec-x:s1") == []
    assert not (root / "sub-mine.spec").exists(), "artifacts removed"
    assert (root / "sub-other.spec").exists(), "foreign sub untouched"
