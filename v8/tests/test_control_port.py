"""S3 (s-870e401942): the supervisor's control port is loopback-only and refuses a request without its
secret; the supervisor honours an admin stop, gives up on a crash loop and guards a pool stop."""

from __future__ import annotations

import http.client
import threading

import pytest

from edp8 import control, launcher, run_state, supervisor

TOKEN = "s3-test-secret"


@pytest.fixture
def server():
    calls: list[tuple[str, dict]] = []

    def dispatch(path, body):
        calls.append((path, body))
        return 200, {"ok": True, "path": path}

    srv, port = control.serve(dispatch, port=0, token=TOKEN)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, port, calls
    srv.shutdown()
    srv.server_close()


def req(port, method="POST", path="/status", headers=None, body=b"{}"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    h.update(headers or {})
    c.request(method, path, body=body if method == "POST" else None, headers=h)
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


def test_binds_loopback_literal_only(server):
    srv, port, _ = server
    assert srv.server_address[0] == "127.0.0.1"


def test_secret_host_origin_and_method_rules(server):
    _, port, calls = server
    assert req(port, headers={control.HEADER: TOKEN}) == 200
    assert calls == [("/status", {})]
    assert req(port) == 403                                                     # no secret
    assert req(port, headers={control.HEADER: "wrong"}) == 403                  # wrong secret
    assert req(port, headers={control.HEADER: TOKEN, "Host": f"evil.example:{port}"}) == 403  # rebinding
    assert req(port, headers={control.HEADER: TOKEN, "Origin": "http://127.0.0.1:9400"}) == 403  # a browser
    assert req(port, "GET", headers={control.HEADER: TOKEN}) == 405
    assert req(port, "DELETE", headers={control.HEADER: TOKEN}) == 405
    assert len(calls) == 1  # none of the refused requests reached the dispatcher


@pytest.fixture
def quiet_state(monkeypatch):
    monkeypatch.setattr(run_state, "mark_probe", lambda *a, **k: None)
    monkeypatch.setattr(run_state, "update", lambda *a, **k: None)


def _sup(probe=lambda s: False, clock=None):
    restarts, events = [], []
    sup = supervisor.Supervisor(["board", "pool"], probe=probe, alive=lambda s: False,
                                restart=lambda s, r: restarts.append(s), emit=lambda s, r, *a: events.append((s, r)),
                                threshold=1, clock=clock or (lambda: 100.0))
    return sup, restarts, events


def test_crash_loop_marks_failed_instead_of_restarting_forever(quiet_state):
    sup, restarts, events = _sup(probe=lambda s: s != "board")
    for _ in range(supervisor.CRASH_LOOP_MAX + 3):
        sup.tick()
    assert restarts == ["board"] * supervisor.CRASH_LOOP_MAX
    assert sup.failed == {"board"}
    assert events.count(("board", "crash_loop")) == 1
    sup.resume("board")  # an admin start clears it
    assert "board" not in sup.failed


def test_admin_stop_pauses_and_pool_stop_with_seats_needs_force(quiet_state, monkeypatch):
    sup, restarts, _ = _sup()
    stopped = []
    monkeypatch.setattr(launcher, "stop", lambda svc, **k: stopped.append(svc) or
                        {"service": svc, "state": "stopped", "killed": [], "survivors": []})
    monkeypatch.setattr(launcher, "live_seats", lambda: ["engineer.x"])
    dispatch = supervisor.make_dispatch(sup, lambda *a: None)

    code, out = dispatch("/services/pool/stop", {})
    assert code == 409 and out["seats"] == ["engineer.x"] and stopped == []
    code, _ = dispatch("/services/pool/stop", {"force": True})
    assert code == 200 and stopped == ["pool"]

    code, _ = dispatch("/services/board/stop", {})
    assert code == 200 and sup.paused == {"pool", "board"}
    sup.tick()
    assert restarts == []  # a stopped service is never restarted behind the admin's back

    assert dispatch("/services/nope/start", {})[0] == 404
    assert dispatch("/other", {})[0] == 404


def test_shutdown_ends_the_run_loop_at_once(quiet_state):
    sup, _, _ = _sup(probe=lambda s: True)
    dispatch = supervisor.make_dispatch(sup, lambda *a: None)
    t = threading.Thread(target=sup.run, kwargs={"interval": 60.0}, daemon=True)
    t.start()
    assert dispatch("/shutdown", {})[0] == 200
    t.join(timeout=5)
    assert not t.is_alive()
