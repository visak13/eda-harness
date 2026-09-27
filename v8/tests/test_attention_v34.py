"""t-852e7add63 (design-e963c656f5 v34 §4.18, owner m-8aa6439a77 / m-1a09573d3d): only real asks wait on a human,
a later message from the human to the asker clears an ask, Dismiss is a pure attention write that wakes nobody,
a GFM table straight after a paragraph renders, and the one-off cleanup report measures before/after."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import attention, broker_adapter
from edp8.board import Board, BoardError
from edp8.delivery import delivery_plan
from edp8.schemas import EventKind, MessageKind, Role, SessionState, StatusValue, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store
from edp8.views import render_message_markdown

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **kw: True)
    b = Board(Store())
    owner = b.participant_create("human", Role.owner, "owner", id_="owner")
    arch = b.participant_create("agent", Role.architect, "architect.e", id_="architect.e")
    eng = b.participant_create("agent", Role.engineer, "engineer.s", id_="engineer.s")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Asks")
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S8", parent_id=epic.id)
    for i, p in enumerate((arch, eng)):
        b.session_upsert(id_=f"s-{i}", participant_id=p.id, ticket_id=epic.id, pool_id="pool",
                         state=SessionState.alive)
    return b, owner, arch, eng, epic, story


def waiting(b, p):
    return [m["id"] for m in b.inbox(p)]


def with_status(b, m, status):
    return b.store.put("message", m.model_copy(update={"status": status}))


# ------------------------------------------------------------------ item 1: only real asks count

def test_only_real_asks_wait_on_a_human(rig):
    b, owner, arch, _, epic, _ = rig
    q = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="q")
    st = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.steer, text="s")
    dv = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.deviation, text="d")
    blocked = with_status(b, b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.status,
                                            text="blocked"), StatusValue.blocked)
    failed = with_status(b, b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.status,
                                           text="failed"), StatusValue.failed)
    deferred = with_status(b, b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.status,
                                             text="deferred"), StatusValue.deferred)
    # never: a plain status (no value, or done), a note, a finding
    b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.status, text="update")
    with_status(b, b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.status, text="done"),
                StatusValue.done)
    b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.note, text="fyi")
    b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.finding, text="found")
    assert waiting(b, owner) == [q.id, st.id, dv.id, blocked.id, failed.id, deferred.id]
    rows = attention.items(b, owner)
    assert [r["id"] for r in rows] == waiting(b, owner)  # the trail reads the same rule: no dot for an update
    assert attention.rollup(rows)["counts"]["total"] == 6


# ------------------------------------------------------------------ item 2: a human's later message clears

def test_a_later_human_message_to_the_asker_clears_without_reply_to(rig):
    # the S8 case: m-584a1c342d answered by m-f5f30e92bb, addressed to the engineer, no reply_to
    b, owner, arch, eng, epic, story = rig
    q = b.message_send(eng, ticket_id=story.id, to="owner", kind=MessageKind.question, text="step 6?")
    b.message_send(owner, ticket_id=epic.id, to=eng.id, kind=MessageKind.note, text="other ticket")
    b.message_send(owner, ticket_id=story.id, to=arch.id, kind=MessageKind.note, text="someone else")
    assert waiting(b, owner) == [q.id]  # another ticket, or another addressee, does not clear it
    b.message_send(owner, ticket_id=story.id, to=eng.id, kind=MessageKind.note, text="done, all ok")
    assert waiting(b, owner) == []
    assert attention.items(b, owner) == []


def test_a_human_message_before_the_ask_does_not_clear_it(rig):
    b, owner, _, eng, _, story = rig
    b.message_send(owner, ticket_id=story.id, to=eng.id, kind=MessageKind.steer, text="start")
    q = b.message_send(eng, ticket_id=story.id, to="owner", kind=MessageKind.question, text="which?")
    assert waiting(b, owner) == [q.id]


def test_reply_to_the_ask_still_clears(rig):
    b, owner, arch, _, epic, _ = rig
    q = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="ship?")
    b.message_send(owner, ticket_id=epic.id, to=None, kind=MessageKind.note, text="yes", reply_to=q.id)
    assert waiting(b, owner) == []


# ------------------------------------------------------------------ item 6: Dismiss

def test_dismiss_clears_every_surface_and_wakes_nobody(rig):
    b, owner, arch, eng, epic, story = rig
    q = b.message_send(eng, ticket_id=story.id, to="owner", kind=MessageKind.question, text="need a call?")
    keep = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="other")
    eng_inbox = b.inbox(eng)
    messages_before = len(b.store.query("message", {}, limit=-1))
    seq_before = b.store.max_seq()
    assert b.dismiss_asks(owner, [q.id]) == [q.id]
    assert waiting(b, owner) == [keep.id]
    assert [r["id"] for r in attention.items(b, owner)] == [keep.id]
    # a pure attention write: no message posted, the asker's inbox and feed untouched, nobody woken
    assert len(b.store.query("message", {}, limit=-1)) == messages_before
    assert b.inbox(eng) == eng_inbox
    new = [ev for _, ev in b.store.events_since(seq_before, limit=50)]
    assert [ev.kind for ev in new] == [EventKind.ask_dismissed]
    assert delivery_plan(b, new[0]) == []
    for p in (eng, arch, owner):
        assert not b.relevant(new[0], p)


def test_dismiss_refuses_what_is_not_waiting_on_you(rig):
    b, owner, arch, eng, epic, _ = rig
    to_eng = b.message_send(arch, ticket_id=epic.id, to=eng.id, kind=MessageKind.question, text="not the owner's")
    note = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.note, text="fyi")
    for bad in ([to_eng.id], [note.id], ["m-nope"]):
        with pytest.raises(BoardError):
            b.dismiss_asks(owner, bad)
    assert b.store.query("event", {"kind": EventKind.ask_dismissed}, limit=5) == []


def test_another_humans_dismissal_does_not_clear_my_ask(rig):
    b, owner, arch, _, epic, _ = rig
    other = b.participant_create("human", Role.owner, "other", id_="other")
    q = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="mine")
    b._emit(q.id, EventKind.ask_dismissed, {"by": other.id, "ticket": epic.id})
    assert waiting(b, owner) == [q.id]


def test_dismiss_route(rig):
    b, owner, arch, _, epic, _ = rig
    q = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="q")
    c = TestClient(create_app(b))
    h = {"X-Participant": "owner"}
    r = c.post("/v1/me/attention/dismiss", json={"ids": [q.id]}, headers=h)
    assert r.status_code == 200 and r.json()["value"] == {"dismissed": [q.id]}
    assert c.get("/v1/me/attention", headers=h).json()["value"]["counts"]["total"] == 0
    assert c.post("/v1/me/attention/dismiss", json={"ids": [q.id]}, headers=h).status_code >= 400


# ------------------------------------------------------------------ item 8: GFM table after a paragraph

FIXTURE_M_14333C915C = (
    "Your attention list has 21 items on this epic. 18 of them are my own status reports to you.\n"
    "| count | what | why it counts |\n|---|---|---|\n"
    "| 18 | status from architect (14:00 → 23:08) | t-9e9ba3a6e5's rule |\n"
    "| 2 | my questions m-304c22bd64 and m-d58e46d4f8 | never replied to directly |\n"
    "| 1 | S8's step-6 question m-584a1c342d | correct |\n"
    "**Why only 2 show:** the epic page loads only the recent part of the thread.\n"
    "**Proposed fix (one task, today):**\n1. Only a real ask counts.\n")


def test_table_straight_after_a_paragraph_renders():
    html = render_message_markdown(FIXTURE_M_14333C915C)
    assert html.count("<table>") == 1 and html.count("<tr>") == 4
    assert "<td>18</td>" in html and "<th>why it counts</th>" in html
    assert "<strong>Why only 2 show:</strong>" in html and "<td><strong>Why" not in html
    assert "<p>Your attention list" in html


def test_pipes_in_code_and_prose_stay_as_typed():
    html = render_message_markdown("a | b in prose\n\n```\nx | y\n|---|\n```\n")
    assert "<table>" not in html and "x | y" in html


# ------------------------------------------------------------------ item 7: the cleanup report

def _cleanup():
    spec = importlib.util.spec_from_file_location("attention_v34_cleanup", ROOT / "scripts" / "attention_v34_cleanup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cleanup_report_before_and_after(rig):
    b, owner, arch, eng, epic, story = rig
    for i in range(3):
        b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.status, text=f"update {i}")
    b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.finding, text="found")
    answered = b.message_send(eng, ticket_id=story.id, to="owner", kind=MessageKind.question, text="step 6?")
    b.message_send(owner, ticket_id=story.id, to=eng.id, kind=MessageKind.note, text="ok")
    live = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="real")
    out = _cleanup().report(b, epic.id)
    row = out["humans"][0]
    assert (row["human"], row["before"], row["after"]) == ("owner", 6, 1)
    assert row["before_by_kind"] == {"status": 3, "finding": 1, "question": 2}
    assert row["still_waiting"] == [live.id] and answered.id in row["resolved"]
