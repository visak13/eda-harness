"""t-d606b5d93f (qa m-dbf4b571de, owner m-fb5905cf40 / m-f24b793271): the product video and every doc
that states the context-pack default must match the code default, so a change of default can never
leave a stale number behind again (chapter 4 said 40 KB for hours after S23-T2 cut it to 8 KB).

The video reads its numbers from docs/video/src/code-facts.json, which docs/video/scripts/code-facts.mjs
writes from the code before every render. These tests pin that JSON, the composition and the prose to
the code. A red test after a default change means: `cd docs/video && node scripts/code-facts.mjs &&
npm run render:all`, rebuild the README cut, fix the named doc line.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from edp_contracts import settings as registry

from edp8 import bundles

V8 = Path(__file__).resolve().parents[1]
VIDEO = V8 / "docs" / "video"
FACTS = json.loads((VIDEO / "src" / "code-facts.json").read_text(encoding="utf-8"))


def _default(env: str):
    return next(s for s in registry.all_settings() if s.env == env).default_value()


def test_registry_and_bundles_agree_on_the_context_budget():
    assert _default("EDP8_CONTEXT_BUDGET_B") == bundles._CONTEXT_BUDGET_B


def test_video_facts_match_the_code():
    assert FACTS["contextBudgetBytes"] == _default("EDP8_CONTEXT_BUDGET_B"), \
        "stale src/code-facts.json: run node scripts/code-facts.mjs, then npm run render:all"
    skill = (V8 / ".claude" / "skills" / "harvest" / "SKILL.md").read_text(encoding="utf-8")
    assert f"At most {FACTS['harvestMaxLessons']}; none is a valid answer" in skill


def test_chapters_state_no_hand_typed_numbers():
    ch4 = (VIDEO / "src" / "chapters" / "Ch4Context.tsx").read_text(encoding="utf-8")
    assert 'from "../code-facts.json"' in ch4
    assert not re.search(r"\d+(\.\d+)?\s*KB (by default|default)", ch4), "Ch4 types the budget by hand"
    assert not re.search(r"/\s*\d+\s*KB", ch4), "Ch4 meter types the budget by hand"
    ch5 = (VIDEO / "src" / "chapters" / "Ch5Memory.tsx").read_text(encoding="utf-8")
    assert "FACTS.harvestMaxLessons" in ch5 and not re.search(r"≤\s*\d+ lessons", ch5)
    ch2b = (VIDEO / "src" / "chapters" / "Ch2bTeam.tsx").read_text(encoding="utf-8")
    assert "contrast(C.muted, C.bg)" in ch2b and not re.search(r"\d\.\d : 1", ch2b)


# Every prose line that states the context-pack default, as "<file>: regex whose group 1 is N KB".
# Add a line here when a doc starts stating the number. (The lookup pack, knowledge.MAX_BYTES 16 KB,
# is a different budget and is not listed.)
PROSE = {
    "guides/context-refresh.md": r"`EDP8_CONTEXT_BUDGET_B`, default (\d+) KB",
}


def test_prose_states_the_code_default():
    want = _default("EDP8_CONTEXT_BUDGET_B")
    for rel, rx in PROSE.items():
        hits = re.findall(rx, (V8 / rel).read_text(encoding="utf-8"))
        assert hits, f"{rel}: the stated default is gone; update PROSE"
        assert all(int(n) * 1000 == want for n in hits), f"{rel} states {hits} KB, the code default is {want} B"


def test_no_stale_40_kb_context_claim_anywhere():
    """The old default must not come back in the video, the guides, the cards or the skills."""
    roots = [VIDEO / "src", VIDEO / "README.md", V8 / "guides", V8 / ".claude"]
    stale = []
    for root in roots:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.suffix in {".md", ".tsx", ".ts", ".json"}]
        for p in files:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if re.search(r"context", line, re.I) and re.search(r"\b40 ?KB\b", line):
                    stale.append(f"{p.relative_to(V8)}:{i}")
    assert not stale, stale


def test_admin_settings_fixture_shows_the_code_default():
    fixture = json.loads((V8 / "web" / "src" / "test" / "fixtures" / "admin-settings.json").read_text(encoding="utf-8"))
    row = next(s for g in fixture["groups"] for s in g["settings"] if s["env"] == "EDP8_CONTEXT_BUDGET_B")
    assert row["default"] == _default("EDP8_CONTEXT_BUDGET_B"), "regenerate: scripts/gen_admin_settings_fixture.py"
