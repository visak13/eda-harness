"""Mention tokeniser contract (adversary round 2 #6): the board's @handle extraction must agree
with tests/fixtures/mention_cases.json — the fixture the SPA composer's mentionTokens is tested
against too. Code spans/fences never mention; emails are not mentions; trailing `.`/`,` is
punctuation; unresolvable handles stay prose."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from edp8.board import Board, _mention_handles
from edp8.schemas import Role
from edp8.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "mention_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def board() -> Board:
    b = Board(Store(":memory:"))
    for h in CASES["handles"]:
        b.participant_create("agent", Role.engineer, h)
    return b


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["text"][:40] for c in CASES["cases"]])
def test_board_mentions_match_contract(board: Board, case: dict) -> None:
    ids = board.mentions(case["text"])
    handles = [board.participant(pid).handle for pid in ids]
    assert handles == case["expect"], case["text"]


def test_tokeniser_keeps_duplicates_and_strips_punctuation() -> None:
    # raw tokens (before participant resolution): duplicates kept, trailing punctuation dropped
    assert _mention_handles("@bob, @bob. and @qa.epic-1,") == ["bob", "bob", "qa.epic-1"]
    assert _mention_handles("a@b.com x@bob.com alice@bob") == []
    assert _mention_handles("`@bob` ```\n@alice\n``` @bob") == ["bob"]
    assert _mention_handles("") == []
    assert _mention_handles(None) == []  # type: ignore[arg-type]
