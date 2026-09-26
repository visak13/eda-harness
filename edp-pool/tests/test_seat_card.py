"""s-ccdafcb229 (owner m-b13c61ddea): EDP_CARD picks a per-flow role card for every launcher."""
from pathlib import Path

from edp_pool.pi_launcher import role_card_text
from edp_pool.pty_launcher import activation_text


def test_activation_uses_the_flow_card_when_given():
    assert activation_text("engineer") == "/engineer"
    assert activation_text("engineer", "engineer-quick") == "/engineer-quick"


def test_a_malformed_card_name_is_ignored():
    assert activation_text("engineer", "../evil") == "/engineer"
    assert activation_text("engineer", "") == "/engineer"


def test_pi_reads_the_flow_card_and_falls_back_to_the_role(tmp_path: Path):
    cmds = tmp_path / ".claude" / "commands"
    cmds.mkdir(parents=True)
    (cmds / "engineer.md").write_text("EPIC CARD", encoding="utf-8")
    (cmds / "engineer-quick.md").write_text("QUICK CARD", encoding="utf-8")
    assert role_card_text(str(tmp_path), "engineer-quick", fallback="engineer") == "QUICK CARD"
    assert role_card_text(str(tmp_path), "missing-card", fallback="engineer") == "EPIC CARD"
    assert role_card_text(str(tmp_path), "engineer") == "EPIC CARD"
