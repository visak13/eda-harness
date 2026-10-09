"""Independent F4 recheck at b4b35b1b; synthetic, isolated Board only."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
from conftest import isolated_home, isolated_tokens, no_pool_watch, no_browser_tool, no_wake_mod_env
from test_requirements import b, r, say
from edp8.board import BoardError
from edp8.schemas import DocType, EventKind, TicketStatus


def set_status(b, eid, status):
    epic = b.ticket(eid)
    epic.status = status
    b.store.put("ticket", epic)


@pytest.mark.parametrize("initial", [TicketStatus.done, TicketStatus.partial, TicketStatus.dropped, TicketStatus.in_progress])
def test_new_mark_has_only_the_accepted_reopen_effect(b, r, initial):
    m = say(b, r)
    eid = r["epic"].id
    set_status(b, eid, initial)
    before = len(b.store.query("event", {"kind": EventKind.status_changed}, limit=1000))
    req = b.requirement_mark(r["owner"], message_id=m.id)
    reopened = initial in (TicketStatus.done, TicketStatus.partial)
    assert b.ticket(eid).status == (TicketStatus.in_progress if reopened else initial)
    changes = b.store.query("event", {"kind": EventKind.status_changed}, limit=1000)[before:]
    hints = [e for e in b.store.query("event", {"kind": EventKind.board_hint}, limit=1000)
             if e.data.get("hint") == "requirement_reopened"]
    assert len(changes) == len(hints) == int(reopened)
    if reopened:
        assert changes[0].data == {"from": initial.value, "to": "in_progress", "by": "board",
                                    "trigger": f"requirement {req.id} marked"}
        assert hints[0].data["requirement"] == req.id


def test_duplicates_reads_links_messages_and_refused_marks_do_not_reopen(b, r):
    m = say(b, r, "first second")
    eid = r["epic"].id
    req = b.requirement_mark(r["owner"], message_id=m.id, char_start=0, char_end=5)
    d = b.doc_create(r["architect"], doc_type=DocType.design, title="D", scope=eid, body_md="# Design\n\n## Scope\nFirst.\n")
    b.requirement_link(r["architect"], req.id, doc=d.id, version=1, heading="Scope")
    set_status(b, eid, TicketStatus.done)
    before = len(b.store.query("event", {"kind": EventKind.status_changed}, limit=1000))
    assert b.requirement_mark(r["owner"], message_id=m.id, char_start=0, char_end=5).id == req.id
    b.requirements(eid)
    b.requirement_link(r["architect"], req.id, doc=d.id, version=1, heading="Scope")
    say(b, r, "ordinary follow-up, not a requirement")
    with pytest.raises(BoardError):
        b.requirement_mark(r["architect"], message_id=m.id, char_start=6, char_end=12)
    with pytest.raises(BoardError):
        b.requirement_mark(r["owner"], message_id=m.id, char_start=0, char_end=99)
    assert b.ticket(eid).status == TicketStatus.done
    assert len(b.store.query("event", {"kind": EventKind.status_changed}, limit=1000)) == before
    b.requirement_mark(r["owner"], message_id=m.id, char_start=6, char_end=12)
    assert b.ticket(eid).status == TicketStatus.in_progress
