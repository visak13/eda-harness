"""e0cec S6 task 2 (c-95b0ee1d78): the architect reads lessons before designing.

The architect card has a read-lessons-before-design step (lookup on the epic's words), and
doc_create(design) returns a hint naming the recalled lessons the doc does not cite (advisory only).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import records
from edp8.board import Board
from edp8.schemas import Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store

CARD = Path(__file__).resolve().parents[1] / ".claude" / "commands" / "architect.md"


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_PAIN_FILE", str(tmp_path / "pain-points.jsonl"))
    records._pain_seen.clear()
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board):
    roles = {"owner": Role.owner, "architect": Role.architect, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h, id_=h)
            for h, r in roles.items()}


def _epic(board, rig, tags=None):
    return board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature,
                               title="retry the flaky upload", tags=tags,
                               words="Make the flaky upload retry with backoff instead of failing the render")


def _post(c, body, **kw):
    return c.post("/v1/docs", headers={"X-Participant": "architect"}, json=body, **kw)


def test_architect_card_reads_lessons_before_designing():
    # S18-6: the semantic order (read lessons, look them up, then create the design), not the card's punctuation
    card = CARD.read_text(encoding="utf-8")
    step = card.index("READ LESSONS FIRST")
    look = card.index("lookup(scope=<epic>", step)
    assert step < look < card.index("doc_create(design)", look)


def test_design_hint_names_recalled_lessons_the_doc_does_not_cite(board, rig):
    epic = _epic(board, rig)
    les = board.record_lesson(rig["qa"], domain="ops", topic="flaky upload",
                              text="a flaky upload is retried with backoff, never skipped", scope_kind="framework")
    c = TestClient(create_app(board))
    r = _post(c, {"doc_type": "design", "title": "d", "body_md": "# design\nno lessons here", "scope": epic.id})
    assert r.status_code == 200, r.text
    hint = r.json()["hint"]
    assert les.id in hint and "does not cite" in hint and "advisory" in hint
    cited = _post(c, {"doc_type": "design", "title": "d2", "body_md": f"# design\nper {les.id}, retry", "scope": epic.id})
    assert les.id not in cited.json()["hint"] and cited.json()["hint"].startswith("link it")


def test_the_nudge_is_design_only_and_never_blocks(board, rig):
    epic = _epic(board, rig)
    board.record_lesson(rig["qa"], domain="ops", topic="flaky upload", text="a flaky upload is retried with backoff",
                        scope_kind="framework")
    c = TestClient(create_app(board))
    note = _post(c, {"doc_type": "note", "title": "n", "body_md": "x", "scope": epic.id})
    assert note.status_code == 200 and "recalled lesson" not in note.json()["hint"]
    nowhere = _post(c, {"doc_type": "design", "title": "g", "body_md": "x", "scope": "global"})
    assert nowhere.status_code in (200, 400, 403)  # a scope that is no epic gets no nudge and no crash
    assert "recalled lesson" not in (nowhere.json().get("hint") or "")


def test_the_nudge_never_names_a_lesson_from_another_project(board, rig):
    epic = _epic(board, rig)  # a framework epic
    board.record_lesson(rig["qa"], domain="ops", topic="flaky upload",
                        text="a flaky upload of a mesh is retried with backoff", project="beech-tree")
    c = TestClient(create_app(board))
    r = _post(c, {"doc_type": "design", "title": "d", "body_md": "x", "scope": epic.id})
    assert "recalled lesson" not in r.json()["hint"]
