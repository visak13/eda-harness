"""S15 task 4 (s-6c2f5a8593): p-c4adfd0f — topic_research's fetch failures name host, cause class and next step.

A bare `fetching <url> failed: ConnectError` told the seat nothing; on the fleet host the real cause was
WinError 10013 (outbound sockets forbidden for the process). Every class is asserted without the network.
p-59f06ccc (12,000-char cut, no continuation) is pinned by test_s23_t6_findings.py::N1; p-ff30576a and
p-fc50ec61 by test_sme_optin.py (S6 514bba9).
"""

from __future__ import annotations

import http.server
import socket
import ssl
import threading
import time

import httpx
import pytest
from test_topics import _topic, board, client, dns, pool, tokens  # noqa: F401 — fixtures
from test_topics import ADMIN, OWNER  # noqa: F401

from edp8 import topics
from edp8.board import BoardError

URL = "https://www.skills.sh/api/search?q=python"


def _raised(exc: Exception, cause: BaseException | None = None) -> httpx.HTTPError:
    exc.__cause__ = cause
    return exc


def _err(exc: Exception) -> BoardError:
    return topics._fetch_error(URL, exc)


@pytest.mark.parametrize("exc, cls, words", [
    (_raised(httpx.ConnectError("[Errno 11001] getaddrinfo failed"), socket.gaierror(11001, "getaddrinfo failed")),
     "dns", "cannot resolve"),
    (_raised(httpx.ConnectError("boom"), ConnectionRefusedError(10061, "refused")), "refused", "refused"),
    (_raised(httpx.ConnectError("[WinError 10013] An attempt was made to access a socket in a way forbidden"),
             OSError(10013, "forbidden by its access permissions")), "blocked", "firewall or sandbox"),
    (_raised(httpx.ConnectError("tls"), ssl.SSLCertVerificationError("certificate verify failed")),
     "tls", "TLS handshake"),
    (httpx.ConnectTimeout("timed out"), "timeout", "too slowly"),
    (httpx.ReadTimeout("took longer"), "timeout", "too slowly"),
    (httpx.ProxyError("407"), "proxy", "PROXY"),
    (httpx.ConnectError("odd"), "connect", "cannot reach the site"),
    (httpx.RemoteProtocolError("garbled"), "http", "retry later"),
])
def test_each_failure_class_names_host_class_and_next_step(exc, cls, words):
    e = _err(exc)
    assert e.code == "unavailable"
    assert f"({cls}, {type(exc).__name__})" in e.message and "www.skills.sh" in e.message
    assert words in (e.message + " " + e.hint)
    assert e.message != f"fetching {URL} failed: {type(exc).__name__}"  # never the bare class name again


def test_blocked_class_keeps_the_os_detail():
    e = _err(_raised(httpx.ConnectError("x"), OSError(10013, "forbidden by its access permissions")))
    assert "forbidden by its access permissions" in e.message and "outbound https" in e.hint


def test_a_real_refused_connect_is_classed_refused():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens now
    with pytest.raises(httpx.ConnectError) as ei:
        httpx.get(f"http://127.0.0.1:{port}/", timeout=3, trust_env=False)
    e = topics._fetch_error(f"http://127.0.0.1:{port}/", ei.value)
    assert "(refused, ConnectError)" in e.message or "(blocked, ConnectError)" in e.message, e.message


def test_a_real_slow_server_is_classed_timeout():
    class Slow(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            time.sleep(1.5)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(httpx.TimeoutException) as ei:
            httpx.get(f"http://127.0.0.1:{srv.server_port}/", timeout=0.3, trust_env=False)
    finally:
        srv.shutdown()
    assert "(timeout, " in topics._fetch_error(f"http://127.0.0.1:{srv.server_port}/", ei.value).message


def test_fetch_raises_the_classed_error_not_a_bare_class(monkeypatch):
    def down(url):
        raise _raised(httpx.ConnectError("x"), socket.gaierror(11001, "getaddrinfo failed"))
    monkeypatch.setattr(topics, "FETCH", down)
    with pytest.raises(BoardError) as ei:
        topics.fetch(URL, topics.BASE_HOSTS)
    assert "(dns, ConnectError)" in ei.value.message and "www.skills.sh" in ei.value.message and ei.value.hint


def test_a_redirect_to_a_disallowed_host_is_refused_with_the_allowed_hosts(monkeypatch):
    monkeypatch.setattr(topics, "FETCH", lambda url: (302, b"", "https://evil.example.com/steal"))
    with pytest.raises(BoardError) as ei:
        topics.fetch("https://github.com/a/b", topics.BASE_HOSTS)
    assert ei.value.code == "forbidden" and "outside this topic's research hosts" in ei.value.message
    assert "github.com" in ei.value.hint


def test_the_research_route_returns_the_classed_reason(client, board, tokens, monkeypatch):
    from test_topics import _seat

    def down(url):
        raise _raised(httpx.ConnectError("x"), OSError(10013, "forbidden by its access permissions"))
    monkeypatch.setattr(topics, "FETCH", down)
    t = _topic(client, tags=["python"])["topic"]
    board.run_pending_pairings()
    sme = _seat(client, tokens, t)
    out = client.post(f"/v1/topics/{t['id']}/research", json={"query": "python testing"}, headers=sme).json()
    assert not out["ok"] and "(blocked, ConnectError)" in out["error"]["message"] and "outbound https" in out["hint"]
