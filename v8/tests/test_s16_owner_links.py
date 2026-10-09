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

from edp8.board import Board
from edp8.schemas import Role
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
    assert "Needs you" not in step  # the Needs you view is gone (s-aa76c83998); the link is the only route
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
