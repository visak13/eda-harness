"""The ONE shared MCP server (2026-09-06): per-role endpoints, header identity, stateless."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time

os.environ.setdefault("EDP8_EMBEDDER", "none")

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

import edp8
from edp8 import mcp_server
from edp8.board import Board
from edp8.bundles import ROLE_BUNDLES
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    def __init__(self, app, port):
        self.cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(self.cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture
def stack(monkeypatch):
    """A real board on one port and the shared MCP server on another."""
    board = Board(Store(":memory:"))
    bport, mport = _free_port(), _free_port()
    board_app = create_app(board, admin_token="t")
    tc = TestClient(board_app)
    for pid, role, typ in [("owner", "owner", "human"), ("eng.s1", "engineer", "agent"), ("arch.e1", "architect", "agent")]:
        assert tc.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=ADMIN).json()["ok"]
    monkeypatch.setenv("EDP8_BOARD_URL", f"http://127.0.0.1:{bport}")
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "t")
    with _Server(board_app, bport), _Server(mcp_server.build_http_app(), mport):
        yield {"mcp": f"http://127.0.0.1:{mport}", "board": f"http://127.0.0.1:{bport}"}


async def _call(url: str, headers: dict, tool: str | None = None, **args):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(headers=headers, timeout=30) as hc:
        async with streamable_http_client(url, http_client=hc) as (r, w):
            async with ClientSession(r, w) as c:
                await c.initialize()
                tools = await c.list_tools()
                names = [t.name for t in tools.tools]
                if tool is None:
                    return names, None
                res = await c.call_tool(tool, args)
                return names, res


def _run(coro):
    return asyncio.run(coro)


def test_healthz_reports_version_and_roles(stack):
    h = httpx.get(f"{stack['mcp']}/healthz").json()
    assert h["ok"] and h["transport"] == "streamable-http/stateless"
    assert h["version"] == edp8.__version__ and h["git_rev"]  # the launcher's stray check compares `version`
    assert set(h["roles"]) == set(ROLE_BUNDLES)


def test_per_role_endpoint_serves_that_roles_tools_only(stack):
    eng_names, _ = _run(_call(f"{stack['mcp']}/mcp/engineer", {"X-Participant": "eng.s1"}))
    own_names, _ = _run(_call(f"{stack['mcp']}/mcp/owner", {"X-Participant": "owner"}))
    assert set(eng_names) == set(ROLE_BUNDLES["engineer"])
    assert set(own_names) == set(ROLE_BUNDLES["owner"])
    assert "close_self" in eng_names and "close_self" not in own_names


def test_identity_comes_from_the_request_header(stack):
    import json
    _, res = _run(_call(f"{stack['mcp']}/mcp/engineer", {"X-Participant": "eng.s1", "X-Session": "sid-1"}, "whoami"))
    out = json.loads(res.content[0].text)
    assert out["ok"] and out["value"]["participant"]["id"] == "eng.s1"
    assert out["value"]["server_version"] == mcp_server.VERSION
    _, res2 = _run(_call(f"{stack['mcp']}/mcp/architect", {"X-Participant": "arch.e1"}, "whoami"))
    assert json.loads(res2.content[0].text)["value"]["participant"]["id"] == "arch.e1"


def test_concurrent_callers_keep_their_own_identity(stack):
    import json

    async def both():
        a = _call(f"{stack['mcp']}/mcp/engineer", {"X-Participant": "eng.s1"}, "whoami")
        b = _call(f"{stack['mcp']}/mcp/architect", {"X-Participant": "arch.e1"}, "whoami")
        return await asyncio.gather(*[a, b] * 3)

    results = _run(both())
    ids = [json.loads(r[1].content[0].text)["value"]["participant"]["id"] for r in results]
    assert ids == ["eng.s1", "arch.e1"] * 3


# --------------------------------------------------------------- §24.1(c) X-Token forwarded end-to-end
@pytest.fixture
def public_stack(tmp_path, monkeypatch):
    """A PUBLIC-mode board (tokens.json, fail-closed) behind the shared MCP proxy. A minted-token
    seat must authenticate through the proxy — the proxy forwards X-Token, it does not substitute
    its own process env (client.py:35 was the bug: the proxy's EDP8_TOKEN, not the seat's)."""
    import json as _json
    tf = tmp_path / "tokens.json"
    tf.write_text(_json.dumps({"owner": "ownersecret", "agents": {"eng.s1": "engsecret"}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_PUBLIC_URL", "http://host.example:9400")
    monkeypatch.setenv("EDP8_TOKENS", str(tf))
    monkeypatch.delenv("EDP8_TOKEN", raising=False)  # the proxy process holds NO seat secret
    board = Board(Store(":memory:"))
    bport, mport = _free_port(), _free_port()
    board_app = create_app(board, admin_token="realsecret")
    tc = TestClient(board_app)
    for pid, role, typ in [("owner", "owner", "human"), ("eng.s1", "engineer", "agent")]:
        assert tc.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                       headers={"X-Admin": "realsecret"}).json()["ok"]
    monkeypatch.setenv("EDP8_BOARD_URL", f"http://127.0.0.1:{bport}")
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "realsecret")
    with _Server(board_app, bport), _Server(mcp_server.build_http_app(), mport):
        yield {"mcp": f"http://127.0.0.1:{mport}", "board": f"http://127.0.0.1:{bport}"}


def test_minted_token_authenticates_through_the_proxy(public_stack):
    import json
    _, res = _run(_call(f"{public_stack['mcp']}/mcp/engineer",
                        {"X-Participant": "eng.s1", "X-Token": "engsecret"}, "whoami"))
    out = json.loads(res.content[0].text)
    assert out["ok"] and out["value"]["participant"]["id"] == "eng.s1"


def test_missing_token_is_refused_through_the_proxy(public_stack):
    import json
    _, res = _run(_call(f"{public_stack['mcp']}/mcp/engineer", {"X-Participant": "eng.s1"}, "whoami"))
    out = json.loads(res.content[0].text)
    assert out.get("ok") is not True  # header-only is 401 at the board → not an ok envelope


# --------------------------------------------------------------- t-3e246b5e32 (a) tools follow the board role
@pytest.fixture
def expert_stack(tmp_path, monkeypatch):
    """PUBLIC-mode board with an expert (a human linked to one Library topic) and an engineer seat."""
    import json as _json
    tf = tmp_path / "tokens.json"
    tf.write_text(_json.dumps({"owner": "ownersecret", "exp.ada": "expsecret",
                               "agents": {"eng.s1": "engsecret"}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_PUBLIC_URL", "http://host.example:9400")
    monkeypatch.setenv("EDP8_TOKENS", str(tf))
    monkeypatch.delenv("EDP8_TOKEN", raising=False)
    board = Board(Store(":memory:"))
    bport, mport = _free_port(), _free_port()
    board_app = create_app(board, admin_token="realsecret")
    tc = TestClient(board_app)
    for pid, role, typ in [("owner", "owner", "human"), ("exp.ada", "expert", "human"), ("eng.s1", "engineer", "agent")]:
        assert tc.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                       headers={"X-Admin": "realsecret"}).json()["ok"]
    monkeypatch.setenv("EDP8_BOARD_URL", f"http://127.0.0.1:{bport}")
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "realsecret")
    with _Server(board_app, bport), _Server(mcp_server.build_http_app(), mport):
        yield {"mcp": f"http://127.0.0.1:{mport}", "board": f"http://127.0.0.1:{bport}"}


def test_expert_gets_zero_tools_on_every_role_path(expert_stack):
    import json
    hdr = {"X-Participant": "exp.ada", "X-Token": "expsecret"}
    for role in sorted(ROLE_BUNDLES):
        names, res = _run(_call(f"{expert_stack['mcp']}/mcp/{role}", hdr, "whoami"))
        assert names == [], (role, names)
        out = json.loads(res.content[0].text)
        assert out["ok"] is False and out["error"]["code"] == "unauthorized", (role, out)


def test_seat_naming_another_roles_path_gets_only_its_own_tools(expert_stack):
    hdr = {"X-Participant": "eng.s1", "X-Token": "engsecret"}
    names, _ = _run(_call(f"{expert_stack['mcp']}/mcp/owner", hdr))
    assert "spawn" not in names and "reap" not in names  # owner-only tools stay the owner's
    assert set(names) == set(ROLE_BUNDLES["owner"]) & set(ROLE_BUNDLES["engineer"])
    own, _ = _run(_call(f"{expert_stack['mcp']}/mcp/engineer", hdr))
    assert set(own) == set(ROLE_BUNDLES["engineer"])


# --------------------------------------------------------------- s-e60c3d42ad: wake=mod is decided per seat, over HTTP
def _subscribe_over_http(stack, headers: dict) -> dict:
    import json
    _, res = _run(_call(f"{stack['mcp']}/mcp/engineer", {"X-Participant": "eng.s1", **headers}, "subscribe"))
    return json.loads(res.content[0].text)["value"]


def test_subscribe_over_http_decides_wake_mod_from_the_seats_header_and_readiness(stack, monkeypatch, tmp_path):
    """qa m-dfb5b7f516: the shared service has no CLAUDE_CODE_PLUGIN_DIRS of its own, so the seat's X-Wake-Mod header
    (or a live mod readiness file) is the only signal. The F1 in-process tests hid this."""
    from pathlib import Path

    from edp8 import feed_driver

    mods = str(Path(__file__).resolve().parents[1] / ".claude" / "mods")
    monkeypatch.setenv("EDP8_FEED_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("EDP8_WAKE_READY_WAIT_S", "0")
    monkeypatch.delenv("EDP_WAKE_MOD", raising=False)
    assert "CLAUDE_CODE_PLUGIN_DIRS" not in os.environ and "EDP8_FEED_PY" not in os.environ  # the service's own env

    # no mod anywhere: the Monitor, as before
    out = _subscribe_over_http(stack, {})
    assert out["monitor_cmd"] and "wake" not in out
    # the header names a mod dir but its listener is not up yet: still the Monitor
    out = _subscribe_over_http(stack, {"X-Wake-Mod": mods})
    assert out["monitor_cmd"] and "wake" not in out
    # a Monitor-run driver's readiness file is not the mod's, header or not
    feed_driver.Readiness("eng.s1", owner="monitor").write()
    assert _subscribe_over_http(stack, {"X-Wake-Mod": mods})["monitor_cmd"]
    # the mod's listener is live: header present -> wake=mod and no monitor_cmd
    feed_driver.Readiness("eng.s1", owner="mod").write()
    out = _subscribe_over_http(stack, {"X-Wake-Mod": mods})
    assert out["monitor_cmd"] is None and out["wake"] == "mod"
    # a seat already up is caught by the readiness file alone (header empty or absent)
    assert _subscribe_over_http(stack, {})["wake"] == "mod"
    assert _subscribe_over_http(stack, {"X-Wake-Mod": ""})["wake"] == "mod"
    # the kill switch still wins
    monkeypatch.setenv("EDP_WAKE_MOD", "0")
    assert _subscribe_over_http(stack, {"X-Wake-Mod": mods})["monitor_cmd"]


def test_resume_self_over_http_also_reports_wake_mod(stack, monkeypatch, tmp_path):
    import json
    from pathlib import Path

    from edp8 import feed_driver

    monkeypatch.setenv("EDP8_FEED_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("EDP8_WAKE_READY_WAIT_S", "0")
    monkeypatch.delenv("EDP_WAKE_MOD", raising=False)
    feed_driver.Readiness("eng.s1", owner="mod").write()
    mods = str(Path(__file__).resolve().parents[1] / ".claude" / "mods")
    _, res = _run(_call(f"{stack['mcp']}/mcp/engineer", {"X-Participant": "eng.s1", "X-Wake-Mod": mods}, "resume_self"))
    val = json.loads(res.content[0].text)["value"]
    assert val["monitor_cmd"] is None
