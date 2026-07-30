"""HttpPool (consumer PoolPort) — fake httpx, no network. Capacity error
must reach the caller verbatim (Tool.from_upstream)."""

from edp_contracts import ToolError, ToolOk

from edp_claude.clients import HttpPool


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code // 100 != 2:
            raise AssertionError("unexpected")


class _Client:
    def __init__(self, post=None, get=None):
        self._post = post
        self._get = get
        self.last_json = None  # capture the posted /v1/spawn body
        self.last_get_kwargs = None  # capture per-call kwargs (e.g. timeout)

    async def post(self, url, json=None):
        self.last_json = json
        return self._post

    async def get(self, url, **kwargs):
        self.last_get_kwargs = kwargs
        return self._get


async def test_spawn_ok_returns_session_id():
    c = _Client(post=_Resp(200, {"session_id": "worker:abc"}))
    res = await HttpPool("http://p", c).spawn_worker("plan1", "a1")
    assert isinstance(res, ToolOk)
    assert res.data["session_id"] == "worker:abc"
    assert res.data["handle"] == "plan1:a1"


async def test_capacity_error_is_verbatim():
    upstream = {
        "ok": False, "source": "edp-pool",
        "code": "pool_capacity_exceeded",
        "message": "max workers = 3; 3 active; cannot spawn another",
        "retryable": True,
    }
    c = _Client(post=_Resp(409, upstream))
    res = await HttpPool("http://p", c).spawn_worker("plan1", "a4")
    assert isinstance(res, ToolError)
    assert res.code == "pool_capacity_exceeded"
    assert res.message == "max workers = 3; 3 active; cannot spawn another"
    assert res.retryable is True


# --- W10a: optional per-spawn `model` tier on the 6 non-worker methods.
# A stamped tier becomes a top-level /v1/spawn `model` key; omitting it
# (default None) posts a body with NO `model` key (byte-identical to
# pre-W10a). Representative subset: spawn_planner + spawn_reviewer.

async def test_spawn_planner_model_forwards_as_top_level_key():
    c = _Client(post=_Resp(200, {"session_id": "planner:abc"}))
    await HttpPool("http://p", c).spawn_planner("rec1", "s1", model="claude-x")
    assert c.last_json.get("model") == "claude-x"
    assert c.last_json["role"] == "planner"
    assert c.last_json["handle"] == "rec1:s1"


async def test_spawn_planner_default_omits_model_key():
    import uuid

    c = _Client(post=_Resp(200, {"session_id": "planner:abc"}))
    await HttpPool("http://p", c).spawn_planner("rec1", "s1")

    # The W10a bar this test guards is UNCHANGED: an unstamped tier adds no
    # `model` key. The exact key set (not a subset check) keeps that strict —
    # a leaked `model` still fails here.
    assert "model" not in c.last_json
    assert set(c.last_json) == {
        "role", "handle", "parent_session", "claude_session"
    }
    assert c.last_json["role"] == "planner"
    assert c.last_json["handle"] == "rec1:s1"
    assert c.last_json["parent_session"] == "rec1"
    # W11 re-points the body bar: a planner spawn now ALWAYS pins a fresh
    # uuid4 `claude_session` (so a suspended planner is forkable). Asserted
    # here too, not merely tolerated — see tests/test_w11_session_registry.py.
    assert uuid.UUID(c.last_json["claude_session"]).version == 4


async def test_spawn_reviewer_model_forwards_as_top_level_key():
    c = _Client(post=_Resp(200, {"session_id": "reviewer:abc"}))
    await HttpPool("http://p", c).spawn_reviewer(
        "par1", "rev1", "sess1", model="claude-x"
    )
    assert c.last_json.get("model") == "claude-x"
    assert c.last_json["role"] == "reviewer"
    assert c.last_json["handle"] == "rev1"


async def test_spawn_reviewer_default_omits_model_key():
    c = _Client(post=_Resp(200, {"session_id": "reviewer:abc"}))
    await HttpPool("http://p", c).spawn_reviewer("par1", "rev1", "sess1")
    assert "model" not in c.last_json
    # byte-identical to pre-W10a
    assert c.last_json == {
        "role": "reviewer", "handle": "rev1", "parent_session": "par1",
        "claude_session": "sess1",
    }


async def test_liveness_parses_state():
    # W7: liveness returns {state, last_output_ts}. An endpoint that
    # predates the busyness field (state only) → last_output_ts is None
    # (pass-through, no KeyError).
    c = _Client(get=_Resp(200, {"handle": "p:a1", "state": "alive"}))
    out = await HttpPool("http://p", c).liveness("p:a1")
    assert out == {"state": "alive", "last_output_ts": None}


async def test_liveness_carries_last_output_ts():
    # W7: the pool's mtime-derived busyness signal flows through verbatim.
    c = _Client(get=_Resp(
        200, {"handle": "p:a1", "state": "alive", "last_output_ts": 1720000000.5}))
    out = await HttpPool("http://p", c).liveness("p:a1")
    assert out == {"state": "alive", "last_output_ts": 1720000000.5}


async def test_liveness_uses_bounded_fast_timeout_not_shared_30s():
    # C2 (s18): the liveness path must ride a dedicated 2-5s timeout, NOT the
    # shared 30s httpx client — a hung pool must not stall a tick for 30s.
    from edp_claude.clients.http_pool import LIVENESS_TIMEOUT_S

    c = _Client(get=_Resp(200, {"handle": "p:a1", "state": "alive"}))
    await HttpPool("http://p", c).liveness("p:a1")
    assert c.last_get_kwargs.get("timeout") == LIVENESS_TIMEOUT_S
    assert 2.0 <= LIVENESS_TIMEOUT_S <= 5.0
    assert LIVENESS_TIMEOUT_S != 30.0


async def test_release_ok_echoes_session_id():
    c = _Client(post=_Resp(200, {"released": "worker:abc"}))
    res = await HttpPool("http://p", c).release("worker:abc")
    assert isinstance(res, ToolOk)
    assert res.data["released"] == "worker:abc"


async def test_release_upstream_error_is_verbatim():
    upstream = {
        "ok": False, "source": "edp-pool", "code": "pool_unknown_session",
        "message": "no such session worker:zzz", "retryable": False,
    }
    c = _Client(post=_Resp(404, upstream))
    res = await HttpPool("http://p", c).release("worker:zzz")
    assert isinstance(res, ToolError)
    assert res.code == "pool_unknown_session"
    assert res.message == "no such session worker:zzz"
