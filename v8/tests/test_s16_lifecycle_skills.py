"""S16 (s-ca39f10643, c-9395139668): the /epic and /ticket skills name only statuses, gates and moves that
exist in the Standard workflow tables, and the role cards point at them instead of restating the walk."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from edp8.board import Board
from edp8.schemas import TRANSITIONS, Gate, TicketStatus

HOME = Path(__file__).resolve().parents[1]
SKILLS = {"epic": HOME / ".claude/skills/epic/SKILL.md", "ticket": HOME / ".claude/skills/ticket/SKILL.md"}
STATUSES = {s.value for s in TicketStatus}
GATES = {g.value for g in Gate}
BACKTICKED = re.compile(r"`([a-z_]+)`")


def _rows(text: str) -> list[tuple[str, str, str]]:
    """(needs, tool, leaves) for every step row of every walk table: | # | Step | Needs | Tool (who) | Leaves it |."""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if len(cells) >= 5 and cells[0].isdigit():
            rows.append((cells[2], " | ".join(cells[3:-1]), cells[-1]))
    return rows


def _status(cell: str) -> str | None:
    found = BACKTICKED.findall(cell)
    assert len(found) <= 1, cell
    return found[0] if found else None


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_every_status_gate_and_move_in_the_skill_exists_in_the_standard_workflow(name):
    text = SKILLS[name].read_text(encoding="utf-8")
    rows = _rows(text)
    assert len(rows) >= 8, f"{name}: the walk tables are missing"
    for needs, tool, leaves in rows:
        a, b = _status(needs), _status(leaves)
        assert b in STATUSES, (name, leaves)
        if a is None:
            assert needs == "—", (name, needs)
            continue
        assert a in STATUSES, (name, needs)
        legal = a == b or b in TRANSITIONS[TicketStatus(a)]
        if name == "epic" and not legal:  # the board's forward phase carry (drafted → … → in_review)
            order = [s.value for s in Board._EPIC_PHASE_ORDER]
            legal = a in order and b in order and order.index(a) < order.index(b)
        assert legal, f"{name}: {a} → {b} is not a Standard-workflow move"
        # every status a tool call in the row names is a real status too
        for word in re.findall(r"status=([a-z_]+)", tool):
            assert word in STATUSES, (name, word)
    for gate in re.findall(r"gate_open\(([a-z_]+)\)", text):
        assert gate in GATES, (name, gate)
    assert "Standard" in text and "Design tab" in text and "/ui/design" in text


def test_ticket_skill_covers_both_a_story_and_a_standalone_quick_ticket():
    text = SKILLS["ticket"].read_text(encoding="utf-8")
    assert "Story inside an epic" in text and "Standalone quick ticket" in text
    assert "gate_open(design_signoff)" in text and "checker_for" in text


@pytest.mark.parametrize("card,skill", [("architect", "/epic"), ("engineer", "/ticket"),
                                         ("engineer-quick", "/ticket"), ("qa", "/ticket")])
def test_role_cards_point_at_the_lifecycle_skills(card, skill):
    text = (HOME / f".claude/commands/{card}.md").read_text(encoding="utf-8")
    skills_line = next(line for line in text.splitlines() if line.startswith("**SKILLS**"))
    assert skill in skills_line, (card, skills_line)
