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
