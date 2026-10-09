"""e0cec S6 task 4 (c-11ee92af13): ONE pain store — the board's database.

The repo and installed jsonl stores are imported (deduped by id, resolutions carried over); `pain(action=…)`
reads and writes the board; statuses open / fixed(commit) / ticket(id) / duplicate / invalid; the epic's
architect may resolve `fixed` when the note cites a commit reachable from main.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

import edp8.bundles as bundles_mod
from edp8 import pain_dispositions, pains, records
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import PainStatus, Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store


@pytest.fixture
def files(tmp_path, monkeypatch):
    repo, inst = tmp_path / "repo" / "pain-points.jsonl", tmp_path / "inst" / "pain-points.jsonl"
    repo.parent.mkdir(), inst.parent.mkdir()
    monkeypatch.delenv("EDP8_PAIN_FILE", raising=False)
    monkeypatch.setenv("EDP8_PAIN_IMPORT", os.pathsep.join([str(inst), str(repo)]))
    records._pain_seen.clear()
    pains._synced.clear()
    return repo, inst


@pytest.fixture
def board(files):
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board):
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    arch = board.participant_create("agent", Role.architect, f"architect.{epic.id}", id_=f"architect.{epic.id}")
    eng = board.participant_create("agent", Role.engineer, f"engineer.{epic.id}", id_=f"engineer.{epic.id}")
    return {"owner": owner, "epic": epic, "arch": arch, "eng": eng}


def _line(path, **kw):
    rec = {"id": "p-aaaaaaa1", "ts": "2026-09-01T10:00:00Z", "role": "engineer", "handle": "engineer.x",
           "severity": "low", "area": "tools", "symptom": "link_delete drops unknown ids",
           "expected": "a not_found error", "evidence": "m-1", **kw}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _res(path, pid, status, by="", ts="2026-09-02T10:00:00Z", note=""):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": pid, "resolves": True, "status": status, "fixed_by": by, "ts": ts, "note": note}) + "\n")


def _rows(board, status="all"):
    return {r["id"]: r for r in pains.query(board.store, status=status)}


# ----------------------------------------------------------------------------- import
def test_import_dedupes_the_two_stores_by_id_and_carries_resolutions(board, files):
    repo, inst = files
    _line(repo, id="p-aaaaaaa1")
    _line(inst, id="p-aaaaaaa1", symptom="the same pain in the installed store")  # same id: one pain
    _line(inst, id="p-bbbbbbb2", symptom="only installed")
    _line(repo, id="p-ccccccc3", symptom="fixed in the repo store")
    _res(repo, "p-ccccccc3", "fixed", by="abc1234")
    _line(repo, id="p-ddddddd4", symptom="old one")
    _line(repo, id="p-eeeeeee5", symptom="its replacement", supersedes="p-ddddddd4")
    _res(repo, "p-ddddddd4", "superseded", by="p-eeeeeee5")
    out = pains.sync(board)
    assert out["added"] == 5 and out["seen"] == 6
    rows = _rows(board)
    assert set(rows) == {"p-aaaaaaa1", "p-bbbbbbb2", "p-ccccccc3", "p-ddddddd4", "p-eeeeeee5"}
    assert rows["p-aaaaaaa1"]["symptom"] == "the same pain in the installed store"  # the installed store has precedence
    assert (rows["p-ccccccc3"]["status"], rows["p-ccccccc3"]["fixed_commit"]) == ("fixed", "abc1234")
    assert (rows["p-ddddddd4"]["status"], rows["p-ddddddd4"]["dup_of"]) == ("duplicate", "p-eeeeeee5")
    assert pains.sync(board, force=True)["added"] == 0  # idempotent: a second import adds nothing


def test_a_record_with_dup_of_imports_as_a_duplicate_and_a_bom_line_is_read(board, files):
    repo, _ = files
    repo.write_bytes("﻿".encode("utf-8") + (json.dumps(
        {"id": "p-1111111a", "ts": "t", "severity": "low", "area": "x", "symptom": "root", "expected": "e"}) + "\n").encode())
    _line(repo, id="p-2222222b", dup_of="p-1111111a", symptom="again")
    pains.sync(board)
    rows = _rows(board)
    assert rows["p-1111111a"]["status"] == "open"
    assert (rows["p-2222222b"]["status"], rows["p-2222222b"]["dup_of"]) == ("duplicate", "p-1111111a")
    assert pains.read(board.store, "p-1111111a")["duplicates"] == ["p-2222222b"]


def test_a_legacy_line_without_an_id_gets_a_stable_one(board, files):
    repo, _ = files
    with open(repo, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "t1", "severity": "low", "area": "x", "symptom": "no id here", "expected": "e"}) + "\n")
    pains.sync(board)
    [pid] = _rows(board)
    pains.sync(board, force=True)
    assert list(_rows(board)) == [pid] and pid.startswith("p-")


def test_the_board_wins_over_a_later_file_and_a_file_resolution_closes_an_open_import(board, files, rig):
    repo, _ = files
    _line(repo, id="p-aaaaaaa1")
    _line(repo, id="p-bbbbbbb2", symptom="resolved later by the shell script")
    pains.sync(board)
    pains.resolve(board.store, "p-aaaaaaa1", "invalid", who="owner", role="owner", note="not a bug")
    _res(repo, "p-aaaaaaa1", "fixed", by="deadbee")  # a stale shell resolution never overrides the board's
    _res(repo, "p-bbbbbbb2", "fixed", by="abcdef1")
    pains.sync(board)
    rows = _rows(board)
    assert rows["p-aaaaaaa1"]["status"] == "invalid"
    assert (rows["p-bbbbbbb2"]["status"], rows["p-bbbbbbb2"]["fixed_commit"]) == ("fixed", "abcdef1")


def test_sync_is_mtime_gated(board, files):
    repo, _ = files
    _line(repo)
    assert pains.sync(board) is not None
    assert pains.sync(board) is None  # nothing moved: no re-read
    _line(repo, id="p-bbbbbbb2", symptom="new")
    assert pains.sync(board)["added"] == 1


# ----------------------------------------------------------------------------- the store
def test_file_read_query_with_status_filters(board, files, rig, monkeypatch):
    monkeypatch.setattr(pains, "commit_on_remote", lambda sha: sha == "abc1234")
    a = pains.file(board.store, {"severity": "low", "area": "tools", "symptom": "alpha thing broke",
                                 "expected": "works", "evidence": "m-1"}, role="engineer", handle="engineer.x")
    b = pains.file(board.store, {"severity": "high", "area": "board", "symptom": "beta thing broke",
                                 "expected": "works", "evidence": "m-2"}, role="qa", handle="qa.x")
    c = pains.file(board.store, {"severity": "low", "area": "tools", "symptom": "alpha again", "expected": "works",
                                 "evidence": "m-3", "dup_of": a["id"]}, role="engineer", handle="engineer.y")
    assert {r["id"] for r in pains.query(board.store)} == {a["id"], b["id"]}  # open by default; a duplicate is not open
    assert [r["id"] for r in pains.query(board.store, q="beta")] == [b["id"]]
    assert [r["id"] for r in pains.query(board.store, area="tools", status="duplicate")] == [c["id"]]
    pains.resolve(board.store, a["id"], "fixed", who="owner", role="owner", commit="abc1234")
    pains.resolve(board.store, b["id"], "ticket", who="owner", role="owner", ticket_id=rig["epic"].id)
    assert [r["id"] for r in pains.query(board.store, status="fixed")] == [a["id"]]
    assert [r["ticket_ref"] for r in pains.query(board.store, status="ticket")] == [rig["epic"].id]
    [fx] = pains.query(board.store, status="fixed")
    assert fx["commit_url"].endswith("/commit/abc1234") and fx["commit_url"].startswith("https://github.com/")
    assert "commit_url" not in pains.query(board.store, status="ticket")[0]
    assert len(pains.query(board.store, status="all")) == 3
    got = pains.read(board.store, a["id"])
    assert got["resolution"]["fixed_commit"] == "abc1234" and got["resolution"]["by"] == "owner"
    assert got["duplicates"] == [c["id"]]
    with pytest.raises(pains.PainError):
        pains.query(board.store, status="superseded")


def test_filing_validates_and_supersedes_closes_the_old_one(board, files):
    with pytest.raises(pains.PainError):
        pains.file(board.store, {"severity": "low", "area": "x"}, role="qa", handle="qa")
    with pytest.raises(pains.PainError):
        pains.file(board.store, {"severity": "low", "area": "x", "symptom": "s", "expected": "e", "evidence": "v",
                                 "dup_of": "p-missing"}, role="qa", handle="qa")
    old = pains.file(board.store, {"severity": "low", "area": "x", "symptom": "s", "expected": "e", "evidence": "v"},
                     role="qa", handle="qa")
    new = pains.file(board.store, {"severity": "low", "area": "x", "symptom": "s2", "expected": "e", "evidence": "v",
                                   "supersedes": old["id"]}, role="qa", handle="qa")
    got = pains.read(board.store, old["id"])
    assert (got["status"], got["dup_of"]) == ("duplicate", new["id"])


def test_resolve_demands_the_evidence_its_status_names(board, files, rig):
    p = pains.file(board.store, {"severity": "low", "area": "x", "symptom": "s", "expected": "e", "evidence": "v"},
                   role="qa", handle="qa")
    kw = {"who": "owner", "role": "owner"}
    with pytest.raises(pains.PainError):
        pains.resolve(board.store, p["id"], "ticket", ticket_id="s-nope", **kw)
    with pytest.raises(pains.PainError):
        pains.resolve(board.store, p["id"], "duplicate", dup_of=p["id"], **kw)
    with pytest.raises(pains.PainError):
        pains.resolve(board.store, p["id"], "open", **kw)
    out = pains.resolve(board.store, p["id"], "invalid", note="works as designed", **kw)
    assert out["status"] == "invalid" and out["resolved_by"] == "owner"


# ----------------------------------------------------------------------------- who resolves
def _filed(board):
    return pains.file(board.store, {"severity": "low", "area": "x", "symptom": "s", "expected": "e", "evidence": "v"},
                      role="qa", handle="qa")["id"]


def test_an_epics_architect_resolves_fixed_with_a_commit_reachable_from_main(board, files, rig, monkeypatch):
    pid = _filed(board)
    asked = []
    monkeypatch.setattr(pains, "commit_on_main", lambda sha: asked.append(sha) or (sha == "abc1234", "not on main"))
    out = pains.resolve(board.store, pid, "fixed", who=rig["arch"].handle, role="architect", has_epic=True,
                        note="fixed in abc1234 (S6)")
    assert asked == ["abc1234"]
    got = pains.read(board.store, pid)
    assert got["status"] == "fixed" and got["fixed_commit"] == "abc1234"
    assert got["resolution"]["by"] == rig["arch"].handle  # who, and which commit
    assert out["resolved_by"] == rig["arch"].handle


def test_an_architect_is_refused_without_a_main_reachable_commit(board, files, rig, monkeypatch):
    pid = _filed(board)
    monkeypatch.setattr(pains, "commit_on_main", lambda sha: (False, f"{sha} is not on main"))
    arch = {"who": rig["arch"].handle, "role": "architect", "has_epic": True}
    with pytest.raises(pains.PainError, match="reachable from main"):
        pains.resolve(board.store, pid, "fixed", note="fixed in abc1234", **arch)
    with pytest.raises(pains.PainError, match="names the commit"):
        pains.resolve(board.store, pid, "fixed", note="it is fixed now", **arch)
    with pytest.raises(pains.PainError, match="fixed only"):
        pains.resolve(board.store, pid, "invalid", note="abc1234", **arch)
    assert pains.read(board.store, pid)["status"] == "open"


def test_other_seats_never_resolve(board, files, rig, monkeypatch):
    pid = _filed(board)
    monkeypatch.setattr(pains, "commit_on_main", lambda sha: (True, ""))
    for role, has_epic in (("engineer", False), ("qa", False), ("sme", False), ("architect", False)):
        with pytest.raises(pains.PainError, match="may not resolve"):
            pains.resolve(board.store, pid, "fixed", who="x", role=role, has_epic=has_epic, commit="abc1234")
    assert pains.resolve(board.store, pid, "fixed", who="adm", role="engineer", admin=True, commit="abc1234")["status"] == "fixed"


def test_git_check_rejects_a_sha_that_is_not_an_ancestor_of_main(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True, text=True).stdout.strip()
    run("init", "-b", "main")
    (repo / "a").write_text("1")
    run("add", "a")
    run("commit", "-m", "one")
    on_main = run("rev-parse", "HEAD")
    run("checkout", "-b", "side")
    (repo / "b").write_text("2")
    run("add", "b")
    run("commit", "-m", "two")
    off_main = run("rev-parse", "HEAD")
    monkeypatch.setenv("EDP8_REPO", str(repo))
    assert pains.commit_on_main(on_main)[0] is True
    ok, why = pains.commit_on_main(off_main)
    assert ok is False and "not on main" in why
    assert pains.commit_on_main("0123456789abcdef")[0] is False


def test_commit_link_only_for_a_commit_the_remote_has(tmp_path, monkeypatch, board):
    """sweep #5 (note-8f0629190d): github.com/<repo>/commit/<sha> 404s for an unpushed commit, so no commit_url then."""
    import subprocess
    from edp8 import pain_git
    remote = tmp_path / "remote.git"
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True, text=True).stdout.strip()
    run("init", "-b", "main")
    (repo / "a").write_text("1")
    run("add", "a")
    run("commit", "-m", "one")
    run("remote", "add", "origin", str(remote))
    run("push", "origin", "main")
    pushed = run("rev-parse", "HEAD")
    (repo / "b").write_text("2")
    run("add", "b")
    run("commit", "-m", "two")
    local_only = run("rev-parse", "HEAD")
    monkeypatch.setenv("EDP8_REPO", str(repo))
    pain_git._REMOTE_YES.clear()
    pain_git._REMOTE_NO.clear()
    assert pain_git.commit_on_remote(pushed) is True
    assert pain_git.commit_on_remote(local_only) is False
    assert pain_git.commit_on_remote("0123456789abcdef") is False
    for sha in (pushed, local_only):
        p = pains.file(board.store, {"severity": "low", "area": "x", "symptom": f"s {sha[:7]}", "expected": "e", "evidence": "m-1"},
                       role="engineer", handle="engineer.x")
        pains.resolve(board.store, p["id"], "fixed", who="owner", role="owner", commit=sha)
    rows = {r["fixed_commit"]: r for r in pains.query(board.store, status="fixed")}
    assert rows[pushed]["commit_url"].endswith(f"/commit/{pushed}")
    assert "commit_url" not in rows[local_only]


# ----------------------------------------------------------------------------- dispositions (note-5df2381eb1)
def test_dispositions_route_only_imported_open_pains(board, files, rig):
    repo, _ = files
    for pid in ("p-892b786f", "p-3eba4926", "p-c3c5d460", "p-a05affa0", "p-a3ae2179", "p-69a7583c"):
        _line(repo, id=pid, symptom=f"imported {pid}")
    pains.sync(board)
    rows = _rows(board)
    for pid in ("p-892b786f", "p-3eba4926", "p-c3c5d460"):
        assert (rows[pid]["status"], rows[pid]["fixed_commit"]) == ("fixed", "4644c81")
    assert rows["p-69a7583c"]["status"] == "duplicate" and rows["p-69a7583c"]["dup_of"] == "p-a3ae2179"
    assert rows["p-a05affa0"]["status"] == "open"  # its story does not exist on this board: skipped, not guessed
    got = pains.read(board.store, "p-892b786f")
    assert got["resolution"]["by"] == "board:note-5df2381eb1"


def test_a_routed_ticket_must_exist_and_a_board_filed_pain_is_never_routed(board, files, rig, monkeypatch):
    s = board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="S15")
    monkeypatch.setattr(pain_dispositions, "DISPOSITIONS", (("p-a05affa0", "ticket", s.id, "n"),
                                                           ("p-bbbbbbb2", "fixed", "4644c81", "n")))
    repo, _ = files
    _line(repo, id="p-a05affa0")
    pains.sync(board)
    mine = pains.file(board.store, {"severity": "low", "area": "x", "symptom": "s", "expected": "e", "evidence": "v"},
                      role="qa", handle="qa")
    board.store.put("pain", pains.get(board.store, mine["id"]).model_copy(update={"id": "p-bbbbbbb2"}))
    assert pain_dispositions.apply(board) == 0
    rows = _rows(board)
    assert (rows["p-a05affa0"]["status"], rows["p-a05affa0"]["ticket_ref"]) == ("ticket", s.id)
    assert rows["p-bbbbbbb2"]["status"] == "open"


# ----------------------------------------------------------------------------- REST + tool + readers
def _client(board):
    return TestClient(create_app(board, admin_token="t"))


def test_rest_routes_read_and_write_the_board_and_gate_resolution(board, files, rig, monkeypatch):
    repo, _ = files
    _line(repo, id="p-aaaaaaa1")
    c = _client(board)
    own, arch, eng = ({"X-Participant": h} for h in ("owner", rig["arch"].id, rig["eng"].id))
    assert [r["id"] for r in c.get("/v1/pains", headers=eng).json()["value"]] == ["p-aaaaaaa1"]  # imported on read
    f = c.post("/v1/pains", headers=eng, json={"severity": "low", "area": "tools", "symptom": "s2", "expected": "e",
                                              "evidence": "v"}).json()
    assert f["ok"], f
    assert not c.post("/v1/pains/p-aaaaaaa1/resolve", headers=eng, json={"status": "invalid"}).json()["ok"]
    monkeypatch.setattr(pains, "commit_on_main", lambda sha: (sha == "abc1234", "off main"))
    bad = c.post("/v1/pains/p-aaaaaaa1/resolve", headers=arch, json={"status": "fixed", "note": "see 9999999"})
    assert not bad.json()["ok"] and "reachable" in bad.text
    ok = c.post("/v1/pains/p-aaaaaaa1/resolve", headers=arch, json={"status": "fixed", "note": "fixed by abc1234"}).json()
    assert ok["ok"] and ok["value"]["resolved_by"] == rig["arch"].handle
    [fixed] = c.get("/v1/pains?status=fixed", headers=own).json()["value"]
    assert fixed["fixed_commit"] == "abc1234"
    t = c.post(f"/v1/pains/{f['value']['id']}/resolve", headers=own,
               json={"status": "ticket", "ticket_id": rig["epic"].id}).json()
    assert t["ok"]
    assert [r["id"] for r in c.get("/v1/pains?status=ticket", headers=own).json()["value"]] == [f["value"]["id"]]
    assert c.post("/v1/pains/import", headers=eng).status_code in (400, 403)
    assert c.post("/v1/pains/import", headers=own).json()["ok"]


def test_pain_tool_resolves_with_commit_and_ticket(board, files, rig, monkeypatch):
    c = _client(board)
    set_client(BoardClient(participant="owner", admin_token="t", client=c))
    tool = ALL_TOOLS["pain"]
    filed = tool.handler(tool.args_model(action="file", severity="low", area="tools", symptom="s", expected="e",
                                         evidence="v"))
    pid = filed["value"]["id"]
    done = tool.handler(tool.args_model(action="resolve", id=pid, status="ticket", ticket_id=rig["epic"].id))
    assert done["ok"], done
    rows = tool.handler(tool.args_model(action="query", status="ticket"))["value"]["items"]
    assert [r["id"] for r in rows] == [pid] and rows[0]["ticket_ref"] == rig["epic"].id
    miss = tool.handler(tool.args_model(action="resolve", id=pid, status="duplicate"))
    assert not miss["ok"]


def test_lessons_and_the_doctor_read_the_board_not_a_file(board, files, rig):
    mine = pains.file(board.store, {"severity": "low", "area": "tools", "symptom": "a pain filed on the board only",
                                    "expected": "it becomes a lesson", "evidence": "v"}, role="qa", handle="qa")
    made = records.lessons_from_pains(board)
    assert [le.evidence for le in made] == [[mine["id"]]]
    pains.resolve(board.store, mine["id"], "invalid", who="owner", role="owner")
    from edp8 import doctor
    assert doctor.pains(board)["open"] == 0
    other = pains.file(board.store, {"severity": "low", "area": "x", "symptom": "still open", "expected": "e",
                                     "evidence": "v"}, role="qa", handle="qa")
    assert [p["id"] for p in doctor.pains(board)["pains"]] == [other["id"]]
