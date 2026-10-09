"""S9 (c-fad33cf7c2; owner m-fc77f7e7c3, qa m-c2db4d16ef): the role cards and skills a seat loads stay at or below
the byte cut the owner accepted, -23.5% against 7c3e9e9 over the 19 files that existed then. A card or skill edit
that grows them past it fails here, so the budget cannot drift again unseen."""
from __future__ import annotations

from pathlib import Path

V8 = Path(__file__).resolve().parents[1]
BASELINE_B = 42_750  # `git cat-file -s` summed over the 19 files at 7c3e9e9
CUT = 0.235
FILES = [f".claude/commands/{n}.md" for n in
         ("adversary", "architect", "doctor", "engineer-quick", "engineer", "qa", "sme")] + \
        [f".claude/skills/{n}/SKILL.md" for n in
         ("demo", "deviation", "doubt", "epic", "handoff", "harvest", "learn", "methodology", "ocak", "pain",
          "ticket", "verify")]


def _size(rel: str) -> int:
    return len((V8 / rel).read_bytes().replace(b"\r\n", b"\n"))  # the blob size: a CRLF checkout counts as LF


def test_the_19_baseline_cards_and_skills_hold_the_accepted_cut():
    assert len(FILES) == 19
    total = sum(_size(f) for f in FILES)
    cap = int(BASELINE_B * (1 - CUT))
    assert total <= cap, (f"cards+skills are {total} B, {100 * (total - BASELINE_B) / BASELINE_B:.2f}% vs 7c3e9e9; "
                          f"the accepted cut is -23.5% (<= {cap} B): trim before adding")
