"""The listening contract as a table (design §16.2 rule 6): role × event/message kind ×
addressee × subject topology × actor relation × mention × epic ownership, with explicit
negative rows (sibling story, other epic, other epic's owner/architect) and overlapping-reason
rows. This is the durable statement of "no blind spots" and qa's checklist for any
future change to delivery.delivery_plan — if a row here fails, delivery changed.

Events are built two ways: message_sent / status_recorded through the real board writes (so the
structured `status` field on the event is exercised, never text-parsed), the rest as synthetic
Events over real ticket ids (so subject topology resolves) — the predicate is what is under test.
"""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import broker_adapter, delivery
from edp8.board import Board
from edp8.schemas import (
    Check,
    Event,
    EventKind,
    MessageKind,
    Reason,
    Role,
    StatusValue,
    TicketKind,
    Verdict,
    WorkType,
)
from edp8.store import Store

WHY_CLAUSES = {"addressed to you", "on your ticket", "architect listener",
               "owner listener", "@mention"}


@pytest.fixture(autouse=True)
def _no_broker(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)


@pytest.fixture
def rig():
    """Two epics. e1 owned by human `owner`, with architect a1, story s1 (engineer e1e, qa e1q)
    and sibling story s1b (engineer e1s). e2 owned by human `owner2`, architect a2, story s2
    (engineer e2e). e3 owned by `owner`, story s3 with NO architect and NO qa (recovery bed)."""
    b = Board(Store(":memory:"))
    p = {}
    p["owner"] = b.participant_create("human", Role.owner, "owner", id_="owner")
    p["owner2"] = b.participant_create("human", Role.owner, "owner2", id_="owner2")

    def epic(owner, title):
        return b.ticket_create(p[owner], kind=TicketKind.epic, work_type=WorkType.feature, title=title)

    def seat(role, tid):
        pid = f"{role.value}.{tid}"
        return b.participant_create("agent", role, pid, id_=pid)

    e1 = epic("owner", "E1")
    a1 = seat(Role.architect, e1.id)
    b.ticket_update(p["owner"], e1.id, assignee=a1.id)
    s1 = b.ticket_create(a1, kind=TicketKind.story, work_type=WorkType.feature, title="S1", parent_id=e1.id)
    e1e = seat(Role.engineer, s1.id)
    b.ticket_update(p["owner"], s1.id, assignee=e1e.id)
    e1q = seat(Role.qa, s1.id)
    s1b = b.ticket_create(a1, kind=TicketKind.story, work_type=WorkType.feature, title="S1b", parent_id=e1.id)
    e1s = seat(Role.engineer, s1b.id)
    b.ticket_update(p["owner"], s1b.id, assignee=e1s.id)

    e2 = epic("owner2", "E2")
    a2 = seat(Role.architect, e2.id)
    b.ticket_update(p["owner2"], e2.id, assignee=a2.id)
    s2 = b.ticket_create(a2, kind=TicketKind.story, work_type=WorkType.feature, title="S2", parent_id=e2.id)
    e2e = seat(Role.engineer, s2.id)
    b.ticket_update(p["owner2"], s2.id, assignee=e2e.id)

    # e3 deliberately has NO architect SEAT (recovery bed). A base architect (id "architect",
    # not architect.<epic>) authors its story — it is inert for delivery (never matches a seat).
    arch0 = b.participant_create("agent", Role.architect, "architect", id_="architect")
    e3 = epic("owner", "E3")
    s3 = b.ticket_create(arch0, kind=TicketKind.story, work_type=WorkType.feature, title="S3", parent_id=e3.id)

    p.update(a1=a1, e1e=e1e, e1q=e1q, e1s=e1s, a2=a2, e2e=e2e)
    ids = dict(e1=e1.id, s1=s1.id, s1b=s1b.id, e2=e2.id, s2=s2.id, e3=e3.id, s3=s3.id)
    return {"b": b, "p": p, "ids": ids}


def synth(subject_id, ev_kind, **data):
    return Event(id="ev-synth", subject_id=subject_id, kind=ev_kind, data=data)


def recips(b, ev):
    return {pid: rs for pid, rs in delivery.delivery_plan(b, ev)}


def _why_ok(b, ev, p):
    w = b.why(ev, p)
    assert w in WHY_CLAUSES, f"why {w!r} not one of the five clauses"
    return w


# --------------------------------------------------------------------------- the required row
def test_engineer_question_to_qa_reaches_qa_and_architect_only(rig):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    b.message_send(P["e1e"], ticket_id=I["s1"], to="qa", kind=MessageKind.question, text="q?")
    ev = b.store.query("event", {"subject_id": I["s1"], "kind": EventKind.message_sent})[-1]
    r = recips(b, ev)
    assert set(r) == {P["e1q"].id, P["a1"].id}, r
    assert b.relevant(ev, P["e1q"]) and b.relevant(ev, P["a1"])
    for absent in ("e1s", "e2e", "a2", "owner", "owner2", "e1e"):
        assert not b.relevant(ev, P[absent]), f"{absent} should not hear a question to qa"
    assert _why_ok(b, ev, P["e1q"]) == "addressed to you"
    assert _why_ok(b, ev, P["a1"]) == "architect listener"


# --------------------------------------------------------------------------- rule 1: architect
@pytest.mark.parametrize("kind", [MessageKind.question, MessageKind.deviation,
                                  MessageKind.finding, MessageKind.steer])
@pytest.mark.parametrize("to_key", ["e1e", "owner"])  # addressed to someone else entirely
def test_architect_hears_crucial_message_however_addressed(rig, kind, to_key):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    to = P[to_key].id
    b.message_send(P["e1e"], ticket_id=I["s1"], to=to, kind=kind, text="x")
    ev = b.store.query("event", {"subject_id": I["s1"], "kind": EventKind.message_sent})[-1]
    assert b.relevant(ev, P["a1"]), f"architect must hear a {kind} to {to_key}"
    assert Reason.architect_listener in recips(b, ev)[P["a1"].id]
    assert not b.relevant(ev, P["a2"]), "other epic's architect must not hear"


@pytest.mark.parametrize("kind", [MessageKind.note, MessageKind.answer])
def test_architect_not_paged_for_notes_between_others(rig, kind):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    # addressed to the sibling engineer: no listener, and not on the architect's read path either
    b.message_send(P["e1e"], ticket_id=I["s1"], to=P["e1s"].id, kind=kind, text="x")
    ev = b.store.query("event", {"subject_id": I["s1"], "kind": EventKind.message_sent})[-1]
    assert not b.relevant(ev, P["a1"]), f"a {kind} between two other seats must not page the architect"


@pytest.mark.parametrize("status", [StatusValue.blocked, StatusValue.failed, StatusValue.deferred])
def test_architect_and_owner_hear_recorded_status(rig, status):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    # addressed to the architect (a non-null `to`) so the OWNER's page depends only on rule 2's
    # failed/blocked filter, not on the to=None status-note path every status would take
    b.record_status(P["e1e"], status=status, note="n", to=P["a1"].id, ticket_id=I["s1"])
    ev = b.store.query("event", {"subject_id": I["s1"], "kind": EventKind.message_sent})[-1]
    assert ev.data.get("status") == status.value, "status must ride the event data, not the text"
    assert b.relevant(ev, P["a1"]), f"architect must hear a {status} status"
    # owner is paged for failed/blocked whatever the addressee (rule 2), not for deferred
    if status in (StatusValue.failed, StatusValue.blocked):
        assert b.relevant(ev, P["owner"]) and _why_ok(b, ev, P["owner"]) == "owner listener"
    else:
        assert not b.relevant(ev, P["owner"]), "owner is not paged for a deferred status addressed elsewhere"
    assert not b.relevant(ev, P["owner2"]), "other epic's owner never hears"


@pytest.mark.parametrize("to,arch_hears", [("blocked", True), ("partial", True),
                                           ("dropped", True), ("in_review", False),
                                           ("ready", False)])
def test_architect_hears_bad_status_transitions(rig, to, arch_hears):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    ev = synth(I["s1"], EventKind.status_changed, **{"from": "in_progress", "to": to})
    # a status_changed is never a courtesy copy (v21): the architect hears every lifecycle move on
    # its subtree via ancestor delivery; the crucial ones (blocked/partial/dropped) ALSO add the
    # rule-1 listener reason.
    got = b.relevant(ev, P["a1"])
    assert got  # architect works the subtree — ancestor delivery of a transition always applies
    if arch_hears:
        assert Reason.architect_listener in recips(b, ev)[P["a1"].id]


# --------------------------------------------------------------------------- rule 2: owner
@pytest.mark.parametrize("to,hears", [("ready", True), ("in_review", True), ("done", True),
                                      ("blocked", True), ("partial", True), ("dropped", True),
                                      ("designed", False), ("signed_off", False)])
def test_owner_status_transitions(rig, to, hears):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    ev = synth(I["s1"], EventKind.status_changed, **{"from": "x", "to": to})
    assert b.relevant(ev, P["owner"]) is hears
    assert not b.relevant(ev, P["owner2"])  # scoped to the epic's owner


def test_owner_not_paged_for_ticket_created(rig):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    ev = synth(I["s1"], EventKind.ticket_created, kind="task", by="x")
    assert not b.relevant(ev, P["owner"]), "ticket_created is not an owner page (design §16.2 rule 2)"


def test_owner_hears_criterion_fail_by_other_not_self(rig):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    assert b.relevant(synth(I["s1"], EventKind.criterion_checked, by="qa.x",
                            verdict=Verdict.failed), P["owner"])
    assert not b.relevant(synth(I["s1"], EventKind.criterion_checked, by="owner",
                                verdict=Verdict.failed), P["owner"])


@pytest.mark.parametrize("kind", [EventKind.shell_dead, EventKind.shell_stalled])
def test_owner_and_architect_hear_dying_shells_scoped(rig, kind):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    ev = synth(I["s1"], kind, participant=P["e1e"].id)
    assert b.relevant(ev, P["owner"]) and b.relevant(ev, P["a1"])
    assert not b.relevant(ev, P["owner2"]) and not b.relevant(ev, P["a2"])


# --------------------------------------------------------------------------- overlap & negatives
def test_addressed_and_mention_is_one_delivery_two_reasons(rig):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    # a real send excludes `to` from its own mentions, so the co-occurrence is exercised at the
    # plan level: an event both addressed to e1e AND @mentioning e1e collapses to one delivery
    ev = synth(I["s1"], EventKind.message_sent, to=P["e1e"].id, kind=MessageKind.note,
               mentions=[P["e1e"].id], **{"from": "someone.else"})
    rs = recips(b, ev)[P["e1e"].id]
    assert Reason.addressed in rs and Reason.mention in rs, rs  # two reasons
    assert [pid for pid, _ in delivery.delivery_plan(b, ev)].count(P["e1e"].id) == 1  # one delivery


def test_sibling_engineer_and_cross_epic_are_silent(rig):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    # v21 (rule 1): a plain thread note reaches the seats working s1 directly, but NOT the epic's
    # architect (no ancestor courtesy — it can read the thread) and never the sibling story's engineer
    b.message_send(P["e1e"], ticket_id=I["s1"], to=None, kind=MessageKind.note, text="note")
    ev = b.store.query("event", {"subject_id": I["s1"], "kind": EventKind.message_sent})[-1]
    assert not b.relevant(ev, P["a1"]) and not b.relevant(ev, P["e1s"])
    # a crucial note (deviation) still reaches the architect via rule 1, so the negative above is
    # about the note KIND, not a broken listener
    b.message_send(P["e1e"], ticket_id=I["s1"], to=None, kind=MessageKind.deviation, text="dev")
    dev = b.store.query("event", {"subject_id": I["s1"], "kind": EventKind.message_sent})[-1]
    assert b.relevant(dev, P["a1"])
    # every event on the other epic is invisible to e1's owner and architect
    ev2 = synth(I["s2"], EventKind.status_changed, **{"from": "x", "to": "blocked"})
    assert not b.relevant(ev2, P["owner"]) and not b.relevant(ev2, P["a1"])


def test_recovery_when_no_seat_and_no_architect(rig):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    # e3/s3 has no architect and no qa seat: a question to qa falls back to the epic's human owner
    r = b.resolve(P["owner"], ticket_id=I["s3"], to="qa", kind=MessageKind.question)
    assert r["wakes"] == r["plan"]  # same list under both keys
    assert [w["recipient"] for w in r["wakes"]] == ["owner"]
    assert r["wakes"][0]["reason"] == Reason.recovery.value
    assert "recovery" in r["note"] or "owner" in r["note"]
    # and the feed agrees: the owner is woken for that (synthetic) message
    ev = synth(I["s3"], EventKind.message_sent, to="qa", kind=MessageKind.question, **{"from": "x"})
    assert b.relevant(ev, P["owner"])


def test_resolve_endpoint_over_http(rig):
    """POST /v1/messages/resolve is a preview: it returns {to, wakes, plan, note}, sends nothing,
    and its hint documents the contract. Covers a live-seat wake and the no-seat cases."""
    from fastapi.testclient import TestClient

    from edp8.service import create_app
    b, I = rig["b"], rig["ids"]
    client = TestClient(create_app(b, admin_token="t"))

    def resolve(tid, to, kind="question"):
        return client.post("/v1/messages/resolve", json={"ticket_id": tid, "to": to, "kind": kind},
                           headers={"X-Participant": "owner"}).json()

    before = len(b.store.query("message", {}, limit=100_000))
    r = resolve(I["s1"], "qa")  # a real (never-spawned) qa seat exists on s1
    assert r["ok"], r
    v = r["value"]
    assert v["to"] == f"qa.{I['s1']}" and v["wakes"] == v["plan"]
    recips = {w["recipient"] for w in v["wakes"]}
    assert recips == {f"qa.{I['s1']}", f"architect.{I['e1']}"}
    assert "sent" in r["hint"].lower() or "preview" in r["hint"].lower()
    assert len(b.store.query("message", {}, limit=100_000)) == before, "resolve must not send"

    # no seat exists yet on this epic AND it is a plain note → nobody is woken
    r2 = resolve(I["s3"], "sme", kind="note")["value"]
    assert r2["wakes"] == [] and "nobody is woken" in r2["note"]

    # a question to that same no-seat role, no architect seat on e3 → recovery to the human owner
    r3 = resolve(I["s3"], "sme", kind="question")["value"]
    assert [w["recipient"] for w in r3["wakes"]] == ["owner"]
    assert r3["wakes"][0]["reason"] == Reason.recovery.value


def test_resolve_matches_delivery_for_a_real_send(rig):
    b, P, I = rig["b"], rig["p"], rig["ids"]
    preview = b.resolve(P["e1e"], ticket_id=I["s1"], to="qa", kind=MessageKind.question)
    b.message_send(P["e1e"], ticket_id=I["s1"], to="qa", kind=MessageKind.question, text="q?")
    ev = b.store.query("event", {"subject_id": I["s1"], "kind": EventKind.message_sent})[-1]
    assert {w["recipient"] for w in preview["wakes"]} == set(recips(b, ev))  # preview == delivery


# --------------------------------------------------------------------------- v21: no courtesy wakes (S22)
@pytest.mark.parametrize("status", [StatusValue.reviewed, StatusValue.handed_off, StatusValue.done])
def test_architect_not_paged_for_clean_status(rig, status):
    """rule 1 (v21): a benign record_status (reviewed/handed_off/done) is not an architect page —
    only blocked/failed/deferred are."""
    b, P, I = rig["b"], rig["p"], rig["ids"]
    b.record_status(P["e1e"], status=status, note="n", to=None, ticket_id=I["s1"])
    ev = b.store.query("event", {"subject_id": I["s1"], "kind": EventKind.message_sent})[-1]
    assert not b.relevant(ev, P["a1"]), f"architect must not be paged for a clean {status} status"


def test_clean_shell_dead_pages_neither_owner_nor_architect(rig):
    """rule 1+2 (v21): a CLEAN self-close (clean=true) wakes nobody; an unclean death still pages
    both the epic's architect and its human owner."""
    b, P, I = rig["b"], rig["p"], rig["ids"]
    clean = synth(I["s1"], EventKind.shell_dead, participant=P["e1e"].id, clean=True)
    assert not b.relevant(clean, P["a1"]) and not b.relevant(clean, P["owner"])
    unclean = synth(I["s1"], EventKind.shell_dead, participant=P["e1e"].id)
    assert b.relevant(unclean, P["a1"]) and b.relevant(unclean, P["owner"])


def test_architect_not_paged_for_passing_criterion_check(rig):
    """rule 1 (v21): only a FAIL verdict pages the architect; a pass is not a wake."""
    b, P, I = rig["b"], rig["p"], rig["ids"]
    passing = synth(I["s1"], EventKind.criterion_checked, by="qa.x", verdict=Verdict.passed)
    assert not b.relevant(passing, P["a1"])
    failing = synth(I["s1"], EventKind.criterion_checked, by="qa.x", verdict=Verdict.failed)
    assert b.relevant(failing, P["a1"])


@pytest.mark.parametrize("to", ["drafted", "designed", "signed_off", "in_progress"])
def test_architect_not_paged_for_design_time_transitions(rig, to):
    """rule 1 is EXHAUSTIVE (§24.1(c)): a status_changed INTO a design-time phase
    (drafted/designed/signed_off/in_progress) is a courtesy copy — the architect can read it but is
    not paged. Only the phase boundaries (ready/in_review/blocked/done/partial/dropped) still page."""
    b, P, I = rig["b"], rig["p"], rig["ids"]
    ev = synth(I["s1"], EventKind.status_changed, **{"from": "x", "to": to})
    assert not b.relevant(ev, P["a1"]), f"architect must not be paged for a transition to {to}"


@pytest.mark.parametrize("ev_kind,data", [
    (EventKind.ticket_created, {"kind": "task", "by": "someone.else"}),
    (EventKind.assigned, {"assignee": "someone.else", "by": "someone.else"}),
    (EventKind.doc_updated, {"version": 2, "by": "someone.else"}),
])
def test_architect_not_paged_for_routine_subtree_events(rig, ev_kind, data):
    """rule 1 is EXHAUSTIVE (§24.1(c)): ticket_created, assigned and doc_updated on a subtree ticket
    are courtesy copies — they no longer wake the epic's architect through ancestor delivery. (These
    are frequent: recording evidence emits doc_updated.)"""
    b, P, I = rig["b"], rig["p"], rig["ids"]
    ev = synth(I["s1"], ev_kind, **data)
    assert not b.relevant(ev, P["a1"]), f"architect must not be paged for a subtree {ev_kind}"


def test_architect_still_paged_for_epic_ticket_events_directly(rig):
    """The exhaustive rule drops only ANCESTOR courtesy copies: an event on the epic ticket the
    architect works DIRECTLY (on_ticket) is never dropped — a routine transition on E1 still reaches
    architect.E1."""
    b, P, I = rig["b"], rig["p"], rig["ids"]
    ev = synth(I["e1"], EventKind.status_changed, **{"from": "x", "to": "in_progress"})
    assert b.relevant(ev, P["a1"]), "architect works the epic directly; its own ticket's events reach it"


def test_owner_not_paged_for_agent_passing_command_check(rig):
    """rule 2 (v21): an agent qa passing a `command` criterion is not a human page; a `look`
    check, an owner-checked one, or a fail still wakes the owner."""
    b, P, I = rig["b"], rig["p"], rig["ids"]
    agent_pass = synth(I["s1"], EventKind.criterion_checked, by="qa.s1", verdict=Verdict.passed,
                       check=Check.command, checked_by="qa", by_type="agent", by_role="qa")
    assert not b.relevant(agent_pass, P["owner"])
    look_pass = synth(I["s1"], EventKind.criterion_checked, by="qa.s1", verdict=Verdict.passed,
                      check=Check.look, checked_by="qa", by_type="agent", by_role="qa")
    owner_checked = synth(I["s1"], EventKind.criterion_checked, by="qa.s1", verdict=Verdict.passed,
                          check=Check.command, checked_by="owner", by_type="agent", by_role="qa")
    a_fail = synth(I["s1"], EventKind.criterion_checked, by="qa.s1", verdict=Verdict.failed,
                   check=Check.command, checked_by="qa", by_type="agent", by_role="qa")
    assert b.relevant(look_pass, P["owner"]) and b.relevant(owner_checked, P["owner"]) and b.relevant(a_fail, P["owner"])
    # §24 finding 9: only an AGENT qa passing check is suppressed. A HUMAN qa's
    # passing command check (by_type=human) always pages the owner.
    human_pass = synth(I["s1"], EventKind.criterion_checked, by="human-qa", verdict=Verdict.passed,
                       check=Check.command, checked_by="qa", by_type="human", by_role="qa")
    assert b.relevant(human_pass, P["owner"]), "a human's passing check must page the owner"
    # §24 finding 9 (second-opinion): an AGENT seat whose ROLE is owner verdicting a qa
    # criterion is NOT an agent qa — its passing check must still page (suppression keys on
    # the acting role, not just by_type + checked_by).
    agent_owner_pass = synth(I["s1"], EventKind.criterion_checked, by="owner-agent", verdict=Verdict.passed,
                             check=Check.command, checked_by="qa", by_type="agent", by_role="owner")
    assert b.relevant(agent_owner_pass, P["owner"]), "an agent-owner's passing check must page the owner"
