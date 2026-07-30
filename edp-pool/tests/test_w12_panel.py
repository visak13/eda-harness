"""W12 — the panel surface: the three guards, and the three honest absences.

THE THREE GUARDS ARE NOT THREE LAYERS OF ONE FENCE. Kept distinct here on
purpose, because collapsing them is how a security story becomes a slogan:

  A2  refuses to SERVE when the pool is bound off-loopback.
  A3  refuses a cross-origin browser POST (CSRF) and a rebound Host.
  A1  stamps every panel-forwarded message with the CHANNEL it arrived on.

WHAT A1 PROVES, EXACTLY — and the second sentence is the one that matters:
  TRUE : no panel-submitted message reaches the broker unstamped, and no code
         path writes a panel message without the stamp.
  NOT CLAIMED, ANYWHERE, BY ANY TEST OR ARTIFACT: that the stamp establishes
         who composed a message. It cannot. The panel is unauthenticated on
         loopback by the user's deliberate choice, so any local process can
         reach it exactly as the browser can — and its message is then stamped
         `via=panel`, truthfully. Separately, `broker_send` takes `from_` as a
         parameter, so `from` is self-asserted system-wide. The stamp records
         the PATH TRAVELLED. Authorship is established out-of-band or not at all.
         `test_no_artifact_claims_the_stamp_certifies_authorship` pins that no
         file in this change says otherwise.
"""

import subprocess
import sys
import time

import psutil
import pytest
from edp_contracts import BrokerMessage, is_registered
from fastapi.testclient import TestClient

from edp_pool import proctree, service
from edp_pool.service import PANEL_SENDER, create_app, is_loopback_host
from edp_pool.spawner import FakeSpawner

_SRC = service.__file__
_LOOPBACK_BASE = "http://127.0.0.1:9301"


class _FakeResp:
    status_code = 200

    def __init__(self, payload=None):
        self._p = payload if payload is not None else {"msg_id": "ok"}

    def json(self):
        return self._p


class _CapturingBroker:
    """Stands in for the broker process. Records exactly what the pool forwards
    — which is the only place the stamp can be observed as it lands."""

    posted: list = []
    got: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        _CapturingBroker.posted.append((url, json))
        return _FakeResp()

    async def get(self, url, params=None):
        _CapturingBroker.got.append((url, params))
        return _FakeResp([])


@pytest.fixture
def broker(monkeypatch):
    _CapturingBroker.posted, _CapturingBroker.got = [], []
    monkeypatch.setattr(service.httpx, "AsyncClient", _CapturingBroker)
    return _CapturingBroker


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_POOL_HOST", "127.0.0.1")
    monkeypatch.setenv("EDP_POOL_PAUSE_TOKENS", str(tmp_path / "tok"))
    return create_app(FakeSpawner(), broker_url="http://broker:9300",
                      state_path=tmp_path / "state.json")


@pytest.fixture
def client(app):
    return TestClient(app, base_url=_LOOPBACK_BASE)


# ══ A2 — fail closed off loopback ═════════════════════════════════════════

def test_is_loopback_host_rejects_the_value_that_makes_this_guard_necessary():
    for good in ("127.0.0.1", "127.0.0.1:9301", "localhost", "localhost:9301",
                 "::1", "[::1]:9301", "127.5.5.5"):
        assert is_loopback_host(good), good
    for bad in ("0.0.0.0", "0.0.0.0:9301", "192.168.1.10", "evil.com",
                "", None, "10.0.0.1:9301"):
        assert not is_loopback_host(bad), bad


def test_panel_refuses_to_serve_when_the_pool_is_bound_off_loopback(
        client, monkeypatch):
    """`main.py` reads EDP_POOL_HOST straight into `uvicorn.run(host=...)`.
    Loopback is a DEFAULT, not an invariant — one env var exposes the panel's
    process-suspending endpoints to the network."""
    monkeypatch.setenv("EDP_POOL_HOST", "0.0.0.0")
    r = client.get("/panel")
    assert r.status_code == 403
    assert "loopback" in r.json()["refused"].lower()
    assert "0.0.0.0" in r.json()["refused"]


def test_every_mutating_panel_endpoint_fails_closed_off_loopback(
        client, monkeypatch):
    monkeypatch.setenv("EDP_POOL_HOST", "0.0.0.0")
    for method, path in [
        ("POST", "/v1/shells/p:a1/pause"),
        ("POST", "/v1/shells/p:a1/resume"),
        ("POST", "/v1/recipes/r1/pause"),
        ("POST", "/v1/recipes/r1/resume"),
        ("POST", "/v1/broker/publish"),
        ("POST", "/v1/panel/spawn_defaults"),
        ("GET", "/v1/panel/shells"),
        ("GET", "/v1/shells/p:a1/pause"),
    ]:
        r = client.request(method, path, json={})
        assert r.status_code == 403, f"{method} {path} served off loopback"


def test_the_guard_reads_the_env_at_request_time_not_import_time(
        client, monkeypatch):
    monkeypatch.setenv("EDP_POOL_HOST", "0.0.0.0")
    assert client.get("/v1/panel/shells").status_code == 403
    monkeypatch.setenv("EDP_POOL_HOST", "127.0.0.1")
    assert client.get("/v1/panel/shells").status_code == 200


def test_the_mcp_surface_is_deliberately_unguarded(client, monkeypatch):
    """DELIBERATELY UNGUARDED, and recorded as such. Every pool-spawned shell
    calls these over plain HTTP with no `Origin`; an A3 check here would refuse
    the entire fleet. This test exists so that an unguarded-on-purpose endpoint
    is distinguishable from a forgotten one."""
    monkeypatch.setenv("EDP_POOL_HOST", "0.0.0.0")   # even then:
    for path in ("/v1/locks", "/v1/sessions", "/v1/liveness/nope"):
        r = client.get(path, headers={"Origin": "http://evil.com"})
        assert r.status_code == 200, f"{path} must stay reachable by shells"


# ══ A3 — Origin / Host (CSRF, DNS rebinding) ══════════════════════════════

def test_cross_origin_post_is_refused(client):
    r = client.post("/v1/shells/p:a1/pause",
                    headers={"Origin": "http://evil.com"})
    assert r.status_code == 403 and "cross-origin" in r.json()["refused"]


def test_same_origin_post_is_allowed(client):
    r = client.post("/v1/shells/p:a1/pause",
                    headers={"Origin": _LOOPBACK_BASE})
    assert r.status_code == 200          # refused by lock lookup, not by A3
    assert "no live shell" in r.json()["refused"]


def test_origin_that_is_loopback_but_not_our_host_is_refused(client):
    r = client.post("/v1/shells/p:a1/pause",
                    headers={"Origin": "http://127.0.0.1:8888"})
    assert r.status_code == 403 and "does not match Host" in r.json()["refused"]


def test_rebound_host_header_is_refused(client):
    r = client.post("/v1/shells/p:a1/pause", headers={"Host": "evil.com"})
    assert r.status_code == 403 and "DNS-rebinding" in r.json()["refused"]


def test_a_request_with_no_origin_is_allowed_and_that_is_the_point(client):
    """A3 is a browser guard. A non-browser client sends no `Origin` and passes.
    This is stated as a test rather than left implicit, because A3's reach is
    exactly what A1's residual section is about."""
    r = client.post("/v1/shells/p:a1/pause")
    assert r.status_code == 200 and "no live shell" in r.json()["refused"]


# ══ A1 — the channel stamp ════════════════════════════════════════════════

def _published(broker):
    assert broker.posted, "nothing reached the broker"
    url, payload = broker.posted[-1]
    assert url.endswith("/v1/publish")
    return payload


def test_a_panel_message_reaches_the_broker_stamped(client, broker):
    r = client.post("/v1/broker/publish",
                    json={"to": "recipe-x", "kind": "answer",
                          "body": {"answer": "yes"}})
    assert r.status_code == 200
    p = _published(broker)
    assert p["body"]["channel"] == {
        "via": "panel", "channel": "panel-http", "authenticated": False,
        "stamped_at": p["body"]["channel"]["stamped_at"],
        "remote_addr": p["body"]["channel"]["remote_addr"],
    }
    assert p["body"]["answer"] == "yes"      # the payload survives the stamp
    assert p["from"] == PANEL_SENDER


def test_the_stamp_cannot_be_omitted(client, broker):
    """Every adversarial shape a caller can send, and every one arrives stamped.
    Deleting the stamp line in `stamp_panel_channel` turns each of these RED."""
    cases = [
        {"to": "r", "kind": "answer"},                                # no body
        {"to": "r", "kind": "answer", "body": {}},                    # empty
        {"to": "r", "kind": "steer", "body": {"channel": "user"}},    # forged
        {"to": "r", "kind": "answer",
         "body": {"channel": {"via": "keyboard", "authenticated": True}}},
        {"to": "r", "kind": "review_comments",
         "body": {"brief": "1.md", "comments": []}},
    ]
    for c in cases:
        r = client.post("/v1/broker/publish", json=c)
        assert r.status_code == 200, c
        ch = _published(broker)["body"]["channel"]
        assert ch["via"] == "panel", c
        assert ch["authenticated"] is False, c


def test_a_caller_supplied_stamp_is_discarded_not_merged(client, broker):
    client.post("/v1/broker/publish", json={
        "to": "r", "kind": "answer",
        "body": {"channel": {"via": "keyboard", "authenticated": True,
                             "extra": "please-trust-me"}}})
    ch = _published(broker)["body"]["channel"]
    assert ch["authenticated"] is False
    assert "extra" not in ch, "a stamp a caller can contribute to is not a stamp"


def test_a_panel_message_cannot_present_itself_as_another_sender(client, broker):
    client.post("/v1/broker/publish",
                json={"from": "recipe-x-s28", "to": "r", "kind": "answer",
                      "body": {}})
    assert _published(broker)["from"] == PANEL_SENDER


def test_a_panel_message_is_distinguishable_from_one_that_never_touched_it(
        client, broker):
    """The property the stamp DOES deliver: a reader can tell which channel a
    message arrived on. Nothing here says who wrote either one."""
    client.post("/v1/broker/publish",
                json={"to": "r", "kind": "answer", "body": {"answer": "ok"}})
    panel_msg = BrokerMessage.model_validate(_published(broker))
    direct = BrokerMessage.model_validate({
        "msg_id": "m2", "ts": "2026-07-10T00:00:00+00:00",
        "from": "some-shell", "to": "r", "kind": "answer",
        "body": {"answer": "ok"}})

    assert panel_msg.body["channel"]["via"] == "panel"
    assert "channel" not in direct.body
    assert panel_msg.from_ == PANEL_SENDER and direct.from_ == "some-shell"


def test_publish_refuses_a_non_object_body(client, broker):
    r = client.post("/v1/broker/publish",
                    json={"to": "r", "kind": "answer", "body": "a string"})
    assert r.status_code == 400
    assert not broker.posted, "an unstampable message must not be forwarded"


def test_publish_requires_to_and_kind(client, broker):
    assert client.post("/v1/broker/publish", json={"kind": "answer"}).status_code == 400
    assert client.post("/v1/broker/publish", json={"to": "r"}).status_code == 400
    assert not broker.posted


def test_panel_publish_is_the_only_route_to_the_broker():
    """"No code path writes a panel message without the stamp" — pinned, not
    asserted. Exactly one publish call site exists in service.py, and the stamp
    runs before it. A second call site is how the stamp gets bypassed."""
    src = open(_SRC, encoding="utf-8").read()
    assert src.count("/v1/publish") == 1, (
        "a second route to the broker's publish endpoint appeared in "
        "service.py; it bypasses stamp_panel_channel")
    assert src.index("stamp_panel_channel(payload") < src.index("/v1/publish")


def test_review_comments_is_registered_so_the_broker_accepts_it():
    """The broker validates kinds in its OWN process and fails CLOSED. Without
    the edp-contracts registration the panel's whole review feature is rejected
    on arrival."""
    assert is_registered("review_comments")
    m = BrokerMessage.model_validate({
        "msg_id": "m", "ts": "2026-07-10T00:00:00+00:00", "from": "panel",
        "to": "recipe-x", "kind": "review_comments",
        "body": {"brief": "1.md",
                 "comments": [{"anchor_quote": "q", "comment": "c"}]}})
    assert m.kind == "review_comments"


# ══ The three honest absences ═════════════════════════════════════════════

def test_last_output_ts_is_reported_absent_with_its_cause_not_substituted(app):
    """F3. DESIGN-v6 names `last_output_ts` as the Shells view's liveness
    column. In monitor mode it CANNOT populate — ConsoleLaunch has no drain log.
    The row carries the absence and the reason, and no substitute value."""
    svc = _svc(app)
    svc.spawn("worker", "p:a1", None, mode="monitor")
    svc.spawn("worker", "p:a2", None, mode="headless")
    rows = {r["handle"]: r for r in svc.panel_shells()}

    mon = rows["p:a1"]
    assert mon["last_output_ts"] is None
    assert mon["last_output_available"] is False
    assert "monitor mode" in mon["last_output_reason"]
    assert mon["spawn_mode"] == "monitor"

    sid = svc.locks["p:a2"]
    svc.spawner.set_output_ts(sid, 1720000000.5)
    row = {r["handle"]: r for r in svc.panel_shells()}["p:a2"]
    assert row["last_output_available"] is True
    assert row["last_output_ts"] == 1720000000.5


def test_a_row_carries_no_stored_paused_boolean(app):
    """F0, structurally: the session row the pool persists has no `paused` key
    to go stale. The panel's indicator is a measurement, or it is `unknown`."""
    svc = _svc(app)
    svc.spawn("worker", "p:a1", None, mode="monitor")
    sid = svc.locks["p:a1"]
    assert "paused" not in svc.sessions[sid]
    assert not any("paus" in k for k in svc.sessions[sid])

    pause = svc.panel_shells()[0]["pause"]
    # FakeSpawner has no real pid → the honest answer is "unknown", never
    # "running", and it carries the reason.
    assert pause["frozen"] is None and pause["state"] == "unknown"
    assert "pid" in pause["reason"]


def test_the_cost_view_renders_no_number_it_did_not_measure():
    """d77 removed `cost_report` from the build. The view says so and shows
    nothing — rather than deriving a plausible figure from shell counts."""
    html = _panel_html()
    assert "d77" in html
    assert "Not built, deliberately" in html
    assert "cost_report" in html


def test_the_panel_never_offers_skip_permissions():
    html = _panel_html()
    assert "EDP_SKIP_PERMISSIONS" in html, "it must be named as absent…"
    assert "not here" in html                       # …and only as absent
    for forbidden in ("id=\"sd_skip", "skip_permissions:", "checkbox\" id=\"sd_perm"):
        assert forbidden not in html


#: Phrases that would overstate what A1 delivers. The stamp records the channel
#: a message arrived on. Any artifact asserting it establishes WHO SENT the
#: message — in prose, in a comment, or compressed into an identifier like
#: `user_sourced` — is a fabricated licence, and reads as authorship to every
#: future reader. A guard remembered by a sentence broader than the guard is
#: worse than no guard.
_OVERCLAIMS = ("cannot forge", "user_sourced", "user-sourced", "user_answer",
               "panel_sourced", "proves the user", "certifies that a human")


def test_no_shipped_artifact_overstates_what_the_stamp_delivers():
    """Scans the code this action ships (not this test, which must name the
    banned phrases in order to ban them)."""
    import inspect

    from edp_pool import pause_watchdog, spawn_defaults
    shipped = {
        "service.py": inspect.getsource(service),
        "proctree.py": inspect.getsource(proctree),
        "pause_watchdog.py": inspect.getsource(pause_watchdog),
        "spawn_defaults.py": inspect.getsource(spawn_defaults),
        "panel.html": _panel_html(),
    }
    for name, src in shipped.items():
        low = src.lower()
        for phrase in _OVERCLAIMS:
            assert phrase not in low, f"{name} overclaims: {phrase!r}"


# ══ F0 end-to-end, against a real process this test owns ══════════════════

def _signal_tree_now(pid, action):
    for p in proctree.tree_pids(pid):
        try:
            getattr(psutil.Process(p), action)()
        except psutil.Error:
            pass


def test_pause_state_follows_the_world_not_the_pool(app):
    """The pool never wrote a flag. It reports `frozen` because the threads ARE
    frozen, and `running` the moment they are not — even though the suspend and
    the resume both happened behind its back, through psutil directly."""
    svc = _svc(app)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        ct = psutil.Process(proc.pid).create_time()
        for _ in range(40):                     # let the tree acquire its child
            if len(proctree.tree_pids(proc.pid)) >= 2:
                break
            time.sleep(0.1)

        svc.spawn("worker", "p:a1", None, mode="monitor")
        sid = svc.locks["p:a1"]
        svc.sessions[sid]["proc"] = {"pid": proc.pid, "create_time": ct}

        assert svc.pause_state("p:a1")["state"] == "running"
        _signal_tree_now(proc.pid, "suspend")
        assert svc.pause_state("p:a1")["state"] == "frozen"
        _signal_tree_now(proc.pid, "resume")
        assert svc.pause_state("p:a1")["state"] == "running"
    finally:
        _signal_tree_now(proc.pid, "resume")
        proctree.kill_process_tree(proc.pid)


def test_pause_refuses_a_handle_with_no_registry_row(app):
    svc = _svc(app)
    assert "no live shell" in svc.pause_shell("not-a-handle")["refused"]
    assert svc.pause_state("not-a-handle")["frozen"] is None


def test_pause_refuses_a_row_without_a_create_time(app):
    """The 198-shells guard, at the pause seam: a row that cannot defeat pid
    reuse is never signalled."""
    svc = _svc(app)
    svc.spawn("worker", "p:a1", None, mode="monitor")
    sid = svc.locks["p:a1"]
    svc.sessions[sid]["proc"] = {"pid": 4242, "create_time": None}
    assert "create_time" in svc.pause_shell("p:a1")["refused"]


def test_recipe_fanout_enumerates_the_registry_and_nothing_else(app):
    svc = _svc(app)
    svc.spawn("planner", "recipe-a:s1", None)
    svc.spawn("worker", "recipe-a-s1:a1", None)
    svc.spawn("worker", "recipe-b-s1:a1", None)
    out = svc.pause_recipe("recipe-a")
    assert sorted(out["handles"]) == ["recipe-a-s1:a1", "recipe-a:s1"]
    assert "recipe-b-s1:a1" not in out["handles"]
    # FakeSpawner rows have no pid → every one REFUSES rather than guessing
    assert out["paused"] == 0
    assert all("pid" in r["refused"] for r in out["results"].values())


def test_recipe_fanout_over_an_unknown_recipe_touches_nothing(app):
    out = _svc(app).pause_recipe("no-such-recipe")
    assert out["handles"] == [] and out["paused"] == 0


# ── helpers ───────────────────────────────────────────────────────────────

def _svc(app):
    return app.state.svc


def _panel_html():
    from pathlib import Path
    p = Path(service.__file__).resolve().parents[2] / "static" / "panel.html"
    return p.read_text(encoding="utf-8")
