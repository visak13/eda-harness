"""W11 a2 (DESIGN-v6) — the HttpPool client pins a planner claude session and
filters the session listing.

W11's suspend/resume forks a suspended planner's claude session. That fork has
nothing to fork FROM unless the session id is known up front: today
`spawn_planner` sends no `claude_session`, so `build_session_args(None, None)`
returns `[]` (edp-pool/pty_launcher.py) and the CLI auto-generates an id the
pool never learns. This module pins the bar:

* every `spawn_planner` posts a FRESH uuid4 `claude_session`, and RETURNS it to
  the caller (`claude_session_id`) so suspend's manifest and resume's fork both
  have it without re-deriving;
* `spawn_planner(resume_session=X)` posts BOTH keys — the pair that makes the
  pool emit `--resume <base> --session-id <fork> --fork-session`;
* `spawn_worker` still posts NO `claude_session` (workers are disposable —
  reaped and re-dispatched, never forked). A regression guard against the
  scope creep of pinning everything;
* `sessions(recipe_id=...)` forwards `?recipe_id=`, and `sessions()` issues a
  request with NO query param (byte-identical to pre-W11).

The client stays MECHANICAL (W5/a2's durable lesson): it pins a uuid and
forwards what it is given. No tier/default policy lives here.

Assertions are on the REQUEST the client actually builds, via a stubbed httpx
client — the style of tests/test_w5_consult.py::
test_spawn_consult_client_omits_model_when_none. No pool, no network.
"""

import uuid

from edp_contracts import ToolOk

from edp_claude.clients import HttpPool


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._p = payload if payload is not None else {"session_id": "s:1"}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code // 100 != 2:
            raise AssertionError("unexpected status")


class _Client:
    """Fake httpx client: captures the posted body and the GET kwargs."""

    def __init__(self, post=None, get=None):
        self._post = post or _Resp()
        self._get = get or _Resp(200, [])
        self.bodies: list[dict] = []      # every /v1/spawn body, in order
        self.last_json = None
        self.get_calls: list[tuple] = []  # (url, kwargs) per GET

    async def post(self, url, json=None):
        self.bodies.append(json)
        self.last_json = json
        return self._post

    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self._get


def _pool(client):
    return HttpPool("http://p", client)


def _is_uuid4(s) -> bool:
    """A valid uuid4 STRING — not merely parseable (uuid.UUID accepts any
    version, and a non-4 version would not be a fresh random id)."""
    if not isinstance(s, str):
        return False
    try:
        u = uuid.UUID(s)
    except (ValueError, AttributeError, TypeError):
        return False
    return u.version == 4 and str(u) == s


# ── (a) every planner spawn pins a fresh uuid4 claude_session ───────────────
async def test_spawn_planner_always_pins_a_uuid4_claude_session():
    """Without this, build_session_args(None, None) → [] and the CLI invents a
    session id the pool never learns — W11's fork has nothing to fork."""
    c = _Client(post=_Resp(200, {"session_id": "planner:abc"}))
    res = await _pool(c).spawn_planner("rec1", "s1")

    assert isinstance(res, ToolOk)
    body = c.last_json
    assert "claude_session" in body, "a planner spawn MUST pin its session id"
    assert _is_uuid4(body["claude_session"]), body["claude_session"]
    # the rest of the body is untouched by the pin
    assert body["role"] == "planner"
    assert body["handle"] == "rec1:s1"
    assert body["parent_session"] == "rec1"
    # mechanical client: no model was asked for, so no model key is invented
    assert "model" not in body
    # no resume was asked for, so the key stays off the body entirely
    assert "resume_session" not in body


# ── (b) two successive planner spawns pin DIFFERENT ids ─────────────────────
async def test_two_planner_spawns_pin_different_sessions():
    """A per-spawn uuid, not a per-process constant — otherwise two planners
    would collide on one claude session and the second would resume the first."""
    c = _Client(post=_Resp(200, {"session_id": "planner:abc"}))
    pool = _pool(c)

    await pool.spawn_planner("rec1", "s1")
    await pool.spawn_planner("rec1", "s2")

    first, second = (b["claude_session"] for b in c.bodies)
    assert _is_uuid4(first) and _is_uuid4(second)
    assert first != second, "each planner spawn needs its own session id"


# ── (c) resume_session + claude_session travel together (the fork pair) ─────
async def test_resume_session_sends_both_keys_for_fork():
    """The pool emits `--resume <base> --session-id <fork> --fork-session` only
    when BOTH are present. A resume that dropped the fresh pin would MUTATE the
    suspended base instead of branching it."""
    c = _Client(post=_Resp(200, {"session_id": "planner:abc"}))
    res = await _pool(c).spawn_planner("rec1", "s1", resume_session="base-999")

    body = c.last_json
    assert body["resume_session"] == "base-999"          # the base to fork FROM
    assert _is_uuid4(body["claude_session"])             # the fresh fork id
    assert body["claude_session"] != "base-999"          # fork ≠ base
    # the returned id is the FORK, which is what the caller must persist
    assert res.data["claude_session_id"] == body["claude_session"]


# ── (d) the pinned id is returned to the caller (no re-derivation) ──────────
async def test_spawn_planner_returns_the_pinned_session_id():
    """suspend_recipe's manifest and resume_recipe's fork both need this id;
    neither should have to guess it."""
    c = _Client(post=_Resp(200, {"session_id": "planner:abc"}))
    res = await _pool(c).spawn_planner("rec1", "s1")

    assert isinstance(res, ToolOk)
    assert res.data["claude_session_id"] == c.last_json["claude_session"]
    assert _is_uuid4(res.data["claude_session_id"])
    # the pool's own session_id/handle are unchanged pass-throughs
    assert res.data["session_id"] == "planner:abc"
    assert res.data["handle"] == "rec1:s1"


# ── (e) REGRESSION GUARD: a worker spawn pins NOTHING ───────────────────────
async def test_spawn_worker_still_sends_no_claude_session():
    """Workers are disposable by design — reaped and re-dispatched fresh, never
    forked. Pinning a session here is scope creep; this guard fails loudly if a
    future change 'helpfully' pins everything."""
    c = _Client(post=_Resp(200, {"session_id": "worker:abc"}))
    res = await _pool(c).spawn_worker("plan1", "a1")

    assert "claude_session" not in c.last_json
    # byte-identical to pre-W11: exactly role + handle + parent_session
    assert c.last_json == {
        "role": "worker", "handle": "plan1:a1", "parent_session": "plan1",
    }
    # and nothing was pinned, so nothing is echoed back
    assert res.data["claude_session_id"] is None


# ── (f) sessions(): unfiltered stays bare; recipe_id rides as a query param ─
async def test_sessions_omits_query_param_when_unfiltered():
    c = _Client(get=_Resp(200, [{"handle": "h"}]))
    out = await _pool(c).sessions()

    assert out == [{"handle": "h"}]
    (url, kwargs), = c.get_calls
    assert url == "http://p/v1/sessions"
    # the omission idiom: no `params` kwarg at all, not `params=None`
    assert "params" not in kwargs
    assert kwargs == {}


async def test_sessions_forwards_recipe_id_as_query_param():
    c = _Client(get=_Resp(200, []))
    await _pool(c).sessions(recipe_id="r")

    (url, kwargs), = c.get_calls
    assert url == "http://p/v1/sessions"
    assert kwargs["params"] == {"recipe_id": "r"}
