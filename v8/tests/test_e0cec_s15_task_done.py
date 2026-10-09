"""e0cec S15 task 5 (p-c3c5d460, supersedes p-e40a9db0): an engineer-passed task must reach `done`.

Private board, no pool: nothing here touches the fleet."""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

from asks_support import serve_rest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.schemas import TicketStatus
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


def _rig():
    board = Board(Store(":memory:"), free_mb=lambda: 4096)
    client = TestClient(create_app(board, admin_token="t"))
    epic = None
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"), ("ravi", "qa", "human")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                       headers={"X-Participant": "owner"}).json()["value"]["id"]
    story = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "s", "parent_id": epic},
                        headers={"X-Participant": "arch"}).json()["value"]["id"]
    seats = {"architect": f"architect.{epic}", "engineer": f"engineer.{story}"}
    for role, seat in seats.items():
        assert client.post("/v1/participants", json={"type": "agent", "role": role, "handle": seat, "id": seat},
                           headers=ADMIN).json()["ok"]
    return board, client, epic, story, seats


def _set(board, tid, **kw):
    t = board.store.get("ticket", tid)
    for k, v in kw.items():
        setattr(t, k, v)
    board.store.put("ticket", t)


def _task(client, board, story, seats, *, pass_before_review: bool):
    eng = seats["engineer"]
    epic = board.epic_of(board.ticket(story)).id
    task = client.post("/v1/tickets", json={"kind": "task", "work_type": "feature", "title": "t", "parent_id": story,
                                            "serves": serve_rest(client, epic, {"X-Participant": "owner"})},
                       headers={"X-Participant": eng}).json()
    assert task["ok"], task
    tid = task["value"]["id"]
    _set(board, tid, status=TicketStatus.in_progress, assignee=eng)
    c = client.post("/v1/criteria", json={"ticket_id": tid, "text": "it works", "check": "command"},
                    headers={"X-Participant": eng}).json()
    assert c.get("ok"), c
    cid = c["value"]["id"]
    assert c["value"]["checked_by"] == "engineer"
    d = client.post("/v1/docs", json={"doc_type": "report", "title": "ev", "body_md": "ran it", "scope": tid},
                    headers={"X-Participant": eng}).json()
    assert d["ok"], d
    assert client.patch(f"/v1/criteria/{cid}", json={"evidence_ref": d["value"]["id"]},
                        headers={"X-Participant": eng}).json()["ok"]
    if pass_before_review:
        r = client.patch(f"/v1/criteria/{cid}", json={"verdict": "pass"}, headers={"X-Participant": eng}).json()
        assert r["ok"], r
    return tid, cid


def _status(client, tid, to, as_):
    return client.patch(f"/v1/tickets/{tid}", json={"status": to}, headers={"X-Participant": as_}).json()


def test_task_passed_before_hand_off_goes_done_at_hand_off():
    board, client, epic, story, seats = _rig()
    tid, _ = _task(client, board, story, seats, pass_before_review=True)
    r = _status(client, tid, "in_review", seats["engineer"])
    assert r["ok"], r
    assert board.ticket(tid).status == TicketStatus.done


def test_task_passed_after_hand_off_goes_done_on_the_verdict():
    board, client, epic, story, seats = _rig()
    tid, cid = _task(client, board, story, seats, pass_before_review=False)
    assert _status(client, tid, "in_review", seats["engineer"])["ok"]
    assert board.ticket(tid).status == TicketStatus.in_review
    assert client.patch(f"/v1/criteria/{cid}", json={"verdict": "pass"},
                        headers={"X-Participant": seats["engineer"]}).json()["ok"]
    assert board.ticket(tid).status == TicketStatus.done


def test_a_task_stranded_in_review_with_every_line_passed_completes_on_the_next_note():
    board, client, epic, story, seats = _rig()
    tid, _ = _task(client, board, story, seats, pass_before_review=True)
    _set(board, tid, status=TicketStatus.in_review)  # stranded in_review by an older board
    assert board.ticket(tid).status == TicketStatus.in_review
    r = client.post("/v1/messages", json={"ticket_id": tid, "kind": "note", "text": "still open?"},
                    headers={"X-Participant": seats["architect"]}).json()
    assert r["ok"], r
    assert board.ticket(tid).status == TicketStatus.done


def test_a_task_with_a_pending_line_stays_in_review_on_hand_off():
    board, client, epic, story, seats = _rig()
    tid, _ = _task(client, board, story, seats, pass_before_review=False)
    assert _status(client, tid, "in_review", seats["engineer"])["ok"]
    assert board.ticket(tid).status == TicketStatus.in_review
