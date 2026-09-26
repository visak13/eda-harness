"""S3 (s-870e401942): the `heronry` CLI drives a private instance end to end.

Everything runs in subprocesses with a scrubbed environment (no fleet variable leaks in), a temp
EDP_HOME outside any checkout and free ports, so the fleet's services are never touched. The pool and
broker run from their own venvs (EDP_POOL_PYTHON / EDP_BROKER_PYTHON): this venv holds edp8 only; the
installed-wheel run (one tool venv for all four packages) is the story's evidence script.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from edp_contracts.proc import kill_tree, scan_env_marker

V8 = Path(__file__).resolve().parents[1]
ROOT = V8.parent
MARKER = "EDP_S3_TEST_MARKER"


def _venv_py(project: Path) -> Path:
    return project / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


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


@pytest.fixture
def inst(tmp_path):
    board, mcp, pool, broker = _free_ports(4)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY", "CLAUDE_CONFIG_DIR", "PYTHONPATH"))}
    env.update(EDP_HOME=str(tmp_path / "home"), EDP_CLAUDE_CONFIG_DIR=str(tmp_path / "claude"),
               EDP8_PORT=str(board), EDP8_MCP_PORT=str(mcp), EDP_POOL_PORT=str(pool), EDP_BROKER_PORT=str(broker),
               EDP8_EMBEDDER="none", PYTHONIOENCODING="utf-8", HERONRY_NO_UPDATE_CHECK="1", HERONRY_NO_BROWSER="1")
    env[MARKER] = uuid.uuid4().hex
    for svc, project in (("POOL", ROOT / "edp-pool"), ("BROKER", ROOT / "edp-broker")):
        py = _venv_py(project)
        if py.is_file():
            env[f"EDP_{svc}_PYTHON"] = str(py)
    yield {"env": env, "ports": {"board": board, "mcp": mcp, "pool": pool, "broker": broker}, "home": tmp_path / "home"}
    # no-survivor fixture: whatever this test started (the marker is in every child's environment) dies
    for ident in scan_env_marker(MARKER, env[MARKER]):
        kill_tree(ident, grace=2.0)


def cli(inst, *args, timeout=240) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "edp8.cli", *args], env=inst["env"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)


def test_init_refuses_without_a_harness(inst):
    r = cli(inst, "init")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "no harness selected" in r.stderr and "--harness" in r.stderr
    assert not (inst["home"] / "config.toml").exists()


def test_codexless_init_prints_the_fable_notice_and_writes_trust(inst):
    r = cli(inst, "init", "--harness", "claude", "--agent-home-source", str(V8))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOTICE:" in r.stdout and "Fable" in r.stdout
    cfg = (inst["home"] / "config.toml").read_text(encoding="utf-8")
    assert 'harnesses = ["claude"]' in cfg
    trust = json.loads((Path(inst["env"]["EDP_CLAUDE_CONFIG_DIR"]) / ".claude.json").read_text(encoding="utf-8"))
    home = str((inst["home"] / "agent-home").resolve()).replace("\\", "/")
    assert trust["projects"][home]["hasTrustDialogAccepted"] is True
    # secrets exist and a re-run keeps them
    tok = (inst["home"] / "admin.token").read_text(encoding="utf-8")
    assert cli(inst, "init", "--harness", "claude,codex", "--agent-home-source", str(V8)).returncode == 0
    assert (inst["home"] / "admin.token").read_text(encoding="utf-8") == tok
    assert "NOTICE:" not in cli(inst, "init", "--harness", "codex", "--agent-home-source", str(V8)).stdout


@pytest.mark.skipif(not _venv_py(ROOT / "edp-pool").is_file() or not _venv_py(ROOT / "edp-broker").is_file(),
                    reason="needs the edp-pool and edp-broker venvs")
def test_start_status_idempotent_health_stop_leaves_no_process(inst):
    # a token_urlsafe secret can start with "-": the first start must still bring every service up
    tok = "-" + uuid.uuid4().hex
    assert cli(inst, "init", "--harness", "claude", f"--admin-token={tok}",
               "--agent-home-source", str(V8)).returncode == 0
    try:
        r = cli(inst, "start")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "usage:" not in r.stdout + r.stderr, r.stdout + r.stderr
        # register_defaults ran on the first start: the owner init minted a token for can sign in
        owner_tok = json.loads((inst["home"] / "tokens.json").read_text(encoding="utf-8"))["owner"]
        who = httpx.get(f"http://127.0.0.1:{inst['ports']['board']}/v1/participants",
                        headers={"X-Participant": "@owner", "X-Token": owner_tok}, timeout=10)
        assert who.status_code == 200, who.text
        rows = {x["service"]: x for x in json.loads(cli(inst, "status", "--json").stdout)}
        for svc in ("board", "mcp", "pool", "broker"):
            assert rows[svc]["state"] == "up" and rows[svc]["pid"], rows[svc]
            assert rows[svc]["url"] == f"http://127.0.0.1:{inst['ports'][svc]}", rows[svc]
        assert rows["supervisor"]["state"] == "up"
        again = cli(inst, "start")
        assert again.returncode == 0, again.stdout + again.stderr
        for svc in ("board", "mcp", "pool", "broker"):
            assert any(line.startswith(svc) and "already running" in line for line in again.stdout.splitlines()), again.stdout
        assert httpx.get(f"http://127.0.0.1:{inst['ports']['board']}/v1/health", timeout=10).status_code == 200
    finally:
        stop = cli(inst, "stop")
    assert stop.returncode == 0, stop.stdout + stop.stderr
    assert scan_env_marker(MARKER, inst["env"][MARKER]) == []
    for p in inst["ports"].values():
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", p)) != 0, f"port {p} still answers"


def _fake_v8(root: Path) -> dict:
    """A small v8 checkout: a real board DB (epic, story, participants), tokens, uploads, UI files, .env."""
    from edp8.board import Board
    from edp8.schemas import Role, TicketKind, WorkType
    from edp8.store import Store

    (root / ".data" / "uploads").mkdir(parents=True)
    board = Board(Store(root / ".data" / "edp8.db"))
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    board.participant_create("agent", Role.architect, "arch", id_="arch")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    board.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    board.store._conn.close()
    secret = "imp-" + uuid.uuid4().hex
    (root / "tokens.json").write_text(json.dumps({"owner": secret, "agents": {}}), encoding="utf-8")
    (root / ".data" / "uploads" / "art-1.png").write_bytes(b"\x89PNG fake")
    (root / ".data" / "board.log").write_text("log line\n", encoding="utf-8")
    (root / "ui-settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    (root / "slack_map.json").write_text("{}", encoding="utf-8")
    admin = "-adm" + uuid.uuid4().hex
    env = f"# c\nEDP8_NOT_A_SETTING=1\nEDP8_ADMIN_TOKEN={admin}\nEDP8_DB=C:/elsewhere/x.db\n"
    (root / ".env").write_text(env, encoding="utf-8")
    return {"owner_token": secret, "admin": admin}


def _tree_hash(root: Path) -> dict[str, str]:
    import hashlib
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_import_dry_run_then_apply_keeps_counts_tokens_and_the_source(inst, tmp_path):
    src = tmp_path / "old" / "v8"
    creds = _fake_v8(src)
    before = _tree_hash(src)
    assert cli(inst, "init", "--harness", "claude", "--agent-home-source", str(V8)).returncode == 0

    dry = cli(inst, "import", "--from", str(src))
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "board DB" in dry.stdout and "'epics': 1, 'tickets': 2, 'participants': 2" in dry.stdout, dry.stdout
    assert "dry run: nothing was written" in dry.stdout
    assert "skip     EDP8_NOT_A_SETTING" in dry.stdout and "skip     EDP8_DB" in dry.stdout
    assert creds["admin"] not in dry.stdout and creds["owner_token"] not in dry.stdout  # secrets never printed
    assert not (inst["home"] / "data" / "edp8.db").exists() and not list(inst["home"].rglob("edp8.db"))

    real = cli(inst, "import", "--from", str(src), "--apply")
    assert real.returncode == 0, real.stdout + real.stderr
    assert "imported: {'epics': 1, 'tickets': 2, 'participants': 2}" in real.stdout, real.stdout
    assert _tree_hash(src) == before  # the source is byte-unchanged
    assert not list(inst["home"].rglob("board.log"))  # logs stay behind
    assert list(inst["home"].rglob("art-1.png"))

    try:
        r = cli(inst, "start", "board", "--no-supervisor")
        assert r.returncode == 0, r.stdout + r.stderr
        base = f"http://127.0.0.1:{inst['ports']['board']}"
        ps = httpx.get(f"{base}/v1/participants", headers={"X-Participant": "@owner", "X-Token": creds["owner_token"]},
                       timeout=10)
        assert ps.status_code == 200, ps.text
        assert {"owner", "arch"} <= {p["handle"].lstrip("@") for p in ps.json()["value"]}
        bad = httpx.get(f"{base}/v1/participants", headers={"X-Participant": "@owner", "X-Token": "wrong"}, timeout=10)
        assert bad.status_code == 401
        adm = httpx.post(f"{base}/v1/participants", headers={"X-Admin": creds["admin"]}, timeout=10,
                         json={"type": "agent", "role": "engineer", "handle": "imported-admin-check"})
        assert adm.status_code == 200, adm.text  # the .env admin token moved to the admin.token file
    finally:
        cli(inst, "stop")
    assert _tree_hash(src) == before
