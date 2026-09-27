"""epic-91fcd3b370 S3: GET /v1/code tells the SPA where code-server is and whether it is up; the FAQ
route renders guides/code-tab-faq.md through the sanitised markdown path."""
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edp_contracts.identity import home_id_of

from edp8 import settings
from edp8.api_code import code_router
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

AUTH = {"X-Participant": "alice", "X-Token": "a"}


@pytest.mark.parametrize("port", [9400, 43123])
def test_external_link_preserves_app_port_path_and_query(port):
    app = FastAPI()
    app.include_router(code_router(lambda: None, lambda s: s))
    with TestClient(app, base_url="http://127.0.0.1:9400", client=("127.0.0.1", 1234)) as client:
        r = client.get(f"/v1/code/external/{port}/a%20b/c%23d?x=a%26b", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == f"http://127.0.0.1:{port}/a%20b/c%23d?x=a%26b"
        assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("peer,origin", [("100.64.0.2", "http://127.0.0.1:9400"),
                                         ("127.0.0.1", "https://board.example.ts.net")])
def test_external_link_refuses_remote_peers_and_public_hostnames(peer, origin):
    app = FastAPI()
    app.include_router(code_router(lambda: None, lambda s: s))
    with TestClient(app, base_url=origin, client=(peer, 1234)) as client:
        r = client.get("/v1/code/external/3000/", headers={"X-Forwarded-For": "127.0.0.1"}, follow_redirects=False)
        assert r.status_code == 403 and "location" not in r.headers


@pytest.mark.parametrize("port", ["0", "65536", "-1", "evil.example"])
def test_external_link_refuses_invalid_ports(port):
    app = FastAPI()
    app.include_router(code_router(lambda: None, lambda s: s))
    with TestClient(app, base_url="http://localhost:9400", client=("127.0.0.1", 1234)) as client:
        r = client.get(f"/v1/code/external/{port}/", follow_redirects=False)
        assert r.status_code in (400, 422) and "location" not in r.headers


class _Healthz(BaseHTTPRequestHandler):
    home_id: str | None = None  # what /__edp/home reports; None = a guard from before the id route (404)

    def do_GET(self):  # noqa: N802 — http.server API
        if self.path == "/__edp/home" and self.home_id:
            body = json.dumps({"home_id": self.home_id}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps({"status": "expired", "lastHeartbeat": 1}).encode()
        self.send_response(200 if self.path == "/healthz" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def board_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))  # guides/ and the default folder are the agent home
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / ".run"))
    monkeypatch.setenv("EDP8_PUBLIC", "0")
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    (tmp_path / "tokens.json").write_text(json.dumps({"alice": "a"}))
    app = create_app(Board(Store(":memory:")), admin_token="t")
    with TestClient(app) as client:
        assert client.post("/v1/participants", json={"id": "alice", "handle": "alice", "role": "owner", "type": "human"},
                           headers={"X-Admin": "t"}).status_code == 200
        yield client, tmp_path, monkeypatch


def test_requires_auth(board_env):
    client, _, _ = board_env
    assert client.get("/v1/code").status_code == 401
    assert client.get("/v1/code/faq").status_code == 401


def test_down_when_nothing_listens(board_env):
    client, tmp, mp = board_env
    port = _free_port()
    mp.setenv("EDP_CODE_PORT", str(port))
    r = client.get("/v1/code", headers=AUTH)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    v = r.json()["value"]
    assert v["port"] == port and v["url"] == f"http://127.0.0.1:{port}/"
    assert v["running"] is False and v["version"] is None
    # S21: one command on every OS; whether there is a code-server to start, and how to install one if not
    assert v["start_command"] == "heronry start code"
    assert isinstance(v["installed"], bool) and (v["installed"] or "code-server" in v["install_hint"])
    assert Path(v["default_folder"]) == tmp.resolve()


def _serving(home_id):
    handler = type("H", (_Healthz,), {"home_id": home_id})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_another_homes_code_server_is_never_adopted(board_env):
    """S8 (m-baed3c1589, art-102dc3c695): an install's Code tab embedded the fleet's code-server on 9410. A guard
    that reports another home's id is `foreign`, not running."""
    client, _, mp = board_env
    srv = _serving(home_id_of(Path("C:/somewhere/else/.data")))
    try:
        mp.setenv("EDP_CODE_PORT", str(srv.server_address[1]))
        v = client.get("/v1/code", headers=AUTH).json()["value"]
        assert v["running"] is False and v["foreign"] is True
    finally:
        srv.shutdown()


def test_this_homes_code_server_is_adopted_by_its_id(board_env):
    client, _, mp = board_env
    srv = _serving(home_id_of(settings.data_dir()))
    try:
        mp.setenv("EDP_CODE_PORT", str(srv.server_address[1]))
        v = client.get("/v1/code", headers=AUTH).json()["value"]
        assert v["running"] is True and v["foreign"] is False
    finally:
        srv.shutdown()


def test_a_guard_without_the_id_route_counts_only_as_this_homes_recorded_guard(board_env):
    """A guard started before /__edp/home existed reports no id: it is ours only when it is the guard pid
    this home's .run/code.json recorded for that port (the fleet's own guard until its next restart)."""
    client, tmp, mp = board_env
    srv = _serving(None)
    port = srv.server_address[1]
    try:
        mp.setenv("EDP_CODE_PORT", str(port))
        (tmp / ".run").mkdir(exist_ok=True)
        rec = tmp / ".run" / "code.json"
        v = client.get("/v1/code", headers=AUTH).json()["value"]
        assert v["running"] is False and v["foreign"] is True  # no record: not provably ours
        rec.write_text(json.dumps({"port": port, "guard_pid": os.getpid() + 1}), encoding="utf-8")
        assert client.get("/v1/code", headers=AUTH).json()["value"]["running"] is False  # another pid
        rec.write_text(json.dumps({"port": port + 1, "guard_pid": os.getpid()}), encoding="utf-8")
        assert client.get("/v1/code", headers=AUTH).json()["value"]["running"] is False  # another port
        rec.write_text(json.dumps({"port": port, "guard_pid": os.getpid()}), encoding="utf-8")
        assert client.get("/v1/code", headers=AUTH).json()["value"]["running"] is True
    finally:
        srv.shutdown()


def test_up_with_version_from_run_file(board_env):
    client, tmp, mp = board_env
    srv = ThreadingHTTPServer(("127.0.0.1", 0), type("H", (_Healthz,), {"home_id": home_id_of(settings.data_dir())}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        mp.setenv("EDP_CODE_PORT", str(srv.server_address[1]))
        (tmp / ".run").mkdir(exist_ok=True)
        # start-code.ps1 writes with PowerShell: tolerate a UTF-8 BOM
        (tmp / ".run" / "code.json").write_text(json.dumps({"service": "code", "version": "4.138.0"}), encoding="utf-8-sig")
        v = client.get("/v1/code", headers=AUTH).json()["value"]
        assert v["running"] is True and v["version"] == "4.138.0" and v["port"] == srv.server_address[1]
    finally:
        srv.shutdown()


class _Redirect(_Healthz):
    def do_GET(self):  # noqa: N802 — /healthz redirects to a URL that would answer 200
        if self.path == "/healthz":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        super().do_GET() if self.path != "/ok" else self._ok()

    def _ok(self):
        self.send_response(200)
        self.end_headers()


def test_probe_does_not_follow_redirects(board_env):
    client, _, mp = board_env
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Redirect)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        mp.setenv("EDP_CODE_PORT", str(srv.server_address[1]))
        assert client.get("/v1/code", headers=AUTH).json()["value"]["running"] is False
    finally:
        srv.shutdown()


def test_garbage_run_file_and_bad_port_env(board_env):
    client, tmp, mp = board_env
    mp.setenv("EDP_CODE_PORT", "not-a-port")
    (tmp / ".run").mkdir(exist_ok=True)
    (tmp / ".run" / "code.json").write_text("{not json")
    v = client.get("/v1/code", headers=AUTH).json()["value"]
    assert v["port"] == 9410 and v["version"] is None


def test_faq_rendered_and_sanitised(board_env):
    client, tmp, _ = board_env
    assert client.get("/v1/code/faq", headers=AUTH).status_code == 404
    (tmp / "guides").mkdir()
    (tmp / "guides" / "code-tab-faq.md").write_text("# FAQ\n\n## Shared tree\n\n<script>alert(1)</script>ok\n", encoding="utf-8")
    v = client.get("/v1/code/faq", headers=AUTH).json()["value"]
    assert "<h2>Shared tree</h2>" in v["html"] and "<script>" not in v["html"]
    assert v["path"] == "guides/code-tab-faq.md"


def test_repo_faq_covers_the_five_story_topics():
    body = (Path(__file__).resolve().parents[1] / "guides" / "code-tab-faq.md").read_text(encoding="utf-8").lower()
    for topic in ("shared tree", "worktree", "pylance", "tag", "not guarded"):
        assert topic in body, topic


# -- s-17c13096e5: POST /v1/code/session mints a guard login token for the human owner only ---------

from edp8.code_guard import verify_token  # noqa: E402

MINT_KEY = "m" * 64


@pytest.fixture
def mint_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / ".run"))
    monkeypatch.setenv("EDP8_PUBLIC", "0")
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    (tmp_path / "tokens.json").write_text(json.dumps({"alice": "a", "bob": "b", "agents": {"engineer.x": "e"}}))
    (tmp_path / ".run").mkdir()
    (tmp_path / ".run" / "code.json").write_text(json.dumps({"service": "code", "mint_key": MINT_KEY}), encoding="utf-8-sig")
    app = create_app(Board(Store(":memory:")), admin_token="t")
    with TestClient(app, base_url="http://127.0.0.1:9400", client=("127.0.0.1", 1234)) as client:
        for p in ({"id": "alice", "handle": "alice", "role": "owner", "type": "human"},
                  {"id": "bob", "handle": "bob", "role": "architect", "type": "human"},
                  {"id": "engineer.x", "handle": "engineer.x", "role": "engineer", "type": "agent"}):
            assert client.post("/v1/participants", json=p, headers={"X-Admin": "t"}).status_code == 200
        # an agent in the owner role can no longer exist (t-cd4712c855): its registration is refused
        r = client.post("/v1/participants", json={"id": "owner.agent", "handle": "owner.agent", "role": "owner",
                                                  "type": "agent"}, headers={"X-Admin": "t"})
        assert not r.json().get("ok") and "is a person" in r.text
        yield client, tmp_path


def test_session_minted_for_the_human_owner(mint_env):
    client, _ = mint_env
    r = client.post("/v1/code/session", headers=AUTH)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    v = r.json()["value"]
    seen = {}
    assert verify_token(MINT_KEY, v["token"], seen) is None      # the guard accepts it once
    assert verify_token(MINT_KEY, v["token"], seen) == "token already used"
    assert client.post("/v1/code/session", headers=AUTH).json()["value"]["token"] != v["token"]


@pytest.mark.parametrize("headers,status", [
    ({}, 401),                                                   # no credential
    ({"X-Participant": "alice", "X-Token": "wrong"}, 401),       # a forged owner header
    ({"X-Participant": "engineer.x", "X-Token": "e"}, 403),      # an agent seat's token
    ({"X-Participant": "owner.agent"}, 401),                     # an owner-role agent (unregistrable since t-cd4712c855)
    ({"X-Participant": "bob", "X-Token": "b"}, 403),             # a human who is not the owner
])
def test_session_refused_for_everyone_else(mint_env, headers, status):
    client, _ = mint_env
    r = client.post("/v1/code/session", headers=headers)
    assert r.status_code == status and "token" not in r.text


def test_session_refused_off_the_board_host(tmp_path, monkeypatch, mint_env):
    client, _ = mint_env
    app = client.app
    for base, peer in [("http://127.0.0.1:9400", "100.64.0.2"), ("https://board.example.ts.net", "127.0.0.1")]:
        with TestClient(app, base_url=base, client=(peer, 1234)) as c:
            r = c.post("/v1/code/session", headers={**AUTH, "X-Forwarded-For": "127.0.0.1"})
            assert r.status_code == 403 and "token" not in r.text


def test_session_refused_to_a_header_only_owner_in_trusted_mode(tmp_path, monkeypatch):
    # second opinion 20260925T191655Z-01833b5d: with no tokens.json any local caller can claim the owner
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / ".run"))
    monkeypatch.setenv("EDP8_PUBLIC", "0")
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "absent-tokens.json"))
    (tmp_path / ".run").mkdir()
    (tmp_path / ".run" / "code.json").write_text(json.dumps({"service": "code", "mint_key": MINT_KEY}))
    app = create_app(Board(Store(":memory:")), admin_token="t")
    with TestClient(app, base_url="http://127.0.0.1:9400", client=("127.0.0.1", 1234)) as client:
        assert client.post("/v1/participants", json={"id": "alice", "handle": "alice", "role": "owner", "type": "human"},
                           headers={"X-Admin": "t"}).status_code == 200
        r = client.post("/v1/code/session", headers={"X-Participant": "alice"})
        assert r.status_code == 403 and "token" not in r.json().get("value", {})


def test_session_503_without_a_mint_key(mint_env):
    client, tmp = mint_env
    (tmp / ".run" / "code.json").write_text(json.dumps({"service": "code"}))
    r = client.post("/v1/code/session", headers=AUTH)
    assert r.status_code == 503 and "token" not in r.json().get("value", {})


# -- t-93da8bf09d: POST /v1/code/reset-layout stamps the file the edp-code extension watches -------------

def test_reset_layout_stamps_the_extension_storage_for_the_owner(mint_env):
    client, tmp = mint_env
    user = tmp / "code-user"
    (tmp / ".run" / "code.json").write_text(json.dumps({"service": "code", "mint_key": MINT_KEY, "user_dir": str(user)}))
    r = client.post("/v1/code/reset-layout", headers=AUTH)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    stamp = user / "User" / "globalStorage" / "edp.edp-code" / "reset-layout.json"
    body = json.loads(stamp.read_text(encoding="utf-8"))
    assert body["at"] == r.json()["value"]["at"] and body["by"] == "alice"


def test_reset_layout_defaults_to_the_data_dir_user(mint_env):
    client, tmp = mint_env
    from edp8 import settings
    assert client.post("/v1/code/reset-layout", headers=AUTH).status_code == 200
    assert (settings.data_dir() / "code" / "user" / "User" / "globalStorage" / "edp.edp-code" / "reset-layout.json").is_file()


@pytest.mark.parametrize("headers,status", [
    ({}, 401),
    ({"X-Participant": "engineer.x", "X-Token": "e"}, 403),
    ({"X-Participant": "owner.agent"}, 401),  # an owner-role agent cannot be registered (t-cd4712c855)
    ({"X-Participant": "bob", "X-Token": "b"}, 403),
])
def test_reset_layout_refused_for_everyone_else(mint_env, headers, status):
    client, tmp = mint_env
    assert client.post("/v1/code/reset-layout", headers=headers).status_code == status
    assert not list(tmp.rglob("reset-layout.json"))
