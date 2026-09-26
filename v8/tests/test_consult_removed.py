"""S4 (s-733de6e29f, design-e963c656f5 §4.6): the consult bridge is gone; codex work is a spawned codex seat.

Criteria c-4a79afc6b6 (no bundle exposes consult/consult_status, consult.py and the Consult* enums deleted,
no `consult(` line left in the agent home, codex_seat owns its MCP containment) and c-748eb3755a (the
codex-images guide replaces sol-pairing; the cards route codex work through seats).
"""
import importlib
import re
from pathlib import Path

import pytest

from edp8 import schemas
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES

V8 = Path(__file__).resolve().parents[1]
AGENT_HOME_TEXT = [V8 / ".claude", V8 / "guides", V8 / "CLAUDE.md", V8 / "docs" / "OPERATING.md"]


def _texts():
    for root in AGENT_HOME_TEXT:
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file() and p.suffix == ".md")
        for p in files:
            yield p, p.read_text(encoding="utf-8")


@pytest.mark.parametrize("role", sorted(ROLE_BUNDLES))
def test_no_role_bundle_exposes_consult(role):
    assert not {"consult", "consult_status"} & set(ROLE_BUNDLES[role])


def test_the_tools_the_module_and_the_enums_are_deleted():
    assert "consult" not in ALL_TOOLS and "consult_status" not in ALL_TOOLS
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("edp8.consult")
    for name in ("ConsultPurpose", "ConsultProfile", "ConsultModel"):
        assert not hasattr(schemas, name)
    assert not (V8 / "src" / "edp8" / "consult.py").exists()


def test_codex_seat_owns_its_mcp_containment():
    from edp8.codex_seat import containment, seat
    assert seat.containment is containment
    args = containment.mcp_containment_args([{"name": "cua_repl", "transport": "stdio"}])
    assert 'mcp_servers.cua_repl.command="edp8-disabled"' in args and "features.apps=false" in args
    assert "unreal-mcp" in containment.mcp_disabled_names([])
    src = (V8 / "src" / "edp8" / "codex_seat" / "seat.py").read_text(encoding="utf-8")
    assert "consult" not in src


def test_no_consult_call_is_left_in_the_agent_home():
    hits = [f"{p.relative_to(V8)}:{n}" for p, text in _texts()
            for n, line in enumerate(text.splitlines(), 1) if "consult(" in line]
    assert hits == []


def test_codex_images_is_the_only_codex_image_guide_and_covers_the_three_steps():
    assert not (V8 / "guides" / "sol-pairing.md").exists()
    guide = (V8 / "guides" / "codex-images.md").read_text(encoding="utf-8")
    for must in ("image_gen", "named directory", "~/.codex/generated_images/", "view_image", "artifact_upload"):
        assert must in guide
    others = [p.name for p, text in _texts() if p.name != "codex-images.md" and "image_gen" in text
              and p.parent.name == "guides" and p.name not in ("astra-seat.md", "harness-parity.md")]
    assert others == []  # astra-seat/harness-parity are the harness's measured history, not how-to


def test_the_cards_route_codex_work_through_seats():
    qa = (V8 / ".claude" / "commands" / "qa.md").read_text(encoding="utf-8")
    assert "spawn(role=adversary, ticket_id=<epic>)" in qa and "to='architect'" in qa
    assert "work_type=review" in qa  # an existing review story's findings are read, not re-run
    adv = (V8 / ".claude" / "commands" / "adversary.md").read_text(encoding="utf-8")
    assert "ONE hostile pass of your own" in adv and "claude-fable-5-1" in adv
    eng = (V8 / ".claude" / "commands" / "engineer.md").read_text(encoding="utf-8")
    assert "no per-story second opinion" in eng and "workspace-write codex seat" in eng
    quick = (V8 / ".claude" / "commands" / "engineer-quick.md").read_text(encoding="utf-8")
    assert not re.search(r"consult", quick)
    brief = (V8 / "guides" / "strategy-creative-reference-then-build.md").read_text(encoding="utf-8")
    assert "An unread image cannot PASS" in brief and "workspace-write codex seat" in brief
