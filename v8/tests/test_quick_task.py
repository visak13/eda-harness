"""S-QUICK (s-9d62ba5f6c, design-34bf11cc07 §4.2, owner m-5b3db5cb0d): the owner's quick task — a
parentless story tagged `quick` that the owner opens, its engineer plans and writes criteria for, and the
owner verdicts from Needs you. Covers c-b92ae4a8dd (creators, no design_ref, no story cap) plus the
board halves of the one-step endpoint and the owner verdict loop."""
from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import pool_adapter
from edp8.board import STORY_CAP, Board, BoardError
from edp8.schemas import Check, DocType, Role, TicketKind, TicketStatus, Verdict, WorkType
from edp8.service import create_app
from edp8.store import Store
from edp8 import views

ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}


@pytest.fixture
def b():
    board = Board(Store(":memory:"))
    ps = {
        "owner": board.participant_create("human", Role.owner, "owner", id_="owner"),
        "arch": board.participant_create("agent", Role.architect, "arch", id_="arch"),
        "eng": board.participant_create("agent", Role.engineer, "eng", id_="eng"),
        "qa": board.participant_create("agent", Role.qa, "qa", id_="qa"),
    }
    return board, ps


def _quick(board, owner, **kw):
    return board.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.feature, title="Fix the tab title",
                               words="the Seats tab title says Sessions; call it Seats", tags=["quick"], **kw)


# ----------------------------------------------------------------------------- c-b92ae4a8dd creators

def test_owner_creates_a_parentless_quick_story_that_starts_ready(b):
    board, ps = b
    t = _quick(board, ps["owner"])
    assert t.kind == TicketKind.story and t.parent_id is None and "quick" in t.tags
    assert t.status == TicketStatus.ready  # the words are the design: no design_ref, no sign-off walk
    assert t.epic_id == t.id and board.epic_owner(t.id) == "owner"
    view = board.ticket_view(t.id)
    assert view["words"] == "the Seats tab title says Sessions; call it Seats"


def test_owner_parentless_story_without_the_tag_is_tagged_quick(b):
    board, ps = b
    t = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.chore, title="T")
    assert "quick" in t.tags and t.status == TicketStatus.ready


def test_architect_still_creates_stories_under_an_epic_and_never_a_quick_one(b):
    board, ps = b
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    s = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    assert s.parent_id == epic.id and s.status == TicketStatus.drafted and "quick" not in s.tags
    with pytest.raises(BoardError, match="needs parent_id"):
        board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S2")
    with pytest.raises(BoardError, match="only the owner opens a quick task"):
        board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S3",
                            parent_id=epic.id, tags=["quick"])


def test_engineer_cannot_create_a_story(b):
    board, ps = b
    with pytest.raises(BoardError, match="engineer may not create a story"):
        _quick(board, ps["eng"])


def test_quick_story_skips_the_story_cap(b):
    board, ps = b
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    for i in range(STORY_CAP):
        board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title=f"S{i}",
                            parent_id=epic.id)
    with pytest.raises(BoardError, match="at most"):
        board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="over",
                            parent_id=epic.id)
    q = _quick(board, ps["owner"], parent_id=epic.id)  # the owner's own task is not epic scope
    assert q.parent_id == epic.id and q.status == TicketStatus.ready


def test_quick_story_marks_designed_without_a_design_ref(b):
    board, ps = b
    # the guard itself (reachable from drafted, e.g. a quick story walked back) waives design_ref
    t = _quick(board, ps["owner"])
    probe = t.model_copy(deep=True)
    probe.status = TicketStatus.drafted
    board.criterion_create(ps["eng"], ticket_id=t.id, text="c", check=Check.verdict)
    board._guard_transition(ps["arch"], probe, TicketStatus.designed)  # no "needs a design_ref"


def test_quick_tag_is_fixed_at_create(b):
    board, ps = b
    t = _quick(board, ps["owner"])
    with pytest.raises(BoardError, match="quick"):
        board.ticket_update(ps["owner"], t.id, tags=[])
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    s = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    with pytest.raises(BoardError, match="quick"):
        board.ticket_update(ps["arch"], s.id, tags=["quick"])
    board.ticket_update(ps["owner"], t.id, tags=["quick", "ui"])  # other tags stay editable


# ----------------------------------------------------------------------------- engineer criteria, owner verdict

def _worked(board, ps):
    """A quick task its engineer took, wrote two owner-checked criteria for, evidenced and handed off."""
    t = _quick(board, ps["owner"], assignee="eng")
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_progress)
    c1 = board.criterion_create(ps["eng"], ticket_id=t.id, text="tab reads Seats", check=Check.verdict)
    c2 = board.criterion_create(ps["eng"], ticket_id=t.id, text="test passes", check=Check.command,
                                checked_by="owner")
    rep = board.doc_create(ps["eng"], doc_type=DocType.report, title="R", body_md="done", scope=t.id)
    for c in (c1, c2):
        board.criterion_update(ps["eng"], c.id, evidence_ref=rep.id)
    return t, c1, c2


def test_engineer_writes_owner_checked_criteria_on_its_quick_task(b):
    board, ps = b
    t, c1, c2 = _worked(board, ps)
    assert c1.checked_by == "owner" and c2.checked_by == "owner"
    # a normal story still refuses an engineer's criterion
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    s = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    with pytest.raises(BoardError, match="tasks only"):
        board.criterion_create(ps["eng"], ticket_id=s.id, text="x", check=Check.verdict)


def test_needs_you_lists_a_quick_task_only_once_it_is_in_review(b):
    board, ps = b
    t, c1, c2 = _worked(board, ps)
    assert views.decisions_for(board, ps["owner"])["signoffs"] == []  # mid-work: not the owner's yet
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_review)
    rows = views.decisions_for(board, ps["owner"])["signoffs"]
    assert {r["criterion"]["id"] for r in rows} == {c1.id, c2.id}
    assert all(r["ticket"]["quick"] and r["ticket"]["id"] == t.id for r in rows)


def test_owner_passes_every_criterion_and_the_quick_task_is_done_without_qa(b):
    board, ps = b
    t, c1, c2 = _worked(board, ps)
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_review)
    views.record_verdict(board, ps["owner"], criterion_id=c1.id, verdict="pass", evidence_version=1)
    assert board.ticket(t.id).status == TicketStatus.in_review
    views.record_verdict(board, ps["owner"], criterion_id=c2.id, verdict="pass", evidence_version=1)
    assert board.ticket(t.id).status == TicketStatus.done
    with pytest.raises(BoardError):  # qa is not this criterion's checker
        board.criterion_update(ps["qa"], c1.id, verdict=Verdict.failed)


def test_owner_fail_returns_the_quick_task_to_in_progress_with_the_note(b):
    board, ps = b
    t, c1, _ = _worked(board, ps)
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_review)
    out = views.record_verdict(board, ps["owner"], criterion_id=c1.id, verdict="fail",
                               note="still says Sessions on the narrow layout", ticket_id=t.id, evidence_version=1)
    assert board.ticket(t.id).status == TicketStatus.in_progress
    msg = board.store.get("message", out["message"])
    assert msg.to == "eng" and "still says Sessions" in msg.text
    # the engineer fixes it and hands off again; the refused criterion is re-ruled
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_review)
    assert board.ticket(t.id).status == TicketStatus.in_review


# ----------------------------------------------------------------------------- POST /v1/quick-tasks

@pytest.fixture
def api(tmp_path, monkeypatch):
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"builder": {"model": "claude-opus-4-8", "effort": "medium"}}, "roles": {"engineer": "builder"},
        "role_models": {"engineer": ["claude-opus-5-5", "gpt-6-sol"], "qa": ["claude-fable-5-1", "gpt-6-astra"],
                        "adversary": ["gpt-6-astra"]}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    board = Board(Store(":memory:"))
    client = TestClient(create_app(board, admin_token="t"))
    for pid, role, typ in (("owner", "owner", "human"), ("arch", "architect", "agent")):
        r = client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=ADMIN)
        assert r.json()["ok"], r.text
    calls: list[dict] = []

    def fake_spawn(role, participant_id, **kw):
        calls.append({"role": role, "participant_id": participant_id, **kw})
        return {"ok": True, "value": {"session_id": f"sess-{len(calls)}"}, "hint": ""}

    monkeypatch.setattr(pool_adapter, "spawn", fake_spawn)
    monkeypatch.setattr(pool_adapter, "reachable", lambda timeout=2.0: True)
    return {"board": board, "client": client, "calls": calls}


def test_quick_task_endpoint_creates_assigns_and_spawns_in_one_call(api):
    client, calls = api["client"], api["calls"]
    r = client.post("/v1/quick-tasks", json={"title": "Rename tab", "words": "call it Seats", "model": "gpt-6-sol"},
                    headers=OWNER)
    assert r.status_code == 200 and r.json()["ok"], r.text
    v = r.json()["value"]
    tid = v["ticket"]["id"]
    assert v["seat"] == f"engineer.{tid}"
    assert v["ticket"]["assignee"] == f"engineer.{tid}" and v["ticket"]["status"] == "ready"
    assert "quick" in v["ticket"]["tags"] and v["ticket"]["parent_id"] is None
    assert calls[-1]["role"] == "engineer" and calls[-1]["participant_id"] == f"engineer.{tid}"
    assert calls[-1]["model"] == "codex/gpt-6-sol"  # a GPT id runs on the codex seat
    got = client.get(f"/v1/tickets/{tid}", headers=OWNER).json()["value"]
    assert got["words"] == "call it Seats"


def test_quick_task_endpoint_default_model_is_the_engineer_catalog_default(api):
    r = api["client"].post("/v1/quick-tasks", json={"title": "T", "words": "w"}, headers=OWNER)
    assert r.json()["ok"], r.text
    assert api["calls"][-1]["model"] == "claude-opus-5-5"


def test_quick_task_endpoint_is_owner_only_and_refuses_before_create_when_the_pool_is_down(api, monkeypatch):
    client, board = api["client"], api["board"]
    r = client.post("/v1/quick-tasks", json={"title": "T", "words": "w"}, headers={"X-Participant": "arch"})
    assert not r.json()["ok"] and "owner" in r.text
    monkeypatch.setattr(pool_adapter, "reachable", lambda timeout=2.0: False)
    r = client.post("/v1/quick-tasks", json={"title": "T", "words": "w"}, headers=OWNER)
    assert not r.json()["ok"] and "pool is down" in r.text
    assert board.tickets(kind=TicketKind.story) == []  # nothing orphaned


def test_quick_task_endpoint_keeps_the_ticket_when_the_pool_refuses_the_spawn(api, monkeypatch):
    monkeypatch.setattr(pool_adapter, "spawn", lambda *a, **k: {"ok": False, "error": {"code": "pool",
                                                                                       "message": "at capacity"}})
    r = api["client"].post("/v1/quick-tasks", json={"title": "T", "words": "w"}, headers=OWNER)
    body = r.json()
    assert body["ok"] and body["value"]["seat"] is None and "at capacity" in body["hint"]
    assert body["value"]["ticket"]["assignee"] is None
