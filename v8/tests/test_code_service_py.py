"""S21 (s-0cfebd3862): the Python `code` service (edp8.code_service) on every OS, with a stub code-server.

Each test runs a private home (tmp EDP_HOME) on free ports; the stub (tests/fixtures/code_server_stub.py) stands
in for code-server, so CI needs no real one. The fleet's code-server (:9410) and services are never touched:
every port here is a fresh ephemeral one, and a stop only acts on this home's record.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import psutil
import pytest

from edp_contracts.proc import ProcId

STUB = Path(__file__).resolve().parent / "fixtures" / "code_server_stub.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A private Heronry home with the stub as code-server, and fleet/seat variables that must NOT reach it."""
    for k in list(os.environ):
        if (k.startswith("EDP_") or k.startswith("EDP8_")) and k not in ("EDP8_UI", "EDP8_TOKENS"):
            monkeypatch.delenv(k, raising=False)
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("EDP_HOME", str(h))
    monkeypatch.setenv("EDP_CODE_PORT", str(_free_port()))
    monkeypatch.setenv("EDP8_PORT", str(_free_port()))
    monkeypatch.setenv("EDP_CODE_SERVER_PATH", str(STUB))
    monkeypatch.setenv("STUB_CODE_REPORT", str(tmp_path / "report.json"))
    # a seat's secrets and identity: none of them may reach code-server or its terminals
    monkeypatch.setenv("EDP8_TOKEN", "seat-secret-token")
    monkeypatch.setenv("EDP_HANDLE", "engineer.test")
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("LOG_LEVEL", "trace")
    from edp8 import code_service
    yield {"dir": h, "report": tmp_path / "report.json", "port": code_service.port()}
    out = code_service.stop()
    # a safety net for a failing test only: never leave the stub's sleeper behind
    try:
        gc = json.loads((tmp_path / "report.json").read_text(encoding="utf-8")).get("grandchild")
        if gc and psutil.pid_exists(gc):
            psutil.Process(gc).kill()
    except (OSError, ValueError, psutil.Error):
        pass
    assert not out["survivors"]


def _get(url: str, headers: dict[str, str] | None = None) -> int:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_a, **_k):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, headers=headers or {}), timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _gone(pid: int | None, deadline_s: float = 10.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if not pid or not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
            return True
        time.sleep(0.2)
    return False


# ------------------------------------------------------------------------------------------ unit

def test_server_env_strips_every_edp_variable_and_the_password_bearing_ones():
    from edp8.code_service import guard_env, server_env
    base = {"PATH": "/bin", "EDP8_TOKEN": "t", "EDP_HANDLE": "h", "edp8_lower": "x", "EDP_HOME": "/h",
            "LOG_LEVEL": "trace", "PASSWORD": "p", "HASHED_PASSWORD": "s", "CODE_SERVER_COOKIE_SUFFIX": "x",
            "VSCODE_OPTIONS": "v", "CODE_SERVER_CONFIG": "c", "CODE_GUARD_MINT_KEY": "k", "HOME": "/u"}
    env = server_env(base)
    assert env == {"PATH": "/bin", "HOME": "/u"}
    g = guard_env(base)
    assert "EDP8_TOKEN" not in g and "EDP_HANDLE" not in g and "HASHED_PASSWORD" not in g
    assert g["EDP_HOME"] and g["EDP8_DATA"] and g["EDP8_RUN_DIR"]


def test_install_hint_per_os_names_the_official_route():
    from edp8.code_service import install_hint
    assert "npm install -g code-server" in install_hint("win32")
    assert "brew install code-server" in install_hint("darwin")
    assert "code-server.dev/install.sh" in install_hint("linux")


def test_locate_prefers_the_setting_and_runs_a_python_entry_under_this_interpreter(home):
    from edp8.code_service import locate
    got = locate()
    assert got is not None and got.source == "setting" and got.argv == [sys.executable, str(STUB)]


def test_not_installed_reports_the_install_hint(home, monkeypatch, tmp_path):
    from edp8 import code_service
    monkeypatch.delenv("EDP_CODE_SERVER_PATH")
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    st = code_service.status()
    assert st["state"] == "not_installed" and st["installed"] is False
    assert st["install_hint"] == code_service.install_hint()
    out = code_service.start()
    assert out["state"] == "not_installed" and code_service.install_hint() in out["reason"]
    assert not code_service.record_path().exists()


def test_non_loopback_bind_is_refused(home, monkeypatch):
    from edp8 import code_service
    monkeypatch.setenv("EDP_CODE_HOST", "0.0.0.0")
    with pytest.raises(code_service.CodeError, match="binds 127.0.0.1 only"):
        code_service.start()


# ------------------------------------------------------------------------------------------ live (stub)

def test_start_guards_strips_env_is_idempotent_and_stops_by_recorded_pid(home):
    from edp8 import code_service, run_state
    p = home["port"]
    out = code_service.start(extensions=False)
    assert out["state"] == "started", out
    rec = code_service.record()
    server, guard = ProcId.from_json(rec["server"]), ProcId.from_json(rec["guard"])
    assert server.live() and guard.live()
    # the record carries what the board reads (api_code): port, guard pid, mint key, user dir
    assert rec["port"] == p and rec["guard_pid"] == guard.pid and len(rec["mint_key"]) == 64
    assert rec["user_dir"] == str(code_service.user_dir()) and rec["home_id"] == code_service.my_home_id()
    # the guard holds the service port, loopback only; code-server sits on the inner port
    lp = run_state.listener_pid(p)
    assert code_service._in_tree(guard, lp)
    assert code_service._in_tree(server, run_state.listener_pid(rec["inner_port"]))
    # our own processes' sockets: the host-wide scan needs root on macOS (CI 36326185339)
    for c, _pid in run_state._own_process_sockets(psutil):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port in (p, rec["inner_port"]):
            assert c.laddr.ip == "127.0.0.1"
    # the guard: this home's id, 401 without its cookie, 421 for a rebinding Host, workbench after login
    assert code_service.guard_home_id(p) == code_service.my_home_id()
    assert _get(f"http://127.0.0.1:{p}/") == 401
    assert _get(f"http://127.0.0.1:{p}/", {"Host": f"evil.example:{p}"}) == 421
    assert code_service.workbench(rec["mint_key"], p)
    assert code_service.status()["state"] == "up"
    # env strip: no EDP_*/EDP8_* key and no password-bearing variable reached code-server
    rep = json.loads(home["report"].read_text(encoding="utf-8"))
    leaked = [k for k in rep["env"] if k.upper().startswith(("EDP_", "EDP8_")) or k.upper() in
              ("HASHED_PASSWORD", "LOG_LEVEL", "CODE_GUARD_SESSION", "CODE_GUARD_MINT_KEY")]
    assert leaked == [] and rep["had_secret"] is True
    assert rep["proxy_uri"].endswith("/v1/code/external/{{port}}/")
    assert "--auth" in rep["argv"] and rep["argv"][rep["argv"].index("--auth") + 1] == "password"
    grandchild = rep["grandchild"]
    assert psutil.pid_exists(grandchild)
    # idempotent: a second start adopts, never starts twice
    again = code_service.start(extensions=False)
    assert again["state"] == "already_running" and again["pid"] == server.pid
    assert code_service.record()["server"] == rec["server"]
    # stop: the recorded pair and their trees, port closed, record gone, no survivor (grandchild included)
    out = code_service.stop()
    assert out["state"] == "stopped" and out["survivors"] == []
    assert _gone(server.pid) and _gone(guard.pid) and _gone(grandchild)
    assert not run_state._port_listening(p)
    assert not code_service.record_path().exists()
    assert code_service.stop()["state"] == "not_running"


class _Foreign(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_a):
        pass


def test_a_foreign_listener_fails_the_start_loudly_and_is_never_touched(home):
    from edp8 import code_service
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", home["port"]), _Foreign)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert code_service.status()["state"] == "foreign"
        with pytest.raises(code_service.CodeError, match="leaving it"):
            code_service.start(extensions=False)
        # a stop with no record never takes the foreign listener for ours
        assert code_service.stop()["state"] == "not_running"
        assert _get(f"http://127.0.0.1:{home['port']}/") == 200 and t.is_alive()
        assert not home["report"].exists()  # nothing was launched
    finally:
        srv.shutdown()
        srv.server_close()


def test_stop_never_kills_a_reused_pid_and_matches_a_legacy_record_to_the_second(home):
    import subprocess
    from edp8 import code_service
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL)
    try:
        real = ProcId.of(other.pid)
        # a record naming that pid with another start time: a reused pid, never ours
        code_service._write_record({"service": "code", "port": home["port"], "pid": other.pid,
                                    "server": {"pid": other.pid, "create_time": real.create_time - 30, "name": real.name},
                                    "guard_pid": other.pid, "guard_creation_date": "2001-01-01T00:00:00+00:00"})
        assert code_service.stop()["state"] == "not_running"
        assert other.poll() is None
        # the old script's record (pid + .NET "o" date, 7 fraction digits): matched only to the second
        from datetime import datetime, timezone
        iso = datetime.fromtimestamp(real.create_time, timezone.utc).astimezone().isoformat(timespec="microseconds")
        dotnet = iso[:iso.index(".") + 7] + "4" + iso[iso.index(".") + 7:]
        assert code_service._legacy_ident(other.pid, dotnet) == real
        late = datetime.fromtimestamp(real.create_time + 5, timezone.utc).isoformat()
        assert code_service._legacy_ident(other.pid, late) is None
    finally:
        other.kill()
        other.wait(timeout=10)


def test_a_failed_start_rolls_back_what_it_launched(home, monkeypatch):
    from edp8 import code_service
    # a guard that exits at once: readiness never comes, and the started code-server must go again
    monkeypatch.setattr(code_service, "guard_argv", lambda args: [sys.executable, "-c", "import sys; sys.exit(3)"])
    with pytest.raises(code_service.CodeError, match="rolled back"):
        code_service.start(extensions=False, wait_s=15)
    rep = json.loads(home["report"].read_text(encoding="utf-8"))
    assert _gone(rep["grandchild"])
    assert not code_service.record_path().exists()
