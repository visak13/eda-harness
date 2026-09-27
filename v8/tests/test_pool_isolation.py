"""qa m-c4f23e49f0 (SEVERE): a private Playwright spec board on spare ports showed the fleet pool's capacity and its
Admin "Save caps" could write the fleet's limits. With no EDP_POOL_URL the pool URL was the registry's fixed
`http://127.0.0.1:9301` (and pool_adapter cached it at import, from a seat shell's env). Now it derives from THIS
home's pool.host/pool.port and is read per call; the e2e harness and the pytest conftest pin the pool port to a port
nothing listens on (web/e2e/hermeticEnv.ts deadServiceEnv, tests/conftest.py no_pool_watch)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from admin_support import ADMIN_H, make_env
from edp8 import pool_adapter, settings

#: a seat shell's identity and fleet pointers, minus EDP_POOL_URL (the e2e harness and conftest strip that one)
SEAT_ENV = {"EDP_HANDLE": "engineer.t-x", "EDP8_PARTICIPANT": "engineer.t-x", "EDP8_TOKEN": "seat-token",
            "EDP8_BOARD_URL": "http://127.0.0.1:9400", "EDP_ROLE": "engineer"}


class StandInPool:
    """An HTTP listener standing in for "some other home's pool": it records every request it gets."""

    def __init__(self) -> None:
        seen = self.seen = []

        class H(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                seen.append((self.command, self.path, self.rfile.read(n) if n else b""))
                body = json.dumps({"max_total_shells": 7, "max_live_shells": 14, "usage": {}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _answer

            def log_message(self, *a) -> None:
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def stand_in():
    p = StandInPool()
    yield p
    p.close()


def test_the_pool_url_is_this_homes_pool_port_read_per_call(monkeypatch):
    monkeypatch.setenv("EDP_POOL_PORT", "12345")
    assert pool_adapter.pool_url() == "http://127.0.0.1:12345"
    monkeypatch.setenv("EDP_POOL_HOST", "0.0.0.0")  # a bind-all pool is still called on loopback
    assert pool_adapter.pool_url() == "http://127.0.0.1:12345"
    monkeypatch.setenv("EDP_POOL_URL", "http://10.0.0.5:9999/")
    assert pool_adapter.pool_url() == "http://10.0.0.5:9999"
    assert settings.setting("EDP_POOL_URL").default_doc == "http://<pool.host>:<pool.port>"


def test_the_suite_never_points_at_the_default_pool():
    # the conftest pins the port: an unmocked pool call in any test fails instead of reaching the fleet's :9301
    assert not settings.is_set("EDP_POOL_URL")
    assert ":9301" not in pool_adapter.pool_url()
    assert not pool_adapter.reachable(timeout=2.0)


def test_a_board_with_a_seat_env_reaches_no_pool_but_its_own(tmp_path, monkeypatch, stand_in):
    for k, v in SEAT_ENV.items():
        monkeypatch.setenv(k, v)
    e = make_env(tmp_path, monkeypatch)
    caps = {"max_total_shells": 3}
    got = e.client.get("/v1/admin/capacity", headers=ADMIN_H)
    assert got.status_code == 503 and "pool unreachable" in got.text, got.text  # no other home's caps shown
    assert e.client.put("/v1/admin/capacity", headers=ADMIN_H, json=caps).status_code == 503
    assert stand_in.seen == [], "a board without its own pool must not read or write another home's caps"
    # the same board configured with a pool port reaches exactly that pool: the port decides, never a fixed default
    monkeypatch.setenv("EDP_POOL_PORT", str(stand_in.port))
    assert e.client.put("/v1/admin/capacity", headers=ADMIN_H, json=caps).status_code == 200
    assert any(m == "POST" and p == "/v1/limits" and json.loads(b) == caps for m, p, b in stand_in.seen), stand_in.seen
