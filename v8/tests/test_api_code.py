"""epic-91fcd3b370 S3: GET /v1/code tells the SPA where code-server is and whether it is up; the FAQ
route renders guides/code-tab-faq.md through the sanitised markdown path."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

AUTH = {"X-Participant": "alice", "X-Token": "a"}


class _Healthz(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server API
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
    assert v["start_command"] == ".\\edp.ps1 start code"
    assert Path(v["default_folder"]) == tmp.resolve()


def test_up_with_version_from_run_file(board_env):
    client, tmp, mp = board_env
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Healthz)
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
