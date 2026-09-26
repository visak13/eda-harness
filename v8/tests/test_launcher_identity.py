"""t-596660619c: the launcher acts only on its own home's services (a service's identity is its home).

Unit tests drive `launcher` in-process against FAKE listeners (a tiny subprocess answering the health
route with a chosen identity, or none); the integration tests drive the `heronry` CLI on two private
homes with free ports. Nothing here touches the fleet's ports or run dir; every child carries a marker
and dies in the fixture.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from edp_contracts.identity import home_id_of
from edp_contracts.proc import ProcId, kill_tree, scan_env_marker

from edp8 import launcher, run_state, settings, setup

V8 = Path(__file__).resolve().parents[1]
MARKER = "EDP_T596_TEST_MARKER"

FAKE = r"""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port, body = int(sys.argv[1]), sys.argv[2]
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        data = body.encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def _free_ports(n: int) -> list[int]:
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


def _listening(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture
def marker():
    value = uuid.uuid4().hex
    yield value
    for ident in scan_env_marker(MARKER, value):
        kill_tree(ident, grace=2.0)


@pytest.fixture
def fake(marker, tmp_path):
    """fake(port, body) -> ProcId of a listener that answers every GET with `body` (a dict, JSON)."""
    script = tmp_path / "fake_health.py"
    script.write_text(FAKE, encoding="utf-8")

    def start(port: int, body: dict, *extra: str) -> ProcId:
        env = {**os.environ, MARKER: marker}
        # `extra` lets a fake carry a service module name in its argv (the old _ours matched on it)
        proc = subprocess.Popen([sys.executable, str(script), str(port), json.dumps(body), *extra], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not _listening(port):
            time.sleep(0.1)
        assert _listening(port), "fake listener did not come up"
        return ProcId.of(run_state.listener_pid(port) or proc.pid)
    return start


@pytest.fixture
def home(tmp_path, monkeypatch):
    """This process as the caller of home A: its own EDP_HOME, run dir and a free board port."""
    h = tmp_path / "homeA"
    h.mkdir()
    for k in ("EDP_HOME", "EDP8_HOME", "EDP8_DATA", "EDP8_RUN_DIR", "EDP_CONFIG_DIR", "EDP_DEV"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EDP_HOME", str(h))
    (port,) = _free_ports(1)
    monkeypatch.setitem(run_state.SERVICES, "board", {"port": port, "health": "/v1/health"})
    return {"home": h, "port": port}


# ------------------------------------------------------------------------------------------ unit

def test_listener_without_identity_is_foreign_never_killed(home, fake):
    lid = fake(home["port"], {"ok": True})
    who, facts = launcher.owner("board")
    assert who == "foreign" and facts["answers"] and facts["home_id"] is None
    assert launcher._ours("board", lid) is False
    assert launcher.healthy("board") is False
    rows = {r["service"]: r for r in launcher.status_rows()}
    assert rows["board"]["state"] == "foreign", rows["board"]
    out = launcher.stop("board")
    assert out["state"] == "not_running" and lid.live() is not None
    with pytest.raises(launcher.LaunchError, match=rf"Port {home['port']} is used by a service that does not report"):
        launcher.start("board")
    assert lid.live() is not None and run_state.read("board") is None  # never adopted


def test_caller_with_no_home_never_claims_a_listener(home, fake, monkeypatch, tmp_path):
    # the old _ours returned True for every installed CLI (no EDP_HOME) when the argv named the module
    monkeypatch.delenv("EDP_HOME")
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "run-nohome"))
    assert settings.home() is None
    lid = fake(home["port"], {"ok": True}, "-m", "edp8.service")
    assert launcher._ours("board", lid) is False
    assert launcher.stop("board")["state"] == "not_running" and lid.live() is not None


def test_another_homes_service_is_refused_named_and_left_alone(home, fake, tmp_path):
    other = tmp_path / "homeB" / ".data"
    lid = fake(home["port"], {"ok": True, "home_id": home_id_of(other), "home": str(other)})
    with pytest.raises(launcher.LaunchError) as e:
        launcher.start("board")
    assert str(e.value) == (f"Port {home['port']} is used by another Heronry ({other}). "
                            "Choose other ports with `heronry init --ports` or stop that one.")
    assert run_state.read("board") is None
    row = {r["service"]: r for r in launcher.status_rows()}["board"]
    assert row["state"] == "foreign" and row["note"] == f"another Heronry ({other})" and row["pid"] == lid.pid
    assert launcher.stop("board")["state"] == "not_running" and lid.live() is not None


def test_own_home_id_is_adopted_and_stopped(home, fake):
    lid = fake(home["port"], {"ok": True, "home_id": launcher.my_home_id(), "home": str(settings.data_dir())})
    assert launcher.owner("board")[0] == "ours" and launcher.healthy("board")
    out = launcher.start("board")
    assert out["state"] == "already_running" and out["pid"] == lid.pid
    stopped = launcher.stop("board")
    assert stopped["state"] == "stopped" and not stopped["survivors"] and lid.live() is None


def test_transition_a_recorded_service_without_identity_is_still_ours(home, fake):
    # a service this home started before identity existed: its pid file names it, its health has no home_id
    lid = fake(home["port"], {"ok": True})
    run_state.write("board", pid=lid.pid, port=home["port"], git_rev="old")
    assert launcher.owner("board")[0] == "ours" and launcher._ours("board", lid)
    assert launcher.start("board")["state"] == "already_running"
    stopped = launcher.stop("board")
    assert stopped["state"] == "stopped" and lid.live() is None and run_state.read("board") is None


def test_a_record_naming_another_homes_listener_is_not_obeyed(home, fake, tmp_path):
    # the pre-fix launcher adopted a foreign board into this home's run dir; its own answer now wins
    other = tmp_path / "homeB" / ".data"
    lid = fake(home["port"], {"ok": True, "home_id": home_id_of(other), "home": str(other)})
    run_state.write("board", pid=lid.pid, port=home["port"], git_rev="unknown")
    assert launcher._targets("board") == []
    launcher.stop("board")
    assert lid.live() is not None


def test_home_id_is_the_resolved_data_dir(tmp_path):
    d = tmp_path / "x" / ".data"
    assert home_id_of(d) == home_id_of(tmp_path / "x" / "y" / ".." / ".data")
    assert home_id_of(d) != home_id_of(tmp_path / "z" / ".data")
    if sys.platform == "win32":
        assert home_id_of(str(d).upper()) == home_id_of(d)


def test_init_picks_the_next_free_block_when_the_defaults_are_busy(monkeypatch, tmp_path):
    for k in ("EDP_HOME", "EDP8_HOME", "EDP8_PORT", "EDP8_MCP_PORT", "EDP_POOL_PORT", "EDP_BROKER_PORT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EDP_HOME", str(tmp_path / "home"))
    # defaults = a block whose ports are held (another Heronry), the next block free
    base = next(b for b in range(20400, 60000, 1000)
                if all(setup._bindable(p) for p in [*setup.port_block(b).values(), *setup.port_block(b + 1000).values()]))
    held = []
    for p in setup.port_block(base).values():
        s = socket.socket()
        s.bind(("127.0.0.1", p))
        s.listen()
        held.append(s)
    real_get = settings.get
    defaults = {setup.PORT_ENVS[k]: v for k, v in setup.port_block(base).items()}
    monkeypatch.setattr(settings, "get", lambda name: defaults.get(name) or real_get(name))
    try:
        ports, note = setup.choose_ports({})
    finally:
        for s in held:
            s.close()
    assert ports == setup.port_block(base + 1000), ports
    assert note and f"board {base + 1000}" in note
    cfg = setup.write_config(ports)
    text = cfg.read_text(encoding="utf-8")
    assert f"port = {base + 1000}" in text and f"port = {base + 1000 - 100}" in text
    # an explicit --ports N is the block at N; one explicit port is kept as given
    assert setup.choose_ports({"ports": "30400"})[0] == setup.port_block(30400)
    assert setup.choose_ports({"board-port": "31111"}) == ({"board.port": 31111}, None)


# ------------------------------------------------------------------------------------------ integration

def _env(tmp_path: Path, name: str, ports: dict[str, int], marker: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY", "CLAUDE_CONFIG_DIR", "PYTHONPATH"))}
    env.update(EDP_HOME=str(tmp_path / name), EDP_CLAUDE_CONFIG_DIR=str(tmp_path / f"claude-{name}"),
               EDP8_PORT=str(ports["board"]), EDP8_MCP_PORT=str(ports["mcp"]), EDP_POOL_PORT=str(ports["pool"]),
               EDP_BROKER_PORT=str(ports["broker"]), EDP8_EMBEDDER="none", PYTHONIOENCODING="utf-8",
               HERONRY_NO_UPDATE_CHECK="1", HERONRY_NO_BROWSER="1")
    env[MARKER] = marker
    return env


def _cli(env, *args, timeout=240) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "edp8.cli", *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)


def _init_and_start_board(env) -> ProcId:
    r = _cli(env, "init", "--harness", "claude", "--agent-home-source", str(V8))
    assert r.returncode == 0, r.stdout + r.stderr
    r = _cli(env, "start", "board", "--no-supervisor")
    assert r.returncode == 0, r.stdout + r.stderr
    return ProcId.of(run_state.listener_pid(int(env["EDP8_PORT"])))


def _health(port: int) -> dict:
    return httpx.get(f"http://127.0.0.1:{port}/v1/health", timeout=10).json()


def test_two_homes_on_separate_ports_a_stop_and_restart_never_touch_b(tmp_path, marker):
    pa, pb = _free_ports(4), _free_ports(4)
    a = _env(tmp_path, "A", dict(zip(("board", "mcp", "pool", "broker"), pa)), marker)
    b = _env(tmp_path, "B", dict(zip(("board", "mcp", "pool", "broker"), pb)), marker)
    a_board = _init_and_start_board(a)
    b_board = _init_and_start_board(b)
    b_tree = [b_board, *(ProcId.of(c.pid) for c in b_board.live().children(recursive=True))]
    assert _health(pb[0])["home"] == str((tmp_path / "B" / ".data").resolve())
    assert _health(pa[0])["home_id"] != _health(pb[0])["home_id"]

    r = _cli(a, "restart", "board")
    assert r.returncode == 0, r.stdout + r.stderr
    assert a_board.live() is None and _health(pa[0])["home"] == str((tmp_path / "A" / ".data").resolve())
    r = _cli(a, "stop")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not _listening(pa[0])
    assert all(p.live() is not None for p in b_tree), "A's stop/restart touched B"
    assert _health(pb[0])["home_id"] == home_id_of(tmp_path / "B" / ".data")
    assert _cli(b, "stop").returncode == 0 and b_board.live() is None


def test_two_homes_on_the_same_ports_b_start_refuses_and_names_a(tmp_path, marker):
    ports = dict(zip(("board", "mcp", "pool", "broker"), _free_ports(4)))
    a = _env(tmp_path, "A", ports, marker)
    b = _env(tmp_path, "B", ports, marker)
    a_board = _init_and_start_board(a)
    assert _cli(b, "init", "--harness", "claude", "--agent-home-source", str(V8)).returncode == 0
    r = _cli(b, "start", "board", "--no-supervisor")
    assert r.returncode == 1, r.stdout + r.stderr
    a_data = str((tmp_path / "A" / ".data").resolve())
    assert f"Port {ports['board']} is used by another Heronry ({a_data})" in r.stderr, r.stderr
    assert "already running" not in r.stdout
    assert not (tmp_path / "B" / ".run" / "board.json").exists()  # never adopted
    rows = {x["service"]: x for x in json.loads(_cli(b, "status", "--json").stdout)}
    assert rows["board"]["state"] == "foreign" and rows["board"]["note"] == f"another Heronry ({a_data})"
    r = _cli(b, "stop")
    assert r.returncode == 0, r.stdout + r.stderr
    assert a_board.live() is not None and _health(ports["board"])["home"] == a_data
    assert _cli(a, "stop").returncode == 0 and a_board.live() is None


def test_a_run_record_that_cannot_be_written_fails_the_start_and_stops_the_service(home, fake, monkeypatch):
    """S8 (architect m-a0977dd5c8): the installed app's run-record writes failed (Errno 13); the services ran
    untracked, orphans `stop` could not find. A refused record write is a failed start: the process goes."""
    spawned: list[ProcId] = []

    def fake_detach(argv, **kw):
        spawned.append(fake(home["port"], {"ok": True, "home_id": launcher.my_home_id(),
                                           "home": str(settings.data_dir())}))
        return spawned[-1], None
    monkeypatch.setattr(launcher, "detach", fake_detach)
    monkeypatch.setattr(launcher, "assign_job", lambda *a, **k: False)

    def refused(*a, **k):
        raise PermissionError(13, "Permission denied", str(settings.run_dir() / "board.json"))
    monkeypatch.setattr(run_state, "write", refused)
    with pytest.raises(launcher.LaunchError) as err:
        launcher.start("board", wait_s=20)
    msg = str(err.value)
    assert f"could not write {run_state._path('board')}" in msg and "stopped it again" in msg
    assert "antivirus" not in msg.lower() and "heronry doctor" in msg
    assert spawned and spawned[0].live() is None and not _listening(home["port"])


def test_doctor_names_a_folder_this_process_cannot_write(home, monkeypatch, capsys):
    real = Path.write_text

    def guarded(self, *a, **k):
        if self.name.startswith(".heronry-write-probe") and self.parent == settings.run_dir():
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "write_text", guarded)
    assert setup.write_probe(settings.data_dir()) is None
    assert "Permission denied (errno 13" in (setup.write_probe(settings.run_dir()) or "")
    setup.doctor_cmd([])
    out = capsys.readouterr().out
    assert "FAIL   run folder  could not write " + str(settings.run_dir()) in out and "antivirus" not in out.lower()
    assert "ok     data folder" in out and "ok     logs folder" in out
