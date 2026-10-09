"""t-732cf1dd92 (design m-bb6902256d, rulings m-b61ec43737): the browser tools through edp8. One upstream session per
seat session on the ONE shared service; closed when the seat's session ends (board -> MCP) or after 30 min idle;
sign-in only on the board UI's exact origin with the seat's own token, which no tool result ever carries;
screenshots pass through as MCP image content; 23 tools, the two host-acting ones dropped; every agent role lists
them unless `tools.browser_mcp` is off. The service here is a fake speaking the MCP wire (stateful streamable HTTP);
the real one is proven on the sandbox."""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("EDP8_EMBEDDER", "none")

import httpx
import pytest

from edp_contracts import browser_tool
from edp8 import browser_proxy as bp

TOKEN = "tok-SEAT-SECRET-123"
BOARD = "http://127.0.0.1:57076"
PNG = "iVBORw0KGgo="


class FakeService:
    """Stands in for browser_proxy.Service: a fixed URL, a generation, no process."""

    def __init__(self) -> None:
        self.generation = 1
        self.stopped = False

    def url(self) -> str:
        return "http://127.0.0.1:9/mcp"

    def status(self) -> dict:
        return {"running": not self.stopped}

    def stop(self) -> None:
        self.stopped = True


class FakeUpstream:
    """@playwright/mcp's wire as measured: initialize answers an mcp-session-id over SSE, an unknown id is 404,
    DELETE closes the session; a per-session cookie jar stands in for the per-session browser context."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self.deleted: list[str] = []
        self.bodies: list[str] = []
        self.echo_in_snapshot = False
        self._n = 0

    def _sse(self, msg: dict, sid: str | None = None) -> httpx.Response:
        h = {"content-type": "text/event-stream"}
        if sid:
            h["mcp-session-id"] = sid
        return httpx.Response(200, headers=h, text=f"event: message\ndata: {json.dumps(msg)}\n\n")

    def __call__(self, req: httpx.Request) -> httpx.Response:
        sid = req.headers.get("mcp-session-id")
        if req.method == "DELETE":
            self.deleted.append(sid)
            return httpx.Response(200 if self.sessions.pop(sid, None) is not None else 404)
        self.bodies.append(req.content.decode())
        body = json.loads(req.content)
        if body["method"] == "initialize":
            self._n += 1
            new = f"up-{self._n}"
            self.sessions[new] = {"cookies": {}, "url": None, "storage": {}}
            return self._sse({"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18"}}, new)
        if sid not in self.sessions:
            return httpx.Response(404, text="session not found")
        if "id" not in body:
            return httpx.Response(202)
        name, args = body["params"]["name"], body["params"]["arguments"]
        self.calls.append((sid, name, args))
        s = self.sessions[sid]
        if name == "browser_navigate":
            s["url"] = args["url"]
            content = [{"type": "text", "text": f"### Page\n- Page URL: {args['url']}"}]
        elif name == "browser_evaluate":
            fn = args["function"]
            here = bp.origin_of(s["url"])
            if "sessionStorage.setItem('edp8.token', " in fn:
                if f"location.origin !== {json.dumps(here)}" in fn:
                    out = "set"
                    s["storage"]["edp8.token"] = json.loads(fn.split("sessionStorage.setItem('edp8.token', ")[1]
                                                            .split(")")[0])
                else:
                    out = "elsewhere"
            else:  # a seat's own script: this stand-in only reads the page's token back
                out = s["storage"].get("edp8.token")
            # the real service echoes the code it ran: the token is in this result
            content = [{"type": "text", "text": f'### Result\n"{out}"\n### Ran Playwright code\nawait page.evaluate({fn})'}]
        elif name == "browser_take_screenshot":
            content = [{"type": "text", "text": "### Result\nTook the viewport screenshot"},
                       {"type": "image", "data": PNG, "mimeType": "image/png"}]
        elif name == "browser_snapshot":
            content = [{"type": "text", "text": f"- generic: {TOKEN if self.echo_in_snapshot else 'page'}"}]
        else:
            content = [{"type": "text", "text": "ok"}]
        return self._sse({"jsonrpc": "2.0", "id": body["id"], "result": {"content": content}})


@pytest.fixture
def rig():
    up = FakeUpstream()
    svc = FakeService()
    proxy = bp.BrowserProxy(svc, origins=frozenset({BOARD}), idle_s=1800,
                            http=httpx.Client(transport=httpx.MockTransport(up)))
    return proxy, up, svc


def _texts(res: dict) -> str:
    return json.dumps(res)


# ------------------------------------------------------------------------------------------ the tool set

def test_twenty_three_tools_of_the_pinned_version_without_the_host_acting_two():
    snap = json.loads(bp._SNAPSHOT.read_text(encoding="utf-8"))
    assert snap["version"] == browser_tool.version() == "0.0.83"  # moving the pin means regenerating the snapshot
    assert len(bp.TOOLS) == 23 and not (bp.TOOL_NAMES & browser_tool.DROPPED)
    assert {"browser_navigate", "browser_take_screenshot", "browser_snapshot", "browser_click"} <= bp.TOOL_NAMES
    assert all(t["name"].startswith("browser_") and t["inputSchema"]["type"] == "object" for t in bp.TOOLS)


def test_a_dropped_tool_is_refused_without_reaching_the_service(rig):
    proxy, up, _ = rig
    res = proxy.call("s-1", "browser_run_code_unsafe", {"code": "1"})
    assert res["isError"] and up.calls == [] and up.sessions == {}


# ------------------------------------------------------------------------------------------ per-seat sessions

def test_each_seat_session_gets_its_own_upstream_session(rig):
    proxy, up, _ = rig
    proxy.call("s-A", "browser_navigate", {"url": "http://example.test/"})
    proxy.call("s-B", "browser_navigate", {"url": "http://example.test/"})
    proxy.call("s-A", "browser_snapshot", {})
    sids = [sid for sid, _, _ in up.calls]
    assert sids == ["up-1", "up-2", "up-1"]
    assert sorted(proxy.sessions()) == ["s-A", "s-B"]


def test_a_session_end_closes_only_that_seats_upstream_session(rig):
    proxy, up, _ = rig
    proxy.call("s-A", "browser_snapshot", {})
    proxy.call("s-B", "browser_snapshot", {})
    assert proxy.release("s-A") is True
    assert up.deleted == ["up-1"] and list(up.sessions) == ["up-2"]
    assert proxy.release("s-A") is False  # already gone: no second DELETE
    assert up.deleted == ["up-1"]


def test_an_idle_session_is_reaped_and_a_busy_or_recent_one_is_not(rig):
    proxy, up, _ = rig
    proxy.call("s-old", "browser_snapshot", {})
    proxy.call("s-new", "browser_snapshot", {})
    now = time.monotonic()
    proxy._sessions["s-old"].last = now - 31 * 60
    proxy._sessions["s-new"].last = now - 29 * 60
    assert proxy.reap(now) == ["s-old"]
    assert up.deleted == ["up-1"] and proxy.sessions() == ["s-new"]


def test_the_reaper_default_is_thirty_minutes():
    assert bp.IDLE_S == 30 * 60
    assert browser_tool.IDLE_TIMEOUT_MS > bp.IDLE_S * 1000  # the service's own close is only the last resort


def test_a_session_the_service_lost_is_reopened_once(rig):
    proxy, up, _ = rig
    proxy.call("s-A", "browser_snapshot", {})
    up.sessions.clear()  # the service closed it (its --idle-timeout, a restart)
    res = proxy.call("s-A", "browser_snapshot", {})
    assert not res.get("isError") and [sid for sid, _, _ in up.calls] == ["up-1", "up-2"]


def test_a_restarted_service_starts_fresh_sessions(rig):
    proxy, up, svc = rig
    proxy.call("s-A", "browser_snapshot", {})
    svc.generation += 1
    proxy.call("s-A", "browser_snapshot", {})
    assert [sid for sid, _, _ in up.calls] == ["up-1", "up-2"]


def test_close_releases_every_session_and_stops_the_service(rig):
    proxy, up, svc = rig
    proxy.call("s-A", "browser_snapshot", {})
    proxy.call("s-B", "browser_snapshot", {})
    proxy.close()
    assert sorted(up.deleted) == ["up-1", "up-2"] and svc.stopped


# ------------------------------------------------------------------------------------------ sign-in (ruling 2a)

def test_a_navigate_to_the_board_origin_signs_the_seat_in_and_returns_no_token(rig):
    proxy, up, _ = rig
    res = proxy.call("s-A", "browser_navigate", {"url": f"{BOARD}/ui/"}, handle="qa.s-1", token=TOKEN)
    assert [n for _, n, _ in up.calls] == ["browser_navigate", "browser_evaluate", "browser_navigate"]
    fn = up.calls[1][2]["function"]
    assert f"location.origin !== {json.dumps(BOARD)}" in fn and json.dumps(TOKEN) in fn and '"qa.s-1"' in fn
    assert up.sessions["up-1"]["storage"]["edp8.token"] == TOKEN
    assert TOKEN not in _texts(res) and "Page URL: http://127.0.0.1:57076/ui/" in _texts(res)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:57077/ui/",           # another port
    "http://localhost:57076/ui/",           # another host spelling
    "https://127.0.0.1:57076/ui/",          # another scheme
    "http://127.0.0.1:57076@evil.test/ui/", # user info
    "file:///C:/x.html",
    "https://example.com/?next=http://127.0.0.1:57076/ui/",
])
def test_a_navigate_anywhere_else_carries_no_token(rig, url):
    proxy, up, _ = rig
    res = proxy.call("s-A", "browser_navigate", {"url": url}, handle="qa.s-1", token=TOKEN)
    assert [n for _, n, _ in up.calls] == ["browser_navigate"]
    assert not any(TOKEN in b for b in up.bodies)
    assert TOKEN not in _texts(res)


def test_a_redirect_off_the_board_origin_gets_nothing(rig):
    """The evaluate re-checks location.origin in the page: navigating to the board origin but landing elsewhere
    sets nothing and does not reload."""
    proxy, up, _ = rig

    real = up.__call__

    def redirecting(req: httpx.Request) -> httpx.Response:
        r = real(req)
        sid = req.headers.get("mcp-session-id")
        if sid in up.sessions and up.calls and up.calls[-1][1] == "browser_navigate":
            up.sessions[sid]["url"] = "http://evil.test/"  # the server-side redirect
        return r

    proxy._http = httpx.Client(transport=httpx.MockTransport(redirecting))
    res = proxy.call("s-A", "browser_navigate", {"url": f"{BOARD}/ui/"}, handle="qa.s-1", token=TOKEN)
    assert [n for _, n, _ in up.calls] == ["browser_navigate", "browser_evaluate"]
    assert "edp8.token" not in up.sessions["up-1"]["storage"]
    assert TOKEN not in _texts(res)


def test_no_tool_result_ever_carries_the_token(rig):
    proxy, up, _ = rig
    up.echo_in_snapshot = True  # a page that prints it, a network listing of the UI's own requests
    res = proxy.call("s-A", "browser_snapshot", {}, handle="qa.s-1", token=TOKEN)
    assert TOKEN not in _texts(res) and bp.REDACTED in _texts(res)


def test_no_sign_in_without_a_token_or_with_no_board_origin_match(rig):
    proxy, up, _ = rig
    proxy.call("s-A", "browser_navigate", {"url": f"{BOARD}/ui/"}, handle="qa.s-1", token=None)
    assert [n for _, n, _ in up.calls] == ["browser_navigate"]


def test_board_origins_are_the_board_and_public_urls(monkeypatch):
    monkeypatch.setenv("EDP8_BOARD_URL", "http://127.0.0.1:9400/")
    monkeypatch.setenv("EDP8_PUBLIC_URL", "https://box.example.ts.net")
    assert bp.board_origins() == {"http://127.0.0.1:9400", "https://box.example.ts.net"}
    assert bp.origin_of("HTTP://127.0.0.1:80/x") == "http://127.0.0.1"
    assert bp.origin_of("javascript:alert(1)") is None


# ------------------------------------------------------------------------------------------ through the MCP server

@pytest.fixture
def seats(rig, monkeypatch):
    """_wrap_browser with the board's verdicts faked: qa.s-A and qa.s-B verify with their own tokens."""
    from edp8 import mcp_server
    proxy, up, _ = rig
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    monkeypatch.setattr(bp, "_proxy", proxy)
    monkeypatch.setattr(mcp_server, "_agent_shell_as_human", lambda *a: None)
    tokens = {"qa.s-A": "tok-A-0001", "qa.s-B": "tok-B-0002"}
    monkeypatch.setattr(mcp_server, "_caller_role",
                        lambda b, a, p, t: "qa" if tokens.get(p) == t else None)
    monkeypatch.setattr(mcp_server, "_caller_bundle", lambda *a: None)
    who: dict = {}
    monkeypatch.setattr(mcp_server, "_identity_from", lambda ctx: (who["p"], who["s"], who["t"]))

    def call(participant, session, token, tool, **args):
        who.update(p=participant, s=session, t=token)
        spec = next(t for t in bp.TOOLS if t["name"] == tool)
        return mcp_server._wrap_browser(spec, board_url=BOARD, admin_token="t", path_role="qa")(None, **args)
    return call, up, tokens


def test_a_seat_sending_another_seats_session_gets_its_own_context(seats):
    """Architect m-b397a2b7d9 fix 1: B passes A's X-Session; B lands in a fresh context and never sees A's token."""
    call, up, tok = seats
    call("qa.s-A", "pool-A", tok["qa.s-A"], "browser_navigate", url=f"{BOARD}/ui/")
    assert up.sessions["up-1"]["storage"]["edp8.token"] == tok["qa.s-A"]  # A signed in, in its own context
    seen = [call("qa.s-B", "pool-A", tok["qa.s-B"], "browser_evaluate",
                 function="() => sessionStorage.getItem('edp8.token')"),
            call("qa.s-B", "pool-A", tok["qa.s-B"], "browser_snapshot")]
    b_sids = {s for s, n, a in up.calls[3:]}
    assert b_sids == {"up-2"}  # not A's up-1
    assert all(tok["qa.s-A"] not in json.dumps([c.model_dump() for c in r.content]) for r in seen)


def test_an_unverified_caller_gets_no_browser(seats):
    call, up, _ = seats
    res = call("qa.s-A", "pool-A", "wrong-token", "browser_snapshot")
    assert "unauthorized" in res and up.calls == [] and up.sessions == {}


def test_a_caller_whose_whoami_fails_is_refused_with_no_upstream_session(rig, monkeypatch):
    """Architect m-8aeaaf3286: the board's real verdict path (whoami 401 / unknown handle -> _caller_role None)."""
    from edp8 import mcp_server
    from edp8.client import BoardClient
    proxy, up, _ = rig
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    monkeypatch.setattr(bp, "_proxy", proxy)
    monkeypatch.setattr(BoardClient, "whoami", lambda self: {"ok": False, "error": {"code": "unauthorized"}})
    monkeypatch.setattr(mcp_server, "_identity_from", lambda ctx: ("qa.ghost", "pool-G", "bad"))
    spec = next(t for t in bp.TOOLS if t["name"] == "browser_navigate")
    for path_role in ("qa", None):
        res = mcp_server._wrap_browser(spec, board_url="http://127.0.0.1:9", admin_token="t",
                                       path_role=path_role)(None, url=f"{BOARD}/ui/")
        assert "unauthorized" in res
    assert up.calls == [] and up.sessions == {} and proxy.sessions() == []
    assert not (bp.TOOL_NAMES & mcp_server.allowed_tool_names("qa", None))


def test_a_screenshot_comes_back_as_mcp_image_content(seats):
    from mcp_types import CallToolResult, ImageContent
    call, _, tok = seats
    res = call("qa.s-A", "pool-A", tok["qa.s-A"], "browser_take_screenshot")
    assert isinstance(res, CallToolResult) and not res.is_error
    img = [c for c in res.content if isinstance(c, ImageContent)]
    assert len(img) == 1 and img[0].data == PNG and img[0].mime_type == "image/png"


def test_every_agent_role_lists_the_browser_tools_and_the_switch_removes_them(monkeypatch):
    from edp8 import mcp_server
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    for role in ("qa", "engineer", "architect", "help"):
        assert bp.TOOL_NAMES <= mcp_server.allowed_tool_names(role, role)
    assert bp.TOOL_NAMES <= mcp_server.allowed_tool_names("qa", "engineer")  # any path
    assert not (bp.TOOL_NAMES & mcp_server.allowed_tool_names("owner", "owner"))  # a person's own client
    assert mcp_server.allowed_tool_names("qa", "expert") == set()
    assert mcp_server.allowed_tool_names("qa", None) == set()
    monkeypatch.setenv("EDP_BROWSER_MCP", "0")
    assert not (bp.TOOL_NAMES & mcp_server.allowed_tool_names("qa", "qa"))


def test_the_server_registers_them_only_when_on(monkeypatch):
    from edp8 import mcp_server
    monkeypatch.setenv("EDP_BROWSER_MCP", "0")
    off = mcp_server.build_role_server("qa", board_url=BOARD, admin_token="t")
    assert not ({t.name for t in off._tool_manager.list_tools()} & bp.TOOL_NAMES)
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    on = mcp_server.build_role_server("qa", board_url=BOARD, admin_token="t")
    tools = {t.name: t for t in on._tool_manager.list_tools()}
    assert bp.TOOL_NAMES <= set(tools)
    nav = next(t for t in bp.TOOLS if t["name"] == "browser_navigate")
    assert tools["browser_navigate"].parameters == nav["inputSchema"]


def test_the_release_route_needs_the_admin_token(rig, monkeypatch):
    from starlette.testclient import TestClient
    from edp8 import mcp_server
    proxy, up, _ = rig
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "t")
    monkeypatch.setattr(bp, "_proxy", proxy)
    monkeypatch.setattr(proxy, "start_reaper", lambda *a: None)
    proxy.call(bp.session_key("qa.s-1", "s-A"), "browser_snapshot", {})
    proxy.call(bp.session_key("qa.s-2", "s-A"), "browser_snapshot", {})  # another seat that sent the same id
    proxy.call(bp.session_key("qa.s-1", "s-AB"), "browser_snapshot", {})
    app = mcp_server.build_http_app(["qa"])
    with TestClient(app) as c:
        assert c.post("/browser/release/s-A").status_code == 403
        assert c.post("/browser/release/s-A", headers={"X-Admin": "wrong"}).status_code == 403
        r = c.post("/browser/release/s-A", headers={"X-Admin": "t"}).json()
        assert r["value"] == {"session": "s-A", "released": 2}
        assert proxy.sessions() == [bp.session_key("qa.s-1", "s-AB")]
    assert up.deleted[:2] == ["up-1", "up-2"]


def test_the_release_route_is_shut_when_the_server_has_no_admin_token(rig, monkeypatch):
    """Architect m-b397a2b7d9 fix 2: None == None once let anyone on loopback release sessions."""
    from starlette.testclient import TestClient
    from edp8 import mcp_server
    proxy, up, _ = rig
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    monkeypatch.setattr(mcp_server, "_env", lambda: (BOARD, None))
    monkeypatch.setattr(bp, "admin_token", lambda: None)
    monkeypatch.setattr(bp, "_proxy", proxy)
    monkeypatch.setattr(proxy, "start_reaper", lambda *a: None)
    proxy.call(bp.session_key("qa.s-1", "s-A"), "browser_snapshot", {})
    with TestClient(mcp_server.build_http_app(["qa"])) as c:
        assert c.post("/browser/release/s-A").status_code == 403
        assert c.post("/browser/release/s-A", headers={"X-Admin": ""}).status_code == 403
        assert c.post("/browser/release/s-A", headers={"X-Admin": "wrong"}).status_code == 403
        assert proxy.sessions() == [bp.session_key("qa.s-1", "s-A")]


def test_the_board_releases_a_seats_browser_session_on_its_dead_transition(monkeypatch):
    from fastapi.testclient import TestClient
    from edp8.board import Board
    from edp8.service import create_app
    from edp8.store import Store
    ended: list[str] = []
    monkeypatch.setattr(bp, "notify_session_end", ended.append)
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    body = {"participant_id": "qa.x", "pool_id": "local", "state": "alive"}
    assert c.put("/v1/sessions/s-9", json=body, headers={"X-Admin": "t"}).json()["ok"]
    assert ended == []
    assert c.put("/v1/sessions/s-9", json={**body, "state": "stalled"}, headers={"X-Admin": "t"}).json()["ok"]
    assert ended == []  # a stall may recover: keep its browser
    assert c.put("/v1/sessions/s-9", json={**body, "state": "dead", "reason": "reaped"},
                 headers={"X-Admin": "t"}).json()["ok"]
    assert ended == ["s-9"]
    assert c.put("/v1/sessions/s-9", json={**body, "state": "dead"}, headers={"X-Admin": "t"}).json()["ok"]
    assert ended == ["s-9"]  # not a transition


def test_notify_session_end_posts_with_the_admin_token_and_never_raises(monkeypatch):
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    monkeypatch.setenv("EDP8_MCP_URL", "http://127.0.0.1:9402/")
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "adm")
    sent: list[tuple[str, dict]] = []

    def post(url, headers, timeout):
        sent.append((url, headers))
        raise httpx.ConnectError("down")

    monkeypatch.setattr(bp.httpx, "post", post)
    started: list = []
    monkeypatch.setattr(bp.threading, "Thread", lambda target, **kw: started.append(target) or type(
        "T", (), {"start": staticmethod(target)})())
    bp.notify_session_end("s-1")
    assert sent == [("http://127.0.0.1:9402/browser/release/s-1", {"X-Admin": "adm"})]
    monkeypatch.setenv("EDP_BROWSER_MCP", "0")
    bp.notify_session_end("s-2")
    assert len(sent) == 1


def _token_only_in_the_file(monkeypatch, tmp_path, value="adm-from-file"):
    """An install: EDP8_ADMIN_TOKEN unset, the token only in the home's admin.token (settings.admin_token)."""
    monkeypatch.setenv("EDP_HOME", str(tmp_path))
    for k in ("EDP8_ADMIN_TOKEN", "EDP_CONFIG_DIR", "EDP_DEV"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "admin.token").write_text(value + "\n", encoding="utf-8")
    return value


def test_the_release_route_takes_the_admin_token_an_install_keeps_in_its_file(rig, monkeypatch, tmp_path):
    """hop2 (m-292a0e3c05): the route read only EDP8_ADMIN_TOKEN, unset on an install, so it refused every caller
    and a dead seat's browser lingered until the idle reaper."""
    from starlette.testclient import TestClient
    from edp8 import mcp_server
    proxy, up, _ = rig
    tok = _token_only_in_the_file(monkeypatch, tmp_path)
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    monkeypatch.setattr(bp, "_proxy", proxy)
    monkeypatch.setattr(proxy, "start_reaper", lambda *a: None)
    proxy.call(bp.session_key("qa.s-1", "s-A"), "browser_snapshot", {})
    with TestClient(mcp_server.build_http_app(["qa"])) as c:
        assert c.post("/browser/release/s-A", headers={"X-Admin": "wrong"}).status_code == 403
        r = c.post("/browser/release/s-A", headers={"X-Admin": tok})
        assert r.status_code == 200 and r.json()["value"] == {"session": "s-A", "released": 1}
    assert proxy.sessions() == [] and up.deleted == ["up-1"]


def test_notify_session_end_sends_the_admin_token_from_the_file(monkeypatch, tmp_path):
    tok = _token_only_in_the_file(monkeypatch, tmp_path)
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    monkeypatch.setenv("EDP8_MCP_URL", "http://127.0.0.1:9402")
    sent: list[dict] = []
    monkeypatch.setattr(bp.httpx, "post", lambda url, headers, timeout: sent.append(headers))
    monkeypatch.setattr(bp.threading, "Thread", lambda target, **kw: type("T", (), {"start": staticmethod(target)})())
    bp.notify_session_end("s-1")
    assert sent == [{"X-Admin": tok}]


@pytest.mark.parametrize("name", ["C:/Users/x/a.png", "C:a.png", r"\\host\share\a.png", "/etc/a.png",
                                  r"\a.png", "../a.png", "shots/../../a.png", r"..\a.png", "  "])
def test_a_filename_that_could_leave_the_output_folder_is_refused_before_the_service(rig, name):
    proxy, up, _ = rig
    res = proxy.call("k", "browser_take_screenshot", {"filename": name})
    assert res["isError"] and "filename" in res["content"][0]["text"]
    assert up.calls == [] and up.sessions == {}


def test_a_plain_or_nested_filename_goes_through(rig):
    proxy, up, _ = rig
    for name in ("proof.png", "shots/proof.png", "a..b.png"):
        assert not proxy.call("k", "browser_take_screenshot", {"filename": name}).get("isError")
    assert [c[2]["filename"] for c in up.calls] == ["proof.png", "shots/proof.png", "a..b.png"]


def test_the_service_runs_in_its_output_folder_so_named_files_land_there(monkeypatch, tmp_path):
    """hop2: a named screenshot landed in the MCP's working directory (the data root), not --output-dir."""
    started: dict = {}

    class Proc:
        pid, returncode = 4242, None

        def poll(self):
            return None

    monkeypatch.setattr(bp.browser_tool, "install_dir", lambda: tmp_path / "browser-mcp")
    monkeypatch.setattr(bp.browser_tool, "service_argv", lambda port, out: ["node", "cli.js", "--output-dir", str(out)])
    monkeypatch.setattr(bp.settings, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(bp, "popen_service", lambda argv, **kw: started.update(kw) or Proc())
    monkeypatch.setattr(bp.socket, "create_connection", lambda *a, **k: type("S", (), {"close": lambda self: None})())
    bp.Service().url()
    out = tmp_path / "browser-mcp" / "out"
    assert started["cwd"] == str(out) and out.is_dir()
