"""Subscription audit (design-63db8a7d42 D): for every role card, the event kinds its feed listener receives against
the kinds it must receive, including every board hint. A gap fails here; the table is written to
docs/evidence/s-3c858b31b4/subscription-audit.md when EDP8_WRITE_AUDIT=1.

Private board, no pool, no broker."""
from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8.board import Board
from edp8.schemas import Event, EventKind, Role, TicketKind, WorkType
from edp8.store import Store, new_id

CARDS = Path(__file__).resolve().parents[1] / ".claude" / "commands"
CARD_ROLE = {"architect": Role.architect, "engineer": Role.engineer, "engineer-quick": Role.engineer,
             "qa": Role.qa, "adversary": Role.adversary, "sme": Role.sme, "doctor": Role.doctor}


@pytest.fixture
def rig():
    b = Board(Store(":memory:"), free_mb=lambda: 4096)
    owner = b.participant_create("human", Role.owner, "owner")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story = b.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    seats = {"owner": owner}
    for card, role in CARD_ROLE.items():
        if card == "engineer-quick":
            continue
        tid = story.id if role in (Role.engineer, Role.adversary) else epic.id
        hid = f"{role.value}.{tid}"
        seats[card] = b.participant_create("agent", role, hid, id_=hid)
    other = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Other")
    seats["other-architect"] = b.participant_create("agent", Role.architect, f"architect.{other.id}",
                                                    id_=f"architect.{other.id}")
    return b, epic, story, seats


def _ev(subject, ekind, **data):
    return Event(id=new_id("ev"), subject_id=subject, kind=ekind, data=data)


def _hints(epic, story):
    return {
        "qa_available": _ev(epic.id, EventKind.board_hint, hint="qa_available", by="board",
                            text="epic moved to in_review, qa now available for review"),
        "closed_seat_message": _ev(story.id, EventKind.board_hint, hint="closed_seat_message", by="board",
                                   seat=f"engineer.{story.id}", message="m-x", text="steer m-x awaits CLOSED seat",
                                   sender="owner"),
        "seat_resumed": _ev(story.id, EventKind.board_hint, hint="seat_resumed", by="board",
                            text=f"seat engineer.{story.id} is running again on {story.id}",
                            seat=f"engineer.{story.id}", session="ss-x"),
        "qa_checker_dead": _ev(epic.id, EventKind.board_hint, hint="qa_checker_dead", by="board",
                               text=f"qa seat qa.{epic.id} is gone with c-x pending on {epic.id}",
                               seat=f"qa.{epic.id}", criteria=["c-x"]),
        "requirement_reopened": _ev(epic.id, EventKind.board_hint, hint="requirement_reopened", by="board",
                                    text=f"r-x was marked on {epic.id} after it was done", requirement="r-x"),
    }


SRC = Path(__file__).resolve().parents[1] / "src" / "edp8"
_HINT_CALL = re.compile(r"""\bhint_architect\(\s*[^,()]+(?:\([^()]*\))?[^,()]*,\s*["']([a-z_]+)["']""")


def _hint_kinds_in_source() -> set[str]:
    kinds: set[str] = set()
    for py in SRC.rglob("*.py"):
        kinds.update(_HINT_CALL.findall(py.read_text(encoding="utf-8")))
    return kinds


def test_the_audit_covers_every_hint_kind_the_source_emits(rig):
    """A new `hint_architect(...)` call with an unaudited kind fails here, so a hint cannot be missed again."""
    b, epic, story, seats = rig
    emitted = _hint_kinds_in_source()
    assert len(emitted) >= 5, f"source grep found too few hint kinds: {sorted(emitted)}"
    assert set(HINT_KINDS) == emitted, "the audit rows (HINT_KINDS) must list every emitted hint kind"
    assert emitted == set(_hints(epic, story)), \
        f"audit table and source disagree: only in source {sorted(emitted - set(_hints(epic, story)))}, " \
        f"only in audit {sorted(set(_hints(epic, story)) - emitted)}"


def test_every_board_hint_reaches_the_epics_architect_and_nobody_else(rig):
    b, epic, story, seats = rig
    for name, ev in _hints(epic, story).items():
        got = {k for k, p in seats.items() if b.relevant(ev, p)}
        assert "architect" in got, f"{name}: the epic's architect listener must receive it"
        assert got == {"architect"}, f"{name}: only the architect is paged, got {sorted(got)}"


def test_a_hint_on_a_quick_task_reaches_its_owner_who_has_no_architect():
    b = Board(Store(":memory:"), free_mb=lambda: 4096)
    owner = b.participant_create("human", Role.owner, "owner")
    q = b.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.feature, title="Q", tags=["quick"])
    ev = _ev(q.id, EventKind.board_hint, hint="closed_seat_message", by="board", text="t", seat="engineer.x",
             message="m-1", sender="engineer.x")
    assert b.relevant(ev, owner)
    assert [r.value for r in b._reason_for(ev, owner)] == ["owner_listener"]


def test_the_architect_listening_contract_names_hints_and_every_card_boots_a_subscription(rig):
    b, *_ = rig
    assert "board hint" in b.listening("architect")["receives"]
    for card, role in CARD_ROLE.items():
        text = (CARDS / f"{card}.md").read_text(encoding="utf-8")
        assert "subscribe()" in text or "shared-host-rules" in text, f"{card} card never boots its subscription"
        assert b.listening(role.value)["receives"]


def _msg(where, **kw):
    return lambda e, s, me: _ev((s if where == "story" else e).id, EventKind.message_sent, kind="steer", to=me,
                                **{"from": "x"}, **kw)


MUST = {
    "architect": [
        ("question anywhere in the epic, any `to`",
         lambda e, s, me: _ev(s.id, EventKind.message_sent, kind="question", to="owner", **{"from": "x"}), True),
        ("gate opened", lambda e, s, me: _ev(e.id, EventKind.gate_opened, gate="acceptance", by="x", note="n"), True)],
    "engineer": [("message addressed to it", _msg("story"), True)],
    "qa": [("message addressed to it", _msg("epic"), True)],
    "adversary": [("message addressed to it", _msg("story"), True)],
    "sme": [("message addressed to it", _msg("epic"), True)],
    "doctor": [("message addressed to it", _msg("epic"), True)],
}
HINT_KINDS = ("qa_available", "closed_seat_message", "seat_resumed", "qa_checker_dead", "requirement_reopened")
for _card, _checks in MUST.items():  # every hint kind: the architect must receive it, every other card must not
    for _k in HINT_KINDS:
        _checks.append((f"board hint {_k}", (lambda k: lambda e, s, me: _hints(e, s)[k])(_k), _card == "architect"))


def test_audit_every_card_receives_what_it_must_and_nothing_it_must_not(rig):
    b, epic, story, seats = rig
    rows = []
    for card, checks in MUST.items():
        p = seats[card]
        for label, make, must in checks:
            got = b.relevant(make(epic, story, p.id), p)
            rows.append((card, label, "must receive" if must else "must not receive", "ok" if got == must else "GAP"))
    gaps = [r for r in rows if r[3] == "GAP"]
    if os.environ.get("EDP8_WRITE_AUDIT") == "1":
        out = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "s-3c858b31b4" / "subscription-audit.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Subscription audit (design-63db8a7d42 D)", "",
                 "Generated by `tests/test_subscription_audit.py` with `EDP8_WRITE_AUDIT=1`. Cards audited: "
                 + ", ".join(sorted(CARD_ROLE)) + ". engineer-quick shares the engineer listener; a quick task has no "
                 "architect, so a hint on it reaches its owner (pinned by "
                 "`test_a_hint_on_a_quick_task_reaches_its_owner_who_has_no_architect`).", "",
                 "| card | event | rule | result |", "|---|---|---|---|"]
        lines += [f"| {c} | {lab} | {m} | {r} |" for c, lab, m, r in rows]
        lines += ["", f"Gaps: {len(gaps)}"]
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not gaps, gaps
