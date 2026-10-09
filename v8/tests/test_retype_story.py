"""Owner m-b9f93cddf0: the sme is for research. A story typed `knowledge` sends its criteria to the epic's sme, so
product docs typed that way could not be checked by qa. The architect or the owner now retypes an epic or a
story (ticket_update work_type=...) and its pending criteria follow the new checker."""
from __future__ import annotations

import pytest

from edp8.board import Board, BoardError
from edp8.schemas import Check, EventKind, Role, TicketKind, TicketStatus, Verdict, WorkType
from edp8.store import Store


@pytest.fixture
def b():
    return Board(Store(":memory:"))


@pytest.fixture
def r(b):
    out = {k: b.participant_create("human" if k == "owner" else "agent", role, k)
           for k, role in (("owner", Role.owner), ("architect", Role.architect), ("engineer", Role.engineer),
                           ("qa", Role.qa), ("sme", Role.sme))}
    out["epic"] = b.ticket_create(out["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    return out


def _docs_story(b, r, n=2):
    s = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.knowledge, title="Guide pages",
                        parent_id=r["epic"].id)
    crits = [b.criterion_create(r["architect"], ticket_id=s.id, text=f"page {i}", check=Check.look) for i in range(n)]
    assert {c.checked_by for c in crits} == {"sme"}
    return s, crits


def test_retyping_a_knowledge_story_moves_its_pending_criteria_to_qa(b, r):
    s, crits = _docs_story(b, r)
    t = b.ticket_update(r["architect"], s.id, work_type=WorkType.feature)
    assert t.work_type == WorkType.feature and b.ticket(s.id).work_type == WorkType.feature
    assert {c.checked_by for c in b.criteria(s.id)} == {"qa"}
    moved = b.store.query("event", {"subject_id": s.id, "kind": EventKind.criterion_checker_overridden})
    assert sorted(e.data["criterion"] for e in moved) == sorted(c.id for c in crits)
    assert all(e.data["from"] == "sme" and e.data["to"] == "qa" and e.data["by"] == r["architect"].id
               for e in moved)
    assert b.checker_for(b.ticket(s.id)) == "qa"  # new criteria follow the new type too


def test_a_verdicted_line_and_an_owner_set_checker_stay(b, r):
    s, crits = _docs_story(b, r)
    owners = b.criterion_create(r["owner"], ticket_id=s.id, text="owner signs", check=Check.verdict,
                                checked_by="owner", override_reason="I sign this one")
    done = crits[0]
    done.verdict = Verdict.passed
    b.store.put("criterion", done)
    b.ticket_update(r["owner"], s.id, work_type=WorkType.chore)
    by_id = {c.id: c.checked_by for c in b.criteria(s.id)}
    assert by_id == {done.id: "sme", crits[1].id: "qa", owners.id: "owner"}


@pytest.mark.parametrize("who", ["engineer", "qa", "sme"])
def test_only_the_architect_or_owner_retypes(b, r, who):
    s, _ = _docs_story(b, r)
    with pytest.raises(BoardError, match="may not retype"):
        b.ticket_update(r[who], s.id, work_type=WorkType.feature)
    assert {c.checked_by for c in b.criteria(s.id)} == {"sme"}


def test_review_tasks_and_closed_stories_keep_their_type(b, r):
    s, _ = _docs_story(b, r)
    with pytest.raises(BoardError, match="review"):
        b.ticket_update(r["architect"], s.id, work_type=WorkType.review)
    b.store.put("ticket", b.ticket(s.id).model_copy(update={"status": TicketStatus.done}))
    with pytest.raises(BoardError, match="done"):
        b.ticket_update(r["architect"], s.id, work_type=WorkType.feature)


def test_the_same_type_is_a_no_op(b, r):
    s, _ = _docs_story(b, r)
    before = len(b.store.query("event", {"subject_id": s.id}))
    b.ticket_update(r["architect"], s.id, work_type=WorkType.knowledge)
    assert len(b.store.query("event", {"subject_id": s.id})) == before
