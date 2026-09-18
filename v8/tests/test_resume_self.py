"""resume_self (owner m-268fc869f5, 2026-09-18): the seat-side resume command."""

from __future__ import annotations

from edp8 import bundles
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES, ResumeSelfArgs


class _FakeClient:
    participant = "engineer.s-1"
    base_url = "http://127.0.0.1:9400"
    statuses: list[tuple] = []

    def whoami(self):
        return {"ok": True, "value": {"id": "engineer.s-1", "role": "engineer"}}

    def listening(self):
        return {"ok": True, "value": {"wakes": ["addressed to you"]}}

    def inbox(self):
        return {"ok": True, "value": [{"id": "m-1", "kind": "steer", "answer_with": "message_send(...)"}]}

    def record_status(self, status, note="", to=None, ticket_id=None):
        self.statuses.append((status, note))
        return {"ok": True}


def test_resume_self_is_in_every_role_bundle_and_regenerates_the_boot_from_the_board(monkeypatch):
    assert "resume_self" in ALL_TOOLS
    for role, tools in ROLE_BUNDLES.items():
        assert "resume_self" in tools, role
    fake = _FakeClient()
    monkeypatch.setattr(bundles, "get_client", lambda: fake)
    out = bundles._resume_self(ResumeSelfArgs())
    assert out["ok"]
    v = out["value"]
    assert v["identity"]["id"] == "engineer.s-1"
    assert "edp8.feed_driver --participant engineer.s-1" in v["monitor_cmd"]
    assert v["cron"]["expr"] == "*/30 * * * *"
    assert v["open_asks"][0]["id"] == "m-1"
    assert len(v["steps"]) == 4 and v["steps"][0].startswith("1. Arm")
    assert "1 open ask" in v["steps"][1]
    # transparency: the resume is recorded on the seat's thread
    assert fake.statuses and fake.statuses[0][1].startswith("[resumed]")
    assert "get_guide('resume')" in out["hint"]


def test_resume_guide_exists_and_every_role_card_points_at_it():
    from pathlib import Path
    home = Path(bundles.__file__).resolve().parents[2]
    assert (home / "guides" / "resume.md").is_file()
    for card in (home / ".claude" / "commands").glob("*.md"):
        body = card.read_text(encoding="utf-8")
        assert "resume_self()" in body, card.name
        # owner m-976c2a95f1 (2026-09-18): context_delta lives in every role card, not in a steer
        assert "context_delta(cursor=" in body and "get_guide('context-refresh')" in body, card.name
