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

from asks_support import serve
from edp8 import attention, broker_adapter, notifications, topics, views
from edp8.board import Board
from edp8.schemas import AccessRequest, Check, TicketStatus, DocType, FixProposal, Gate, MessageKind, Role, TicketKind, WorkType
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


def _help_topic(b, owner):
    from edp8 import help as help_
    return b.ticket(help_.ask(b, owner, "Board is slow")["topic"]["id"])


def test_the_retired_attention_kinds_are_gone(rig):
    """s-aa76c83998: a gate, a sign-off, a fix proposal and an access request are no longer attention items."""
    from edp8.schemas import AccessRequest
    b, owner, _, arch, epic, story = rig
    assert attention.KINDS == ("ask",)
    ready_for_signoff(b, arch, epic)
    b.gate_open(epic.id, Gate.design_signoff)
    t = _help_topic(b, owner)
    b.store.put("fix", FixProposal(id=new_id("fix"), created_by="doctor", topic_id=t.id,
                                   action={"kind": "service.restart", "service": "board"}, effect="restart",
                                   request={"method": "POST", "path": "/x", "body": {}}))
    b.store.put("access_request", AccessRequest(id=new_id("ar"), created_by="anonymous", name="Sam",
                                                role_wanted="owner"))
    assert attention.items(b, owner) == []


def test_a_gate_reaches_the_owner_as_a_chat_message_and_settles_with_it(rig):
    b, owner, _, _, epic, story = rig
    ev = b.gate_open(story.id, Gate.scope, note="Split Ship sheet in two?")
    m = b.store.get("message", ev.data["notice"])
    assert m.ticket_id == story.id and m.to == owner.id and m.kind == MessageKind.question
    assert m.created_by == "board" and "Split Ship sheet in two?" in m.text
    assert only(attention.items(b, owner), id=m.id)["kind"] == "ask"
    b.gate_answer(owner, story.id, Gate.scope, "approved")
    assert attention.items(b, owner) == []  # answering the gate settles its notice


def test_a_closed_gate_settles_its_notice(rig):
    b, owner, _, arch, epic, story = rig
    ev = b.gate_open(story.id, Gate.scope)
    assert len(attention.items(b, owner)) == 1
    b.ticket_update(arch, story.id, status=TicketStatus.dropped)
    assert attention.items(b, owner) == []
    assert ev.data["notice"]


def test_the_design_signoff_gate_posts_no_message(rig):
    b, owner, _, arch, epic, _ = rig
    ready_for_signoff(b, arch, epic)
    ev = b.gate_open(epic.id, Gate.design_signoff)
    assert "notice" not in ev.data and attention.items(b, owner) == []


def _access_topics(b):
    from edp8.board import is_access
    return [t for t in b.store.query("ticket", {"kind": "topic"}, limit=-1) if is_access(t)]


def test_an_access_request_posts_to_one_standing_topic_and_settles_when_decided(rig):
    from edp8.admin import access
    b, owner, other, *_ = rig
    reqs = [AccessRequest(id=new_id("ar"), created_by="anonymous", name=n, role_wanted="owner")
            for n in ("Sam", "Kim", "Lee")]
    for q in reqs:
        b.store.put("access_request", q)
        access._notify_owner(b, q)
    (topic,) = _access_topics(b)  # opened once, however many requests
    assert topic.title == "Access requests" and topic.tags == ["access-requests"]
    assert not any(t.id == topic.id for t in topics.list_view(b))  # not a Library topic
    rows = attention.items(b, owner)
    assert len(rows) == 3 and all(r["scope"]["id"] == topic.id for r in rows)
    access._settle_notice(b, reqs[0].id, "approved")
    access._settle_notice(b, reqs[1].id, "denied")
    left = attention.items(b, owner)
    assert len(left) == 1 and reqs[2].id in b.store.get("message", left[0]["id"]).text
    assert attention.items(b, other) == []
    with pytest.raises(Exception, match="access-requests"):  # the tag cannot be spoofed on an ordinary ticket
        b.ticket_create(owner, kind=TicketKind.topic, work_type=WorkType.knowledge, title="x", tags=["access-requests"])


# ------------------------------------------------------------------ clearing + rollup

def test_an_item_clears_only_when_answered(rig):
    b, owner, _, arch, epic, _ = rig
    q = b.message_send(arch, ticket_id=epic.id, kind=MessageKind.question, text="?", to=owner.id)
    b.thread(epic.id)  # reading the thread (opening the item) is not answering it
    assert {r["id"] for r in attention.items(b, owner)} == {q.id}
    b.message_send(owner, ticket_id=epic.id, kind=MessageKind.answer, text="yes", to=arch.id, reply_to=q.id)
    assert attention.items(b, owner) == []


def test_rollup_counts_every_hop_and_writes_the_reason(rig):
    b, owner, _, arch, epic, story = rig
    t = _help_topic(b, owner)
    b.message_send(arch, ticket_id=story.id, kind=MessageKind.question, text="1", to=owner.id)
    b.message_send(arch, ticket_id=story.id, kind=MessageKind.question, text="2", to=owner.id)
    b.message_send(arch, ticket_id=epic.id, kind=MessageKind.question, text="x", to=owner.id)
    b.message_send(arch, ticket_id=t.id, kind=MessageKind.question, text="3", to=owner.id)
    lib = topics.create(b, owner, title="Rendering")["topic"]
    b.message_send(arch, ticket_id=lib.id, kind=MessageKind.question, text="4", to=owner.id)
    roll = attention.rollup(attention.items(b, owner))
    assert roll["counts"] == {"total": 5, "epics": 3, "topics": 1, "help": 1, "admin": 0}
    e = only(roll["scopes"], id=epic.id)
    assert e["count"] == 3 and e["reason"] == "3 questions"
    assert e["tabs"] == {"work": 2, "thread": 1}
    assert e["sections"] == {"work/tickets": 2, "thread/asks": 1} and e["tickets"] == {story.id: 2}
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
    assert len(notifications.attention(b, owner, since=cursor)["requests"]) == 1
    assert views.epics_summary(b, owner)[0]["attention"]["count"] == 1
    monkeypatch.setattr(attention, "items", lambda board, viewer: [])  # the one derivation says: nothing
    assert views.summary_for(b, owner)["counts"]["waiting_on_you"] == 0
    assert views.summary_for(b, owner)["attention"]["total"] == 0
    assert notifications.attention(b, owner, since=cursor)["requests"] == []
    assert views.epics_summary(b, owner)[0]["attention"] is None
    assert not views.conversations_for(b, owner) or not any(r["unread"] for r in views.conversations_for(b, owner))
    assert q.id  # the message itself is untouched: only the derivation decides


# The primitive rules attention.items composes; outside their own definitions only attention.py may call them among
# the modules that serve people's attention surfaces. Agents' own inbox (board.inbox via /v1/inbox, context,
# context_delta, close_check) is the ask rule itself, the one attention reads.
_RULES = {"inbox"}
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
    assert {c for _, c in _calls(SRC / "attention.py")} >= {"inbox"}


def test_a_task_item_sits_on_its_own_work_row(rig):
    """The epic's Work tree lists tasks as rows under their story, so a task's item names the task itself."""
    b, owner, _, arch, epic, story = rig
    task = b.ticket_create(arch, kind=TicketKind.task, work_type=WorkType.feature, title="Sub", parent_id=story.id, serves=serve(b, story.id))
    q = b.message_send(arch, ticket_id=task.id, kind=MessageKind.question, text="?", to=owner.id)
    row = only(attention.items(b, owner), id=q.id)
    assert row["ticket"]["id"] == task.id and row["scope"]["id"] == epic.id
    assert (row["tab"], row["section"]) == ("work", "tickets")
