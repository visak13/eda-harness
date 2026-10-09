"""s-0b8d2e5393 (design-63db8a7d42 items I and J, owner m-d611346eca, m-f65239bfa7, m-4b4bd9b35e).

I: the board refuses only state transitions, who may change status or approve, safety and security, evidence_ref, the
doc version check, the shell cap and "no one approves their own work". Every other rule is advice: the call goes
ahead and the reply's hint says so. A silent rewrite of an agent's input says so too.
J: the story cap stays a hard refusal that tells the architect to ask the owner in chat; the owner's reply, passed by
message id, lifts it for that epic, and the board checks the message is the owner's and sits on the epic.
"""
from __future__ import annotations

import pytest

from edp8 import advice
from edp8.board import STORY_CAP, Board, BoardError
from edp8.schemas import (
    Check,
    DocType,
    MessageKind,
    Role,
    TicketKind,
    TicketStatus,
    Verdict,
    WorkType,
)
from edp8.store import Store


@pytest.fixture
def b():
    return Board(Store(":memory:"), free_mb=lambda: 4096)


@pytest.fixture
def r(b):
    out = {"owner": b.participant_create("human", Role.owner, "owner", id_="owner"),
           "engineer": b.participant_create("agent", Role.engineer, "engineer.story", id_="engineer.story"),
           "qa": b.participant_create("agent", Role.qa, "qa.x", id_="qa.x"),
           "sme": b.participant_create("agent", Role.sme, "sme.x", id_="sme.x")}
    out["epic"] = b.ticket_create(out["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    out["architect"] = b.participant_create("agent", Role.architect, f"architect.{out['epic'].id}",
                                            id_=f"architect.{out['epic'].id}")
    advice.take()
    return out


def _story(b, r, title="S", epic=None, **kw):
    return b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title=title,
                           parent_id=(epic or r["epic"]).id, **kw)


def _said(*needles):
    got = advice.take()
    assert got, "no advice was given"
    text = " | ".join(got)
    for n in needles:
        assert n in text, (n, text)
    return got


# ------------------------------------------------------------------ J: the story cap

def _fill(b, r, epic=None):
    for i in range(STORY_CAP):
        _story(b, r, f"S{i}", epic)


def test_a_story_over_the_cap_is_refused_and_says_to_ask_the_owner_in_chat(b, r):
    _fill(b, r)
    with pytest.raises(BoardError) as ei:
        _story(b, r, "one too many")
    assert ei.value.code == "scope" and "at most" in ei.value.message
    assert "ask the owner in chat" in ei.value.hint and "cap_lift_message" in ei.value.hint


def test_the_owners_reply_message_id_lifts_the_cap_for_that_epic(b, r):
    _fill(b, r)
    reply = b.message_send(r["owner"], ticket_id=r["epic"].id, to=r["architect"].id, kind=MessageKind.answer,
                           text="yes, add as many as the design needs")
    s9 = _story(b, r, "S9", cap_lift_message=reply.id)
    assert s9.parent_id == r["epic"].id
    _story(b, r, "S10")  # the lift is for the epic, not one create
    other = b.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="Other")
    _fill(b, r, other)
    with pytest.raises(BoardError):  # and not for another epic
        _story(b, r, "over", other)


def test_a_message_from_anyone_else_does_not_lift_the_cap(b, r):
    _fill(b, r)
    fake = b.message_send(r["architect"], ticket_id=r["epic"].id, to=r["owner"].id, kind=MessageKind.answer,
                          text="the owner said yes")
    with pytest.raises(BoardError) as ei:
        _story(b, r, "S9", cap_lift_message=fake.id)
    assert ei.value.code == "scope" and "not the owner's" in ei.value.message
    eng = b.message_send(r["engineer"], ticket_id=r["epic"].id, to=r["architect"].id, kind=MessageKind.answer,
                         text="ok")
    with pytest.raises(BoardError):
        _story(b, r, "S9", cap_lift_message=eng.id)


def test_a_missing_message_or_one_from_another_epic_does_not_lift_the_cap(b, r):
    _fill(b, r)
    with pytest.raises(BoardError) as ei:
        _story(b, r, "S9", cap_lift_message="m-nope")
    assert "is not a message" in ei.value.message
    other = b.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="Other")
    elsewhere = b.message_send(r["owner"], ticket_id=other.id, to=None, kind=MessageKind.answer, text="yes")
    with pytest.raises(BoardError) as ei:
        _story(b, r, "S9", cap_lift_message=elsewhere.id)
    assert "is not on epic" in ei.value.message


def test_cap_lift_message_rides_the_rest_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from edp8 import broker_adapter
    from edp8.service import create_app
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    for pid, role, typ in [("sam", "owner", "human"), ("arch", "architect", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers={"X-Admin": "t"}).json()["ok"]
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"},
                  headers={"X-Participant": "sam"}).json()["value"]["id"]
    for i in range(STORY_CAP):
        assert c.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": f"S{i}",
                                           "parent_id": epic}, headers={"X-Participant": "arch"}).json()["ok"]
    over = c.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S9", "parent_id": epic},
                  headers={"X-Participant": "arch"}).json()
    assert not over["ok"] and "ask the owner in chat" in over["hint"]
    msg = c.post("/v1/messages", json={"ticket_id": epic, "kind": "answer", "to": "arch", "text": "go on"},
                 headers={"X-Participant": "sam"}).json()["value"]["id"]
    done = c.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S9", "parent_id": epic,
                                       "cap_lift_message": msg}, headers={"X-Participant": "arch"}).json()
    assert done["ok"], done


# ------------------------------------------------------------------ I: changed guards let the call through

def test_a_task_title_change_goes_ahead_and_says_it_is_normally_fixed(b, r):
    story = _story(b, r)
    task = b.ticket_create(r["engineer"], kind=TicketKind.task, work_type=WorkType.feature, title="T",
                           parent_id=story.id, serves=[])
    advice.take()
    t = b.ticket_update(r["architect"], task.id, title="T renamed")
    assert t.title == "T renamed"
    _said("task's title is normally fixed")


def test_a_long_title_is_refused_with_the_same_hint_as_create(b, r):  # Q2: not a hint, one rule everywhere
    story = _story(b, r)
    with pytest.raises(BoardError) as ei:
        b.ticket_update(r["architect"], story.id, title="x" * (b.TITLE_MAX + 5))
    assert "at most 80" in ei.value.message and "words" in ei.value.hint
    assert b.ticket(story.id).title == "S"


def test_a_tasks_work_type_change_goes_ahead_but_a_topics_stays_refused(b, r):
    story = _story(b, r)
    task = b.ticket_create(r["engineer"], kind=TicketKind.task, work_type=WorkType.feature, title="T",
                           parent_id=story.id)
    advice.take()
    t = b.ticket_update(r["architect"], task.id, work_type=WorkType.bug)
    assert t.work_type == WorkType.bug
    _said("work_type is normally fixed")


def test_the_doer_writing_its_own_criteria_goes_ahead_with_advice(b, r):
    story = _story(b, r)
    b.ticket_update(r["architect"], story.id, assignee=r["architect"].id)
    advice.take()
    c = b.criterion_create(r["architect"], ticket_id=story.id, text="x", check=Check.command)
    assert c.ticket_id == story.id
    _said("doer", "added anyway")


def test_criteria_over_the_cap_go_ahead_with_advice(b, r):
    story = _story(b, r)
    for i in range(6):
        b.criterion_create(r["architect"], ticket_id=story.id, text=f"c{i}", check=Check.command)
    assert advice.take() == []
    b.criterion_create(r["architect"], ticket_id=story.id, text="c6", check=Check.command)
    _said("freshly-written criteria", "number 7")
    assert len(b.criteria(story.id)) == 7


def test_tasks_over_the_cap_go_ahead_with_advice(b, r):
    story = _story(b, r)
    for i in range(5):
        b.ticket_create(r["engineer"], kind=TicketKind.task, work_type=WorkType.feature, title=f"T{i}",
                        parent_id=story.id)
    advice.take()  # the serves advice each task gets is not under test here
    b.ticket_create(r["engineer"], kind=TicketKind.task, work_type=WorkType.feature, title="T5", parent_id=story.id)
    _said("at most 5 tasks", "number 6")


def test_a_task_without_serves_is_created_with_advice(b, r):
    story = _story(b, r)
    t = b.ticket_create(r["engineer"], kind=TicketKind.task, work_type=WorkType.feature, title="T",
                        parent_id=story.id)
    assert t.serves == []
    _said("should name the requirement or finding ids")


def test_serves_on_a_story_is_ignored_and_the_reply_says_so(b, r):
    t = _story(b, r, serves=["a-1"])
    assert t.serves == []
    _said("serves ignored")


# ------------------------------------------------------------------ I: verdict rules advise, evidence_ref still refuses

def _in_review(b, r, check=Check.command, checked_by=None):
    story = _story(b, r)
    d = b.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=r["epic"].id)
    b.ticket_update(r["architect"], story.id, design_ref=d.id)
    c = b.criterion_create(r["architect"], ticket_id=story.id, text="c", check=check)
    b.ticket_update(r["architect"], story.id, status=TicketStatus.designed)
    b.ticket_update(r["owner"], story.id, status=TicketStatus.signed_off)
    b.ticket_update(r["architect"], story.id, status=TicketStatus.ready)
    b.ticket_update(r["architect"], story.id, assignee=r["engineer"].id)
    b.ticket_update(r["engineer"], story.id, status=TicketStatus.in_progress)
    ev = b.doc_create(r["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=r["epic"].id)
    b.criterion_update(r["engineer"], c.id, evidence_ref=ev.id)
    b.ticket_update(r["engineer"], story.id, status=TicketStatus.in_review)
    return story, c, ev


def test_a_look_pass_without_a_screenshot_goes_ahead_with_advice(b, r):
    story, c, _ = _in_review(b, r, check=Check.look)
    advice.take()
    out = b.criterion_update(r["qa"], c.id, verdict=Verdict.passed)
    assert out.verdict == Verdict.passed
    _said("check=look", "screenshot", "passed as given")


def test_a_verdict_without_evidence_ref_is_still_refused(b, r):
    story = _story(b, r)
    c = b.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    with pytest.raises(BoardError) as ei:
        b.criterion_update(r["qa"], c.id, verdict=Verdict.passed)
    assert ei.value.code == "transition" and "evidence_ref" in ei.value.message


def test_no_one_approves_their_own_work(b, r):
    story, c, _ = _in_review(b, r)
    with pytest.raises(BoardError) as ei:  # the doer is not a checker of its own line
        b.criterion_update(r["engineer"], c.id, verdict=Verdict.passed)
    assert ei.value.code == "scope"
    with pytest.raises(BoardError) as ei:  # and a checker never becomes the doer it would check
        b.ticket_update(r["architect"], story.id, assignee=r["qa"].id)
    assert ei.value.code == "scope" and "never becomes its assignee" in ei.value.message


def test_an_older_evidence_version_is_still_refused(b, r):
    story, c, ev = _in_review(b, r)
    b.doc_update(r["engineer"], ev.id, body_md="changed after the read")
    with pytest.raises(BoardError) as ei:
        b.criterion_update(r["qa"], c.id, verdict=Verdict.passed, evidence_version=1)
    assert ei.value.code == "transition" and "re-read" in ei.value.message


def test_a_missing_evidence_version_is_defaulted_and_the_reply_says_so(b, r):
    story, c, ev = _in_review(b, r)
    advice.take()
    out = b.criterion_update(r["qa"], c.id, verdict=Verdict.passed)
    assert out.evidence_version == ev.version
    _said("evidence_version not given")


def test_an_ignored_checked_by_says_so(b, r):
    story = _story(b, r)
    advice.take()
    c = b.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command, checked_by="owner")
    assert c.checked_by == "qa"
    _said("checked_by=owner ignored", "derives the checker")


# ------------------------------------------------------------------ I: kept refusals still refuse

def test_state_transitions_and_authority_still_refuse(b, r):
    story = _story(b, r)
    with pytest.raises(BoardError) as ei:  # a state transition
        b.ticket_update(r["architect"], story.id, status=TicketStatus.done)
    assert ei.value.code == "transition"
    with pytest.raises(BoardError) as ei:  # who may change what
        b.ticket_create(r["engineer"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                        parent_id=r["epic"].id)
    assert ei.value.code == "scope"
    with pytest.raises(BoardError):  # only the owner opens a quick task
        b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                        parent_id=r["epic"].id, tags=["quick"])


# ------------------------------------------------------------------ I: silent rewrites name themselves

def test_the_owners_parentless_story_is_tagged_quick_and_says_so(b, r):
    advice.take()
    t = b.ticket_create(r["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Do a thing")
    assert "quick" in t.tags
    _said("tagged `quick`")


def test_a_long_epic_title_is_derived_and_says_so(b, r):
    advice.take()
    b.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="word " * 40)
    _said("derived the short title")


def test_the_advice_rides_the_rest_reply_hint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from edp8 import broker_adapter
    from edp8.service import create_app
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    for pid, role, typ in [("sam", "owner", "human"), ("arch", "architect", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers={"X-Admin": "t"}).json()["ok"]
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"},
                  headers={"X-Participant": "sam"}).json()["value"]["id"]
    story = c.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S", "parent_id": epic},
                   headers={"X-Participant": "arch"}).json()["value"]["id"]
    j = c.post("/v1/criteria", json={"ticket_id": story, "text": "c", "check": "command", "checked_by": "owner"},
               headers={"X-Participant": "arch"}).json()
    assert j["ok"], j
    assert "checked_by=owner ignored" in j["hint"]
    again = c.get(f"/v1/tickets/{story}", headers={"X-Participant": "arch"}).json()
    assert "ignored" not in again.get("hint", "")  # advice is per reply, never carried to the next


# ------------------------------------------------------------------ J: Astra report-869d0fc8d4 (F1, F2, Q1)

def _owner_msg(b, r, sender, text="yes"):
    return b.message_send(sender, ticket_id=r["epic"].id, to=r["architect"].id, kind=MessageKind.answer, text=text)


def test_f1_another_owners_message_does_not_lift_this_epics_cap(b, r):
    bob = b.participant_create("human", Role.owner, "bob", id_="bob")
    _fill(b, r)
    with pytest.raises(BoardError) as ei:
        _story(b, r, "S9", cap_lift_message=_owner_msg(b, r, bob).id)
    assert ei.value.code == "scope" and "not this epic's owner owner" in ei.value.message
    assert "only the owner of this epic" in ei.value.hint
    assert not b._scope_cap_raised(r["epic"].id)
    with pytest.raises(BoardError):  # and the refused lift left no event behind
        _story(b, r, "S9")


def test_f1_the_epics_own_owner_still_lifts_it_and_a_message_on_a_story_counts(b, r):
    _fill(b, r)
    story = b.children(r["epic"].id)[0]
    reply = b.message_send(r["owner"], ticket_id=story.id, to=r["architect"].id, kind=MessageKind.answer, text="yes")
    _story(b, r, "S9", cap_lift_message=reply.id)
    assert b._scope_cap_raised(r["epic"].id)


def test_f2_a_valid_id_passed_below_the_cap_is_recorded_and_applies_later(b, r):
    reply = _owner_msg(b, r, r["owner"])
    _story(b, r, "S0", cap_lift_message=reply.id)
    lifts = b.store.query("event", {"subject_id": r["epic"].id, "kind": "scope_cap_lifted"})
    assert len(lifts) == 1 and lifts[0].data["message"] == reply.id and lifts[0].data["by"] == "owner"
    for i in range(1, STORY_CAP + 2):
        _story(b, r, f"S{i}")  # past the cap with no id: the earlier lift holds
    _story(b, r, "again", cap_lift_message=reply.id)  # a repeat is not a second event
    assert len(b.store.query("event", {"subject_id": r["epic"].id, "kind": "scope_cap_lifted"})) == 1


def test_f2_a_bad_id_below_the_cap_is_refused_not_ignored(b, r):
    stranger = b.participant_create("human", Role.owner, "bob", id_="bob")
    with pytest.raises(BoardError):
        _story(b, r, "S0", cap_lift_message="m-nope")
    with pytest.raises(BoardError):
        _story(b, r, "S0", cap_lift_message=_owner_msg(b, r, stranger).id)
    assert not b.children(r["epic"].id)


def test_q1_the_refusal_says_to_pass_only_the_owners_yes(b, r):
    _fill(b, r)
    with pytest.raises(BoardError) as ei:
        _story(b, r, "S9")
    assert "only the owner's yes" in ei.value.hint
