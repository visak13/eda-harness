"""S8 (s-60c63f2d8e): the heartbeat moved from a model cron into the feed driver.

c-94568f1183: a quiet board prints nothing; a change the feed did not deliver prints one line; an
in_progress doing seat gets a liveness ping; cards, subscribe() and resume_self no longer ask a seat to
CronCreate. Runs against a real in-memory board through its HTTP app.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from edp8 import feed_driver
from edp8.feed_driver import Heartbeat
from test_context_tools import H, board, client, rig  # noqa: F401 — fixtures

ENG = {"X-Participant": "eng"}
ARCH = {"X-Participant": "arch"}


def make_hb(client, participant="eng", headers=ENG, clock=None):
    lines: list[dict] = []

    def fetch(path, params):
        return client.get(path, headers=headers, params={k: v for k, v in params.items() if v is not None}).json()

    hb = Heartbeat(participant, fetch, clock=clock or (lambda: 0.0), emit=lines.append)
    assert hb.baseline()
    return hb, lines


def go_in_progress(client, ticket_id):
    seen = []
    client.post("/v1/criteria", headers=ARCH, json={"ticket_id": ticket_id, "text": "the capture renders",
                                                      "check": "look", "checked_by": "engineer"})
    for who in (ARCH, ENG, H):
        for status in ("designed", "signed_off", "ready", "in_progress"):
            r = client.patch(f"/v1/tickets/{ticket_id}", headers=who, json={"status": status}).json()
            seen.append((who["X-Participant"], status, (r.get("error") or {}).get("message")))
            if r.get("ok") and r["value"]["status"] == "in_progress":
                return
    raise AssertionError(f"cannot reach in_progress: {seen}")


def test_quiet_board_prints_nothing_over_many_ticks(client, rig):
    hb, lines = make_hb(client)
    for _ in range(5):
        assert hb.tick() is None
    assert lines == []


def test_a_change_the_feed_did_not_deliver_prints_one_line(client, rig):
    hb, lines = make_hb(client)
    client.post("/v1/messages", headers=H, json={"ticket_id": rig["t1"]["id"], "kind": "note", "text": "new work"})
    line = hb.tick()
    assert line is not None and len(lines) == 1
    assert line["heartbeat"]["reason"] == "changes" and line["heartbeat"]["changes"] >= 1
    assert "context_delta" in line["heartbeat"]["next"]
    assert hb.tick() is None            # the cursor advanced: the same change is not repeated
    assert len(lines) == 1


def test_a_change_the_feed_already_delivered_is_not_repeated(client, rig):
    hb, lines = make_hb(client)
    client.post("/v1/messages", headers=H, json={"ticket_id": rig["t1"]["id"], "kind": "note", "text": "feed saw it"})
    seqs = [c["seq"] for c in client.get("/v1/context_delta", headers=ENG,
                                         params={"cursor": hb.cursor}).json()["value"]["changes"]]
    assert seqs
    for s in seqs:                      # the live feed printed these events and woke the seat
        hb.note_wake(s)
    assert hb.tick() is None and lines == []


def test_in_progress_doing_seat_gets_a_liveness_ping_each_tick(client, rig):
    go_in_progress(client, rig["t1"]["id"])
    hb, lines = make_hb(client)
    first, second = hb.tick(), hb.tick()
    for line in (first, second):
        assert line["heartbeat"]["reason"] == "liveness" and line["heartbeat"]["ticket"] == rig["t1"]["id"]
        assert "RESUME THE NEXT UNBUILT ITEM" in line["heartbeat"]["next"]
    assert len(lines) == 2


def test_a_listening_seat_gets_no_liveness_ping(client, rig):
    hb, lines = make_hb(client, "arch", ARCH)
    assert hb.tick() is None and lines == []


def test_a_doing_seat_whose_ticket_is_not_in_progress_stays_quiet(client, rig):
    hb, lines = make_hb(client)          # t1 is drafted
    assert hb.tick() is None and lines == []


def test_a_refused_cursor_prints_a_resync_line_and_rebases(client, rig):
    hb, lines = make_hb(client)
    hb.cursor = "not-a-cursor"
    line = hb.tick()
    assert line["heartbeat"]["reason"] == "resync" and "context()" in line["heartbeat"]["next"]
    assert hb.cursor != "not-a-cursor" and hb.tick() is None


def test_a_quiet_cursor_is_rebased_before_the_board_expires_it(client, rig):
    now = [0.0]
    hb, lines = make_hb(client, clock=lambda: now[0])
    old = hb.cursor
    now[0] = 13 * 3600
    assert hb.tick() is None            # nothing changed: re-basing is silent
    assert hb.cursor != old and hb._based_at == 13 * 3600 and lines == []


def test_an_unreachable_board_is_silent_and_keeps_the_cursor(client, rig):
    hb, lines = make_hb(client)
    cursor = hb.cursor
    hb._fetch = lambda path, params: {"ok": False, "error": {"code": "unreachable", "message": "down"}}
    assert hb.tick() is None and hb.cursor == cursor and lines == []


def test_the_wake_line_is_a_printed_json_line_and_byte_capped(capsys):
    feed_driver._print({"heartbeat": {"reason": "liveness", "ticket": "s-1", "next": "x" * 9000}})
    out = capsys.readouterr().out.strip()
    assert out.startswith('{"heartbeat"') and len(out.encode()) <= 2000


def test_heartbeat_interval_is_a_setting_and_zero_turns_it_off(monkeypatch):
    assert feed_driver._heartbeat_interval() == 1800
    monkeypatch.setenv("EDP8_HEARTBEAT_S", "0")
    assert feed_driver._heartbeat_interval() == 0


# ---- nothing asks a seat to arm a cron any more
def test_subscribe_returns_no_cron_and_resume_self_does_not_ask_for_one(client, rig, monkeypatch):
    from edp8 import bundles
    from edp8.client import BoardClient
    monkeypatch.setattr(bundles, "get_client", lambda: _FakeClient(client))
    out = bundles._subscribe(bundles.SubscribeArgs())
    assert "cron" not in out["value"] and "CronCreate" not in json.dumps(out)


def test_the_rearm_rule_is_in_the_hint_and_both_guides(client, monkeypatch):
    # the heartbeat lives inside the Monitor: a timed-out Monitor takes it down, so every wake-plane text says re-arm
    from edp8 import bundles
    monkeypatch.setattr(bundles, "get_client", lambda: _FakeClient(client))
    hint = bundles._subscribe(bundles.SubscribeArgs())["hint"]
    assert "timed out" in hint and "re-arm monitor_cmd at once" in hint and "persistent:true" in hint
    guides = Path(__file__).resolve().parents[1] / "guides"
    for name in ("resume.md", "shared-host-rules.md"):
        text = " ".join((guides / name).read_text(encoding="utf-8").split())
        assert "re-arm `monitor_cmd` at once" in text and "persistent: true" in text, name


class _FakeClient:
    participant = "eng"
    base_url = "http://127.0.0.1:9400"

    def __init__(self, c):
        self.c = c

    def listening(self):
        return self.c.get("/v1/listening", headers=ENG).json()


CARDS = Path(__file__).resolve().parents[1] / ".claude" / "commands"


@pytest.mark.parametrize("card", sorted(p.name for p in CARDS.glob("*.md")))
def test_role_cards_no_longer_say_cron(card):
    text = (CARDS / card).read_text(encoding="utf-8")
    assert not re.search(r"cron|CronCreate", text, re.I), f"{card} still tells the seat to arm a cron"
