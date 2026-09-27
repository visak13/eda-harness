"""S20 attention trail (design-e963c656f5 §4.18, c-7b63a47c90): ONE read, attention.items, lists every item waiting on a
person with its full location path; the inbox, notifications, the summary/Decisions reads and the Epics list all
read it, and no second rule exists."""
from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import attention, broker_adapter, notifications, topics, views
from edp8.board import Board
from edp8.schemas import OBJECT_TYPES, Check, DocType, FixProposal, Gate, MessageKind, Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store, new_id

SRC = Path(__file__).resolve().parents[1] / "src" / "edp8"


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **kw: True)
    monkeypatch.setenv("EDP8_OWNER", "owner")
    b = Board(Store())
    owner = b.participant_create("human", Role.owner, "owner")
    other = b.participant_create("human", Role.owner, "other")
    arch = b.participant_create("agent", Role.architect, "arch")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Galaxy site")
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="Ship sheet",
                            parent_id=epic.id)
    return b, owner, other, arch, epic, story


def ready_for_signoff(b, arch, epic):
    """An epic the design_signoff gate accepts: a design_ref and an acceptance criterion."""
    d = b.doc_create(arch, doc_type=DocType.design, title="design", body_md="# d", scope=epic.id)
    b.ticket_update(arch, epic.id, design_ref=d.id)
    b.criterion_create(arch, ticket_id=epic.id, text="the site ships", check=Check.command)


def only(rows, **match):
    hits = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, (match, rows)
    return hits[0]


# ------------------------------------------------------------------ each kind × each location

@pytest.mark.parametrize("kind", [MessageKind.question, MessageKind.steer, MessageKind.deviation])  # v34: + blocked status
def test_every_ask_kind_to_a_human_is_an_item_with_its_path(rig, kind):
    b, owner, _, arch, epic, story = rig
    on_epic = b.message_send(arch, ticket_id=epic.id, kind=kind, text="x", to=owner.id)
    on_story = b.message_send(arch, ticket_id=story.id, kind=kind, text="y", to=owner.id)
    rows = attention.items(b, owner)
    root = only(rows, id=on_epic.id)
    assert root["kind"] == "ask" and root["item"] == {"type": "message", "id": on_epic.id}
    assert root["scope"] == {"type": "epic", "id": epic.id, "title": "Galaxy site"}
    assert (root["tab"], root["section"], root["ticket"]) == ("thread", "asks", None)
    assert root["url"] == f"/ui/epic/{epic.id}#{on_epic.id}" and root["noun"] == kind.value
    child = only(rows, id=on_story.id)  # Work → the ticket row → the message on the ticket page
    assert (child["tab"], child["section"]) == ("work", "tickets")
    assert child["ticket"] == {"id": story.id, "title": "Ship sheet"}
    assert child["at"] == {"tab": "thread", "section": "asks"}
    assert child["url"] == f"/ui/ticket/{story.id}#{on_story.id}"


def test_a_note_or_an_agent_addressed_status_is_not_an_item(rig):
    b, owner, _, arch, epic, _ = rig
    b.message_send(arch, ticket_id=epic.id, kind=MessageKind.note, text="fyi", to=owner.id)
    b.message_send(owner, ticket_id=epic.id, kind=MessageKind.status, text="to a seat", to=arch.id)
    assert attention.items(b, owner) == []


@pytest.mark.parametrize("gate,where", [(Gate.scope, ("actions", "decisions")),
                                        (Gate.demo, ("actions", "decisions")),
                                        (Gate.design_signoff, ("design", "signoff"))])
def test_owner_gates_land_on_their_opener(rig, gate, where):
    b, owner, other, arch, epic, story = rig
    ready_for_signoff(b, arch, epic)
    ev = b.gate_open(epic.id, gate)
    row = only(attention.items(b, owner), id=ev.id)
    assert row["kind"] == "gate" and row["item"]["gate"] == gate.value
    assert (row["tab"], row["section"]) == where and row["ticket"] is None
    assert row["url"] == f"/ui/epic/{epic.id}?request={ev.id}"
    assert attention.items(b, other) == []  # not their epic: owner scoping is the gate rule's


def test_a_gate_on_a_child_ticket_goes_through_work_then_the_ticket(rig):
    b, owner, _, _, epic, story = rig
    ev = b.gate_open(story.id, Gate.scope)
    row = only(attention.items(b, owner), id=ev.id)
    assert (row["tab"], row["section"], row["ticket"]["id"]) == ("work", "tickets", story.id)
    assert row["at"] == {"tab": "actions", "section": "decisions"}


@pytest.mark.parametrize("doc_type,where", [(DocType.design, ("design", "signoff")),
                                            (DocType.report, ("files", "evidence"))])
def test_signoffs_land_on_design_or_files(rig, doc_type, where):
    b, owner, _, arch, epic, _ = rig  # noqa
    eng = b.participant_create("agent", Role.engineer, "eng")
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="Sheet",
                            parent_id=epic.id, assignee=eng.id)
    c = b.criterion_create(owner, ticket_id=story.id, text="owner signs", check=Check.look, checked_by="owner",
                           override_reason="the owner rules this one")
    doc = b.doc_create(eng if doc_type == DocType.report else arch, doc_type=doc_type, title="evidence",
                       body_md="# e", scope=story.id)
    b.criterion_update(eng, c.id, evidence_ref=doc.id)
    row = only(attention.items(b, owner), id=c.id)
    assert row["kind"] == "signoff" and row["item"] == {"type": "criterion", "id": c.id, "doc": doc.id}
    assert (row["tab"], row["section"], row["ticket"]["id"]) == ("work", "tickets", story.id)
    assert (row["at"]["tab"], row["at"]["section"]) == where  # on the ticket page: its Design / Files opener
    query = f"?doc={doc.id}" if doc_type == DocType.design else ""  # evidence opens the ticket's ruling drawer
    assert row["url"] == f"/ui/ticket/{story.id}{query}#{c.id}"
    # t-77c3a55b75 (owner m-0e6940fe2c): the item says what the owner decides, the words the ruling drawer heads with
    assert row["ask"] == "Accept “Sheet” as meeting this criterion?" == views.signoff_ask(story)


def test_a_gate_item_asks_its_question_even_when_stored_blank(rig):
    """t-77c3a55b75: a gate item carries its note as `ask`; a legacy gate stored blank asks 0df23fa's generated question."""
    from edp8.schemas import EventKind
    b, owner, _, _, epic, story = rig
    ev = b.gate_open(story.id, Gate.scope, note="Split Ship sheet in two?")
    assert only(attention.items(b, owner), id=ev.id)["ask"] == "Split Ship sheet in two?"
    legacy = b._emit(story.id, EventKind.gate_opened, {"gate": Gate.demo, "by": "arch", "note": ""})
    ask = only(attention.items(b, owner), id=legacy.id)["ask"]
    assert ask == b.gate_question(story.id, Gate.demo) and "Ship sheet" in ask


def _help_topic(b, owner):
    from edp8 import help as help_
    return b.ticket(help_.ask(b, owner, "Board is slow")["topic"]["id"])


def test_a_topic_ask_and_a_fix_proposal_live_on_the_topic(rig):
    b, owner, other, arch, _, _ = rig
    t = _help_topic(b, owner)
    ask = b.message_send(arch, ticket_id=t.id, kind=MessageKind.question, text="which port?", to=owner.id)
    fix = FixProposal(id=new_id("fix"), created_by="doctor", topic_id=t.id,
                      action={"kind": "service.restart", "service": "board"}, effect="restart the board",
                      request={"method": "POST", "path": "/v1/admin/services/board/restart", "body": {}})
    b.store.put("fix", fix)
    rows = attention.items(b, owner)
    a, f = only(rows, id=ask.id), only(rows, id=fix.id)
    assert a["scope"]["type"] == f["scope"]["type"] == "help" and a["scope"]["id"] == t.id
    assert (a["tab"], a["section"]) == ("thread", "asks") and a["url"] == f"/ui/library/topics/{t.id}#{ask.id}"
    assert f["kind"] == "fix" and (f["tab"], f["section"]) == ("fixes", "fixes")
    assert f["url"] == f"/ui/library/topics/{t.id}#{fix.id}"
    assert all(r["kind"] != "fix" for r in attention.items(b, other))  # not an admin
    b.store.put("fix", fix.model_copy(update={"status": "rejected"}))
    assert all(r["kind"] != "fix" for r in attention.items(b, owner))


@pytest.mark.skipif("access_request" not in OBJECT_TYPES, reason="t-882e4d2eeb not landed")
def test_a_pending_access_request_reaches_admins_only(rig):
    from edp8.schemas import AccessRequest
    b, owner, other, *_ = rig
    req = AccessRequest(id=new_id("ar"), created_by="anonymous", name="Sam", role_wanted="owner")
    b.store.put("access_request", req)
    row = only(attention.items(b, owner), id=req.id)
    assert row["scope"]["type"] == "admin" and (row["tab"], row["section"]) == ("teammates", "requests")
    assert row["url"] == f"/ui/admin?tab=teammates#{req.id}" and "Sam" in row["label"]
    assert attention.items(b, other) == []
    b.store.put("access_request", req.model_copy(update={"status": "denied"}))
    assert attention.items(b, owner) == []


# ------------------------------------------------------------------ clearing + rollup

def test_an_item_clears_only_when_answered(rig):
    b, owner, _, arch, epic, _ = rig
    q = b.message_send(arch, ticket_id=epic.id, kind=MessageKind.question, text="?", to=owner.id)
    ev = b.gate_open(epic.id, Gate.scope)
    b.thread(epic.id)  # reading the thread (opening the item) is not answering it
    assert {r["id"] for r in attention.items(b, owner)} == {q.id, ev.id}
    b.message_send(owner, ticket_id=epic.id, kind=MessageKind.answer, text="yes", to=arch.id, reply_to=q.id)
    b.gate_answer(owner, epic.id, Gate.scope, "approved")
    assert attention.items(b, owner) == []


def test_rollup_counts_every_hop_and_writes_the_reason(rig):
    b, owner, _, arch, epic, story = rig
    t = _help_topic(b, owner)
    b.message_send(arch, ticket_id=story.id, kind=MessageKind.question, text="1", to=owner.id)
    b.message_send(arch, ticket_id=story.id, kind=MessageKind.question, text="2", to=owner.id)
    ready_for_signoff(b, arch, epic)
    b.gate_open(epic.id, Gate.design_signoff)
    b.message_send(arch, ticket_id=t.id, kind=MessageKind.question, text="3", to=owner.id)
    lib = topics.create(b, owner, title="Rendering")["topic"]
    b.message_send(arch, ticket_id=lib.id, kind=MessageKind.question, text="4", to=owner.id)
    roll = attention.rollup(attention.items(b, owner))
    assert roll["counts"] == {"total": 5, "epics": 3, "topics": 1, "help": 1, "admin": 0}
    e = only(roll["scopes"], id=epic.id)
    assert e["count"] == 3 and e["reason"] == "2 questions, 1 design sign-off"
    assert e["tabs"] == {"work": 2, "design": 1}
    assert e["sections"] == {"work/tickets": 2, "design/signoff": 1} and e["tickets"] == {story.id: 2}
    row = only(views.epics_summary(b, owner), id=epic.id)
    assert row["attention"]["count"] == 3 and row["attention"]["reason"] == e["reason"]


def test_epics_that_need_you_sort_first(rig):
    b, owner, _, arch, epic, _ = rig
    quiet = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Quiet")
    b.message_send(arch, ticket_id=epic.id, kind=MessageKind.question, text="?", to=owner.id)
    rows = views.epics_summary(b, owner)
    assert rows[0]["id"] == epic.id and rows[0]["attention"]["reason"] == "1 question"
    assert only(rows, id=quiet.id)["attention"] is None


def test_endpoint_returns_items_rollup_and_no_private_source(rig, tmp_path, monkeypatch):
    b, owner, _, arch, epic, _ = rig
    monkeypatch.delenv("EDP8_TOKENS", raising=False)
    b.message_send(arch, ticket_id=epic.id, kind=MessageKind.question, text="SECRET BODY", to=owner.id)
    v = TestClient(create_app(b)).get("/v1/me/attention", headers={"X-Participant": owner.id}).json()["value"]
    assert v["counts"]["total"] == 1 and v["scopes"][0]["reason"] == "1 question"
    assert "_src" not in v["items"][0] and "SECRET BODY" not in str(v)


# ------------------------------------------------------------------ one rule: every surface reads attention.items

def test_every_surface_moves_with_attention_items(rig, monkeypatch):
    b, owner, _, arch, epic, _ = rig
    cursor = notifications.attention(b, owner)["cursor"]
    q = b.message_send(arch, ticket_id=epic.id, kind=MessageKind.question, text="?", to=owner.id)
    assert views.summary_for(b, owner)["counts"]["waiting_on_you"] == 1
    assert len(views.decisions_for(b, owner)["questions"]) == 1
    assert len(notifications.attention(b, owner, since=cursor)["requests"]) == 1
    assert views.epics_summary(b, owner)[0]["attention"]["count"] == 1
    monkeypatch.setattr(attention, "items", lambda board, viewer: [])  # the one derivation says: nothing
    assert views.summary_for(b, owner)["counts"]["waiting_on_you"] == 0
    assert views.summary_for(b, owner)["attention"]["total"] == 0
    assert views.decisions_for(b, owner) == {"signoffs": [], "questions": [], "gates": [],
                                             "counts": {"signoffs": 0, "questions": 0, "gates": 0}}
    assert notifications.attention(b, owner, since=cursor)["requests"] == []
    assert views.epics_summary(b, owner)[0]["attention"] is None
    assert not views.conversations_for(b, owner) or not any(r["unread"] for r in views.conversations_for(b, owner))
    assert q.id  # the message itself is untouched: only the derivation decides


# The primitive rules attention.items composes; outside their own definitions only attention.py may call them among
# the modules that serve people's attention surfaces. Agents' own inbox (board.inbox via /v1/inbox, context,
# context_delta, close_check) is the ask rule itself, the one attention reads.
_RULES = {"inbox", "_owner_gates", "pending_signoffs"}
_SURFACES = ("views.py", "notifications.py", "api_views.py", "api_doctor.py", "ui.py")


def _calls(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name in _RULES and name != fn.name:
                    out.append((fn.name, name))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "query" \
                    and node.args and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value in ("fix", "access_request") and "status" in ast.unparse(node):
                out.append((fn.name, f"query({node.args[0].value}, status)"))
    return out


def test_no_second_attention_rule_exists():
    offenders = {name: calls for name in _SURFACES if (calls := _calls(SRC / name))}
    assert offenders == {}, f"compute attention through attention.items, not a rule of your own: {offenders}"
    assert {c for _, c in _calls(SRC / "attention.py")} >= {"inbox", "_owner_gates", "pending_signoffs"}


def test_a_task_item_sits_on_its_own_work_row(rig):
    """The epic's Work tree lists tasks as rows under their story, so a task's item names the task itself."""
    b, owner, _, arch, epic, story = rig
    task = b.ticket_create(arch, kind=TicketKind.task, work_type=WorkType.feature, title="Sub", parent_id=story.id)
    q = b.message_send(arch, ticket_id=task.id, kind=MessageKind.question, text="?", to=owner.id)
    row = only(attention.items(b, owner), id=q.id)
    assert row["ticket"]["id"] == task.id and row["scope"]["id"] == epic.id
    assert (row["tab"], row["section"]) == ("work", "tickets")
