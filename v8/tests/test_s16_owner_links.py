"""S16 c-017559b2a9 (owner m-cc3a6656ee, architect m-3e9810fceb): every ask that leaves the owner an action carries a
direct link and the button to press.

- whoami gives a seat the link base (`ui_url`): EDP8_PUBLIC_URL when set, else the address the board was reached on;
- the /ticket skill's last step and the sme card carry the hand-off template (link + Pass/Fail);
- the Decisions featured sign-off says in plain words what the owner decides (`ask`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edp8 import views
from edp8.board import Board
from edp8.schemas import Check, DocType, Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store

V8 = Path(__file__).resolve().parents[1]


# ---- whoami ui_url -----------------------------------------------------------------------------

@pytest.fixture
def app_board(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    board = Board(Store(":memory:"))
    board.participant_create("agent", Role.engineer, "eng", id_="eng")
    return board


def test_whoami_ui_url_is_the_request_base_without_a_public_url(app_board, monkeypatch):
    monkeypatch.delenv("EDP8_PUBLIC_URL", raising=False)
    client = TestClient(create_app(app_board, admin_token="t"), base_url="http://127.0.0.1:9400")
    v = client.get("/v1/whoami", headers={"X-Participant": "eng"}).json()["value"]
    assert v["ui_url"] == "http://127.0.0.1:9400/ui"


def test_whoami_ui_url_follows_the_public_url(app_board, monkeypatch, tmp_path):
    monkeypatch.setenv("EDP8_PUBLIC_URL", "https://heronry.example.ts.net/")
    (tmp_path / "tokens.json").write_text(json.dumps({"owner": "o", "agents": {"eng": "eng-secret"}}), encoding="utf-8")  # public mode needs them
    client = TestClient(create_app(app_board, admin_token="not-the-default"), base_url="http://127.0.0.1:9400")
    v = client.get("/v1/whoami", headers={"X-Participant": "eng", "X-Token": "eng-secret"}).json()["value"]
    assert v["ui_url"] == "https://heronry.example.ts.net/ui"  # never the local address, never a double slash


# ---- the hand-off template in the /ticket skill and the sme card --------------------------------

def _text(rel: str) -> str:
    return (V8 / rel).read_text(encoding="utf-8")


def test_ticket_skill_last_step_is_a_direct_link_with_the_button():
    s = _text(".claude/skills/ticket/SKILL.md")
    head = "## Last step · hand the owner a link (knowledge and quick tickets)"
    assert head in s
    step = s.split(head, 1)[1].split("**Why it sticks", 1)[0]
    assert "whoami()" in step and "`ui_url`" in step  # the base comes from the board, not a typed host
    assert "<ui_url>/ticket/<ticket-id>?view=work" in step and "<ui_url>/doc/<doc-id>" in step
    # the buttons the ticket page's CriterionCard really shows (web/src/components/CriterionCard.tsx)
    assert "Approve criterion" in step and "Needs work" in step and "criterion card" in step
    card = (V8 / "web/src/components/CriterionCard.tsx").read_text(encoding="utf-8")
    assert "Approve criterion" in card and "Needs work" in card
    assert "Needs you" in step  # says not to send the owner hunting there
    assert not re.search(r"https?://(127\.0\.0\.1|localhost)", step)  # no hardcoded link base
    # the template block itself: link on its own line, not closed by punctuation
    tpl = step.split("```", 2)[1]
    link_line = next(line for line in tpl.splitlines() if "<ui_url>/ticket/" in line)
    assert re.search(r"<ui_url>/ticket/<ticket-id>\?view=work ", link_line)


def test_sme_card_says_the_owner_ask_is_a_direct_link():
    s = _text(".claude/commands/sme.md")
    line = next(line for line in s.splitlines() if line.startswith("OWNER ASK = A DIRECT LINK"))
    assert "/ticket last step" in line
    assert "<ui_url>/ticket/<ticket-id>?view=work" in line and "<ui_url>/doc/<doc-id>" in line
    assert "Approve criterion (Pass) or Needs work (Fail)" in line and "whoami()" in line
    assert not re.search(r"https?://", line)


# ---- the Decisions card says what the owner decides ---------------------------------------------

@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def ps(board):
    return {
        "owner": board.participant_create("human", Role.owner, "owner", id_="owner"),
        "arch": board.participant_create("agent", Role.architect, "arch", id_="arch"),
        "sme": board.participant_create("agent", Role.sme, "sme", id_="sme"),
    }


class _T:
    def __init__(self, title, work_type=WorkType.feature, tags=()):
        self.title, self.work_type, self.tags, self.parent_id, self.kind = title, work_type, list(tags), None, TicketKind.story


@pytest.mark.parametrize("title,work_type,tags,want", [
    ("hl-craft: shipping a multi-service Python+SPA app cross-platform", WorkType.knowledge, (), "Accept the hl-craft strategy?"),
    ("ll-craft: process control on Windows", WorkType.knowledge, (), "Accept the ll-craft domain research?"),
    ("HL-craft — packaging", WorkType.knowledge, (), "Accept the hl-craft strategy?"),
    ("Survey: board search", WorkType.knowledge, (), "Accept the research on “board search”?"),
    ("Rename the tab", WorkType.chore, ("quick",), "Accept the quick task “Rename the tab” as done?"),
    ("S7: brand the CLI", WorkType.feature, (), "Accept “brand the CLI” as meeting this criterion?"),
])
def test_signoff_ask_wording(title, work_type, tags, want):
    assert views.signoff_ask(_T(title, work_type, tags)) == want


def test_decisions_signoff_row_carries_the_ask(board, ps):
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="Productize")
    story = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.knowledge, parent_id=epic.id,
                                title="hl-craft: shipping it cross-platform")
    c = board.criterion_create(ps["arch"], ticket_id=story.id, text="A strategy_hl doc is published.",
                               check=Check.verdict, checked_by="owner")
    doc = board.doc_create(ps["sme"], doc_type=DocType.strategy_hl, title="hl 1/3", body_md="# hl", scope=epic.id)
    board.criterion_update(ps["sme"], c.id, evidence_ref=doc.id)
    rows = views.decisions_for(board, ps["owner"])["signoffs"]
    assert [r["ask"] for r in rows] == ["Accept the hl-craft strategy?"]
    assert rows[0]["criterion"]["text"] == "A strategy_hl doc is published."
