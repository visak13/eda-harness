"""s-aa76c83998: Mark as requirement replaces the asks ledger (design-63db8a7d42 item H).
Criteria: c-9eee2a8212 (no automatic ask, tools/view gone, rows archived), c-bfd5174fb8 (open requirement blocks done,
linking closes it, architect woken once), plus the REST door for owner and guest. Board-level, in-memory."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edp8 import requirements
from edp8.board import Board, BoardError
from edp8.context_delta import ContextReader
from edp8.schemas import (
    Ask,
    AskState,
    Check,
    DocType,
    EventKind,
    Gate,
    MessageKind,
    RequirementState,
    Role,
    TicketKind,
    TicketStatus,
    WorkType,
)
from edp8.service import create_app
from edp8.store import Store


@pytest.fixture
def b():
    return Board(Store(":memory:"), free_mb=lambda: 4096)


@pytest.fixture
def r(b):
    out = {"owner": b.participant_create("human", Role.owner, "owner", id_="owner"),
           "engineer": b.participant_create("agent", Role.engineer, "engineer.story", id_="engineer.story")}
    out["epic"] = b.ticket_create(out["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    eid = out["epic"].id
    out["architect"] = b.participant_create("agent", Role.architect, f"architect.{eid}", id_=f"architect.{eid}")
    return out


def say(b, r, text="make the button blue, and add a footer", ticket=None):
    return b.message_send(r["owner"], ticket_id=ticket or r["epic"].id, to=None, kind=MessageKind.note, text=text)


def events(b, kind):
    return b.store.query("event", {"kind": kind}, limit=1000)


# ------------------------------------------------------------------ c-9eee2a8212: nothing is an ask any more
def test_a_human_message_creates_no_ask_no_ask_event_and_no_hold(b, r):
    s = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                        parent_id=r["epic"].id)
    say(b, r)
    say(b, r, "on a story", ticket=s.id)
    assert b.store.query("ask", {}, limit=100) == []
    assert [e for k in (EventKind.ask_created, EventKind.ask_triaged, EventKind.ask_judged) for e in events(b, k)] == []
    assert b.store.query("requirement", {}, limit=100) == []  # a message is not a requirement either
    b.gate_open(r["epic"].id, Gate.acceptance, by=r["architect"].id)  # no ledger hold
    assert not [x for x in b.inbox(r["architect"]) if x["kind"] == "ask"]


def test_the_ask_tools_and_routes_are_gone_and_the_requirement_tools_exist(b, r):
    from edp8 import bundles
    names = set(bundles.ALL_TOOLS)
    assert {"asks", "ask_triage", "ask_verdict"}.isdisjoint(names)
    assert {"requirements", "requirement_link"} <= names
    assert "requirement_link" in bundles.ROLE_BUNDLES[Role.architect.value]
    assert "requirement_link" not in bundles.ROLE_BUNDLES[Role.qa.value]
    app = TestClient(create_app(b, admin_token="t"))
    h = {"X-Participant": r["owner"].id}
    assert app.get(f"/v1/epics/{r['epic'].id}/asks", headers=h).status_code == 404
    assert app.post("/v1/asks/ask-1/triage", headers=h, json={}).status_code in (404, 405)


def test_archive_asks_retires_old_rows_once_and_never_deletes_or_converts(b, r):
    s = say(b, r)
    for st in (AskState.untriaged, AskState.covered, AskState.not_met):
        b.store.put("ask", Ask(id=f"ask-{st.value}", epic_id=r["epic"].id, ticket_id=r["epic"].id, source=s.id,
                               created_by="owner", state=st))
    from edp8 import requirements as req
    assert req.archive_asks(b) == {"archived": 3, "already": 0}
    assert {a.state for a in b.store.query("ask", {}, limit=10)} == {AskState.archived}
    assert len(events(b, EventKind.ask_archived)) == 3
    assert req.archive_asks(b) == {"archived": 0, "already": 3}  # idempotent
    assert len(events(b, EventKind.ask_archived)) == 3
    assert b.store.query("requirement", {}, limit=10) == []  # history is not converted into open requirements


# ------------------------------------------------------------------ marking
def test_mark_records_the_span_sends_no_message_and_is_idempotent(b, r):
    m = say(b, r, "make the button blue, and add a footer")
    before = len(b.store.query("message", {}, limit=100))
    x = b.requirement_mark(r["owner"], message_id=m.id, char_start=0, char_end=20)
    assert x.text == "make the button blue" and (x.char_start, x.char_end) == (0, 20)
    assert x.source == m.id and x.epic_id == r["epic"].id and x.state == RequirementState.open
    assert len(b.store.query("message", {}, limit=100)) == before  # no chat message
    assert b.requirement_mark(r["owner"], message_id=m.id, char_start=0, char_end=20).id == x.id
    y = b.requirement_mark(r["owner"], message_id=m.id)  # no range: the whole message
    assert y.id != x.id and y.text == m.text
    assert [q.id for q in b.requirements(r["epic"].id)] == [x.id, y.id]


def test_mark_refuses_bad_ranges_agents_and_threads_off_an_epic(b, r):
    m = say(b, r, "abc")
    for cs, ce in ((2, 2), (0, 99), (-1, 2)):
        with pytest.raises(BoardError):
            b.requirement_mark(r["owner"], message_id=m.id, char_start=cs, char_end=ce)
    with pytest.raises(BoardError) as e:
        b.requirement_mark(r["architect"], message_id=m.id)
    assert e.value.code == "scope"
    with pytest.raises(BoardError):
        b.requirement_mark(r["owner"], message_id="m-missing")


# ------------------------------------------------------------------ c-bfd5174fb8: open blocks done, link closes it
def test_the_architect_is_woken_once_per_new_requirement(b, r):
    m = say(b, r)
    cr = ContextReader(b)
    base = cr.baseline(r["architect"], None)
    x = b.requirement_mark(r["owner"], message_id=m.id, char_start=0, char_end=4)
    out = cr.delta(r["architect"], base)
    row = next(c for c in out["changes"] if c.get("object_id") == x.id or c.get("object_type") == "requirement")
    assert row["object_type"] == "requirement" and row["state"] == "open"
    assert row["read_ref"] == {"tool": "requirements", "epic": r["epic"].id}
    again = b.requirement_mark(r["owner"], message_id=m.id, char_start=0, char_end=4)  # same span: no second event
    assert again.id == x.id and len(events(b, EventKind.requirement_marked)) == 1
    assert not cr.delta(r["architect"], out["next_cursor"])["changed"]


def _epic_in_review(b, r):
    """An epic whose only criterion passed and that sits in_review, so only a requirement can hold it."""
    s = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                        parent_id=r["epic"].id)
    c = b.criterion_create(r["architect"], ticket_id=s.id, text="works", check=Check.command)
    return s, c


def test_an_epic_cannot_finish_or_open_acceptance_while_a_requirement_is_open(b, r):
    s, c = _epic_in_review(b, r)
    x = b.requirement_mark(r["owner"], message_id=say(b, r).id, char_start=0, char_end=4)
    with pytest.raises(BoardError) as e:
        b.gate_open(r["epic"].id, Gate.acceptance, by=r["architect"].id)
    assert x.id in e.value.message and "requirement" in e.value.message
    probe = b.legal_transitions(r["owner"], r["epic"].id)["transitions"]
    assert all(not t["allowed"] for t in probe if t["to"] in ("done", "partial"))
    assert "requirement" in " ".join(str(t["reason"]) for t in probe if t["to"] in ("done", "partial") and t["reason"]) \
        or not any(t["to"] in ("done", "partial") for t in probe)  # the edge is not even legal yet from this phase
    # forced to the terminal edge (in_review) the guard itself speaks
    epic = b.ticket(r["epic"].id)
    epic.status = TicketStatus.in_review
    b.store.put("ticket", epic)
    for to in (TicketStatus.done, TicketStatus.partial):
        with pytest.raises(BoardError) as e2:
            b._guard_transition(r["owner"], b.ticket(r["epic"].id), to)
        assert x.id in e2.value.message
    b.requirement_link(r["architect"], x.id, criterion=c.id)
    b.gate_open(r["epic"].id, Gate.acceptance, by=r["architect"].id)  # closed: nothing holds the gate


def test_link_to_a_criterion_or_a_design_section_closes_it_and_checks_the_target(b, r):
    s, c = _epic_in_review(b, r)
    d = b.doc_create(r["architect"], doc_type=DocType.design, title="d", scope=r["epic"].id,
                     body_md="# Design\n\n## Buttons\nThe button is blue.\n\n## Footer\nA footer.\n")
    m = say(b, r)
    x = b.requirement_mark(r["owner"], message_id=m.id, char_start=0, char_end=20)
    z = b.requirement_mark(r["owner"], message_id=m.id, char_start=22, char_end=36)
    with pytest.raises(BoardError):  # neither / both
        b.requirement_link(r["architect"], x.id)
    with pytest.raises(BoardError):
        b.requirement_link(r["architect"], x.id, criterion=c.id, doc=d.id, version=1, heading="Buttons")
    with pytest.raises(BoardError):  # a section the version does not have
        b.requirement_link(r["architect"], x.id, doc=d.id, version=1, heading="Nowhere")
    with pytest.raises(BoardError):  # a version it does not have
        b.requirement_link(r["architect"], x.id, doc=d.id, version=9, heading="Buttons")
    with pytest.raises(BoardError):  # a criterion outside the epic
        b.requirement_link(r["architect"], x.id, criterion="c-missing")
    with pytest.raises(BoardError) as e:  # an engineer cannot close it
        b.requirement_link(r["engineer"], x.id, criterion=c.id)
    assert e.value.code == "scope"
    ok = b.requirement_link(r["architect"], x.id, doc=d.id, version=1, heading="Buttons")
    assert ok.state == RequirementState.linked and (ok.doc_id, ok.doc_version, ok.heading) == (d.id, 1, "Buttons")
    ok2 = b.requirement_link(r["architect"], z.id, criterion=c.id)
    assert ok2.state == RequirementState.linked and ok2.criterion == c.id
    assert [q.id for q in b.requirements(r["epic"].id, state="open")] == []
    assert len(events(b, EventKind.requirement_linked)) == 2


def test_E6_a_task_names_the_requirement_or_finding_it_serves(b, r):
    from edp8 import advice
    s, _ = _epic_in_review(b, r)
    advice.take()
    bare = b.ticket_create(r["architect"], kind=TicketKind.task, work_type=WorkType.feature, title="T", parent_id=s.id)
    assert bare.serves == []  # design-63db8a7d42 I: advice, not a refusal
    assert any("serves" in said for said in advice.take())
    x = b.requirement_mark(r["owner"], message_id=say(b, r).id)
    t = b.ticket_create(r["architect"], kind=TicketKind.task, work_type=WorkType.feature, title="T", parent_id=s.id,
                        serves=[x.id])
    assert t.serves == [x.id]
    with pytest.raises(BoardError):  # an id that is neither: a wrong reference stays a refusal
        b.ticket_create(r["architect"], kind=TicketKind.task, work_type=WorkType.feature, title="T2",
                        parent_id=s.id, serves=["m-nonexistent"])
    f = b.message_send(r["architect"], ticket_id=s.id, to=None, kind=MessageKind.finding, text="a finding")
    assert b.ticket_create(r["architect"], kind=TicketKind.task, work_type=WorkType.feature, title="T3",
                           parent_id=s.id, serves=[f.id]).serves == [f.id]


def test_story_digest_and_E4_survive_the_ledger(b, r):
    from edp8 import epic_work
    s, c = _epic_in_review(b, r)
    d = epic_work.story_digest(b, b.ticket(s.id))
    assert d["story"] == s.id and d["open_criteria"] == [c.id] and d["last"]["event"].startswith("ev")
    assert "open_asks" not in d
    dec = b.record_decision(r["architect"], scope=r["epic"].id, text="Never delete the owner's drafts silently",
                            binding=True)
    app = TestClient(create_app(b, admin_token="t"))
    h = {"X-Participant": r["architect"].id}
    out = app.post("/v1/criteria", headers=h, json={"ticket_id": s.id, "check": "command",
                                                    "text": "deleting the owner's drafts silently is allowed"}).json()
    assert dec.id in [x["id"] for x in out["value"].get("binding_decisions", [])]


# ------------------------------------------------------------------ the REST door
def test_rest_mark_list_link_for_the_owner_and_the_architect(b, r):
    app = TestClient(create_app(b, admin_token="t"))
    oh, ah = {"X-Participant": r["owner"].id}, {"X-Participant": r["architect"].id}
    s, c = _epic_in_review(b, r)
    m = app.post("/v1/messages", headers=oh, json={"ticket_id": r["epic"].id, "kind": "note",
                                                   "text": "ship the footer"}).json()["value"]
    n = len(b.store.query("message", {}, limit=100))
    x = app.post("/v1/requirements", headers=oh, json={"message_id": m["id"], "char_start": 0, "char_end": 4}).json()
    assert x["ok"] and x["value"]["text"] == "ship" and len(b.store.query("message", {}, limit=100)) == n
    lst = app.get(f"/v1/epics/{r['epic'].id}/requirements", headers=ah).json()["value"]
    assert [q["id"] for q in lst["requirements"]] == [x["value"]["id"]] and "open requirement" in lst["blocked_reason"]
    assert app.post(f"/v1/requirements/{x['value']['id']}/link", headers=oh, json={"criterion": c.id}).status_code == 200
    done = app.get(f"/v1/epics/{r['epic'].id}/requirements", headers=ah).json()["value"]
    assert done["requirements"][0]["state"] == "linked" and "blocked_reason" not in done
    bad = app.post("/v1/requirements", headers=oh, json={"message_id": m["id"], "char_start": 9, "char_end": 3}).json()
    assert bad["ok"] is False


# ------------------------------------------------------------------ s-aa76 adversary fixes (report-879bc8060e)
def test_f4_a_new_requirement_reopens_a_done_epic_and_hints_the_architect(b, r):
    """No workflow declares an edge out of done: the board makes the move itself (as it does in_review -> in_progress)."""
    m = say(b, r)
    epic = b.ticket(r["epic"].id)
    epic.status = TicketStatus.done
    b.store.put("ticket", epic)
    req = b.requirement_mark(r["owner"], message_id=m.id)
    assert b.ticket(epic.id).status == TicketStatus.in_progress
    assert requirements.open_ids(b, epic.id) == [req.id]
    moved = [e for e in events(b, EventKind.status_changed) if e.data.get("to") == "in_progress" and e.data.get("by") == "board"]
    assert moved and moved[-1].data["from"] == "done" and req.id in moved[-1].data["trigger"]
    hints = [e for e in events(b, EventKind.board_hint) if e.data.get("hint") == "requirement_reopened"]
    assert len(hints) == 1 and hints[0].data["requirement"] == req.id


def test_f4_a_dropped_epic_stays_dropped(b, r):
    m = say(b, r)
    epic = b.ticket(r["epic"].id)
    epic.status = TicketStatus.dropped
    b.store.put("ticket", epic)
    b.requirement_mark(r["owner"], message_id=m.id)
    assert b.ticket(epic.id).status == TicketStatus.dropped


def test_q1_a_requirement_links_only_to_a_design_section(b, r):
    req = b.requirement_mark(r["owner"], message_id=say(b, r).id)
    doc = b.doc_create(r["engineer"], doc_type=DocType.report, title="Unrelated report", scope=r["epic"].id,
                       body_md="# Report\n\n## Unrelated\nNo design commitment.\n")
    with pytest.raises(BoardError, match="not a design") as e:
        b.requirement_link(r["architect"], req.id, doc=doc.id, version=1, heading="Unrelated")
    assert "doc_edit" in str(e.value.hint)
    assert b.store.get("requirement", req.id).state == RequirementState.open


def test_archive_preserves_every_non_state_field_and_the_original_state_event(b, r):
    m = say(b, r)
    originals = []
    for i, state in enumerate(AskState):
        a = Ask(id=f"ask-{i:010x}", epic_id=r["epic"].id, ticket_id=r["epic"].id, source=m.id,
                created_by="owner", state=state, covers=["c-original"], amends="ask-before",
                superseded_by="ask-after", story="s-original", triage_note="triage", triaged_by="architect",
                qa_verdict="not_met", qa_note="qa note", judged_by="qa")
        b.store.put("ask", a)
        originals.append(a.model_dump(mode="json"))
    n = len(originals)
    assert requirements.archive_asks(b) == {"archived": n - 1, "already": 1}
    for original in originals:
        got = b.store.get("ask", original["id"]).model_dump(mode="json")
        assert {k: v for k, v in got.items() if k != "state"} == {k: v for k, v in original.items() if k != "state"}
        if original["state"] != "archived":
            evs = b.store.query("event", {"subject_id": original["id"], "kind": EventKind.ask_archived}, limit=10)
            assert len(evs) == 1 and evs[0].data["from"] == original["state"]
    assert requirements.archive_asks(b) == {"archived": 0, "already": n}
