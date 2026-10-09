"""Guard C1: qa is never spawned by the board; the architect starts it once every story is handed over (dec-40efecb36c).
Split out of the retired asks-ledger test file (s-aa76c83998). Board-level, in-memory, no real pool."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.schemas import (
    Check,
    DocType,
    Role,
    TicketKind,
    TicketStatus,
    WorkType,
)
from edp8.service import create_app
from edp8.store import Store


class StubPool:
    def __init__(self):
        self.spawns: list[tuple[str, str]] = []

    def spawn(self, role, participant_id, **kw):
        self.spawns.append((role, participant_id))
        return {"ok": True, "participant_id": participant_id}


@pytest.fixture
def b():
    return Board(Store(":memory:"), pool=StubPool(), free_mb=lambda: 4096)


@pytest.fixture
def r(b):
    out = {"owner": b.participant_create("human", Role.owner, "owner", id_="owner"),
           "engineer": b.participant_create("agent", Role.engineer, "engineer.story", id_="engineer.story")}
    out["epic"] = b.ticket_create(out["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    eid = out["epic"].id
    out["architect"] = b.participant_create("agent", Role.architect, f"architect.{eid}", id_=f"architect.{eid}")
    out["qa"] = b.participant_create("agent", Role.qa, f"qa.{eid}", id_=f"qa.{eid}")
    return out



def story(b, r, title="S", *, review=False):
    s = b.ticket_create(r["architect"], kind=TicketKind.story,
                        work_type=WorkType.review if review else WorkType.feature, title=title, parent_id=r["epic"].id)
    c = b.criterion_create(r["architect"], ticket_id=s.id, text=f"{title} works", check=Check.command)
    return s, c


def hand_over(b, r, s, c):
    d = b.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=r["epic"].id)
    b.ticket_update(r["architect"], s.id, design_ref=d.id)
    b.ticket_update(r["architect"], s.id, status=TicketStatus.designed)
    b.ticket_update(r["owner"], s.id, status=TicketStatus.signed_off)
    b.ticket_update(r["architect"], s.id, status=TicketStatus.ready)
    b.ticket_update(r["architect"], s.id, assignee=r["engineer"].id)
    b.ticket_update(r["engineer"], s.id, status=TicketStatus.in_progress)
    ev = b.doc_create(r["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=r["epic"].id)
    b.criterion_update(r["engineer"], c.id, evidence_ref=ev.id)
    b.ticket_update(r["engineer"], s.id, status=TicketStatus.in_review)


def qa_seats(b):
    return [t for t in b._pending_pairings]


# ------------------------------------------------------------------ C1
def test_C1_qa_does_not_spawn_while_a_review_story_is_still_open(b, r):
    s1, c1 = story(b, r, "feature")
    rv, _ = story(b, r, "review", review=True)  # a review story counts: it is a story
    hand_over(b, r, s1, c1)
    assert b.qa_ready(r["epic"]) is False
    assert "review" in (b.qa_wait(r["epic"]) or "") or b.qa_wait(r["epic"])
    assert b.run_pending_pairings()["spawned"] == [] and b._pool.spawns == []
    assert b.qa_spawn_refusal("qa", r["epic"].id) is not None


def test_C1_qa_is_never_spawned_by_the_board_when_the_last_story_is_in_review(b, r):
    pool = b._pool
    s1, c1 = story(b, r, "one")
    s2, c2 = story(b, r, "two")
    hand_over(b, r, s1, c1)
    assert b.run_pending_pairings()["spawned"] == []
    hand_over(b, r, s2, c2)
    seat = f"qa.{r['epic'].id}"
    assert b.run_pending_pairings()["spawned"] == []  # B: the architect starts qa on the hint, not the board
    assert pool.spawns.count(("qa", seat)) == 0
    assert b.qa_ready(r["epic"]) is True and b.qa_spawn_refusal("qa", r["epic"].id) is None


def test_C1_a_dropped_story_does_not_hold_qa_and_an_empty_epic_is_not_ready(b, r):
    assert b.qa_ready(r["epic"]) is False  # no story at all
    s1, c1 = story(b, r, "one")
    s2, _ = story(b, r, "two")
    hand_over(b, r, s1, c1)
    assert b.qa_ready(r["epic"]) is False
    b.ticket_update(r["architect"], s2.id, status=TicketStatus.dropped)
    assert b.qa_ready(r["epic"]) is True


def test_C1_the_rest_spawn_and_seat_token_advise_qa_before_ready(b, r):
    """design-63db8a7d42 I: one qa per epic, once every story is in review, is advice: the seat-token and the spawn
    go ahead and the reply names what is not ready."""
    s1, c1 = story(b, r, "one")
    story(b, r, "two")
    hand_over(b, r, s1, c1)
    app = TestClient(create_app(b, admin_token="t"))
    h = {"X-Participant": r["architect"].id}
    seat = f"qa.{r['epic'].id}"
    out = app.post("/v1/sessions/spawn", headers=h, json={"role": "qa", "participant_id": seat,
                                                          "ticket_id": r["epic"].id}).json()
    assert out.get("error", {}).get("code") != "scope", out  # not refused by the board (the pool may be down here)
    tok = app.post("/v1/sessions/seat-token", headers=h, json={"participant_id": seat,
                                                               "ticket_id": r["epic"].id}).json()
    assert tok["ok"] is True and any("story" in a for a in tok["value"]["advised"]), tok
    b.participant_create("agent", Role.qa, f"qa.{s1.id}", id_=f"qa.{s1.id}")
    on_story = app.post("/v1/sessions/seat-token", headers=h, json={"participant_id": f"qa.{s1.id}",
                                                                    "ticket_id": s1.id}).json()
    assert on_story["ok"] is True and any("one seat per epic" in a for a in on_story["value"]["advised"]), on_story