"""Design §19 rule 7 (criterion c-ef61da3b6e): the consult write-fence root is derived from
the run (write_dir → git root of the files passed → cwd), never from a hard-coded project;
the fence report lives only in the run manifest; and the note consult posts to a ticket
thread carries the answer plus ONE line naming the run id and 'fence clean' / 'FAILED
CLOSED' — never a file path from another project.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edp8 import consult as consult_mod
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, _fence_status_line, set_client
from edp8.client import BoardClient
from edp8.consult import run_fence_root
from edp8.service import create_app
from edp8.store import Store

_FAKE_MCP = [{"name": "unreal-mcp", "transport": "streamable_http"}]


def _git_init(root: Path, name: str = "tracked.txt", body: str = "original\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    f = root / name
    f.write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@e.st", "-c", "user.name=test",
                    "commit", "-q", "-m", "init"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f


# ---------------------------------------------------------------- run_fence_root

def test_fence_root_prefers_git_root_of_write_dir(tmp_path, monkeypatch):
    monkeypatch.delenv(consult_mod._UE_ROOT_ENV, raising=False)
    _git_init(tmp_path / "proj")
    sub = tmp_path / "proj" / "assets"
    sub.mkdir()
    assert run_fence_root(str(sub), None) == consult_mod._realpath(tmp_path / "proj")


def test_fence_root_from_git_root_of_files(tmp_path, monkeypatch):
    monkeypatch.delenv(consult_mod._UE_ROOT_ENV, raising=False)
    f = _git_init(tmp_path / "proj")
    assert run_fence_root(None, [str(f)]) == consult_mod._realpath(tmp_path / "proj")


def test_fence_root_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv(consult_mod._UE_ROOT_ENV, raising=False)
    plain = tmp_path / "loose"
    plain.mkdir()
    assert run_fence_root(None, None, cwd=str(plain)) == consult_mod._realpath(plain)


def test_fence_root_honours_explicit_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(consult_mod._UE_ROOT_ENV, str(tmp_path / "pinned"))
    assert run_fence_root(str(tmp_path / "anywhere"), None) == Path(str(tmp_path / "pinned"))


def test_no_hardcoded_spacetravel_default(monkeypatch, tmp_path):
    monkeypatch.delenv(consult_mod._UE_ROOT_ENV, raising=False)
    root = run_fence_root(None, None, cwd=str(tmp_path))
    assert "SpaceTravel" not in str(root)


# ---------------------------------------------------------------- one-line note, no paths

def test_fence_status_line_never_contains_a_path():
    ok = _fence_status_line({"ok": True, "value": {}}, "run-1")
    assert ok == "run run-1, fence clean" and "/" not in ok and "\\" not in ok
    boundary = _fence_status_line({"ok": False, "error": {"code": "boundary"}}, "run-1")
    assert "FAILED CLOSED" in boundary and "consult_status(run_id='run-1')" in boundary
    assert "\\" not in boundary and "/" not in boundary.replace("run_id", "")


# ---------------------------------------------------------------- end-to-end thread note

@pytest.fixture
def raw_client():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


def _register(raw, role, handle):
    admin = BoardClient(participant=None, admin_token="t", client=raw)
    r = admin._request("POST", "/v1/participants", admin=True,
                       json={"type": "agent", "role": role, "handle": handle})
    assert r["ok"], r
    return r["value"]["id"]


def test_thread_note_has_no_path_from_an_unrelated_dirty_repo(raw_client, tmp_path, monkeypatch):
    # the run's own project (files come from here) and a completely unrelated repo that
    # happens to have dirty files — the S0d "spacetravel path leaked onto the thread" shape.
    run_repo = tmp_path / "v8run"
    run_file = _git_init(run_repo)
    other = tmp_path / "unrelated"
    _git_init(other, name="secret_other_project_file.txt")
    (other / "secret_other_project_file.txt").write_text("DIRTY IN ANOTHER PROJECT\n", encoding="utf-8")
    # a concurrent edit in the run repo too — the fence may SEE it, but the note still names no path
    run_file.write_text("concurrent edit\n", encoding="utf-8")

    monkeypatch.delenv(consult_mod._UE_ROOT_ENV, raising=False)   # no hard-coded protected tree
    monkeypatch.setenv(consult_mod._LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: "codex")
    monkeypatch.setattr(consult_mod, "discover_mcp_servers", lambda codex, timeout_s=30: (list(_FAKE_MCP), None))

    def fake_codex(argv, timeout_s):
        Path(argv[argv.index("-o") + 1]).write_text("here is the second opinion", encoding="utf-8")
        return json.dumps({"type": "thread.started", "thread_id": "t"}) + "\n", 0, False

    monkeypatch.setattr(consult_mod, "_run_codex", fake_codex)

    owner = _register(raw_client, "owner", "owner-fence")
    set_client(BoardClient(participant=owner, admin_token="t", client=raw_client))
    epic = ALL_TOOLS["ticket_create"].handler(
        ALL_TOOLS["ticket_create"].args_model(kind="epic", work_type="chore", title="fence target"))
    tid = epic["value"]["id"]

    eng = _register(raw_client, "engineer", "eng-fence")
    client = BoardClient(participant=eng, admin_token="t", client=raw_client)
    set_client(client)

    resp = ALL_TOOLS["consult"].handler(
        ALL_TOOLS["consult"].args_model(question="review this", ticket_id=tid, files=[str(run_file)]))
    assert resp["ok"] is True, resp

    notes = [m.get("text") or "" for m in client.message_query(ticket_id=tid)["value"]]
    joined = "\n".join(notes)
    assert "here is the second opinion" in joined          # the answer is on the thread
    assert "fence clean" in joined                         # the one-line fence status
    # NO path from the unrelated repo leaks onto the thread
    assert "secret_other_project_file" not in joined
    assert str(other) not in joined
    # and the run repo's own concurrent path is not dumped either — the note is path-free
    assert "tracked.txt" not in joined

    # the fence report still exists — but only in the run manifest, reachable via consult_status
    st = consult_mod.consult_status(resp["value"].get("run_id"))
    assert st["ok"] and st["value"]["manifest"] is not None
