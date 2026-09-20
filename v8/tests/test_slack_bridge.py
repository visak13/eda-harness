"""Slack doorbell: quiet hours, line rendering, webhook vs bot delivery."""

from __future__ import annotations

from edp8 import slack_bridge
from edp8.user_settings import save_settings


def test_quiet_window_plain_and_wraparound():
    assert slack_bridge._in_quiet([9, 17], 12)
    assert not slack_bridge._in_quiet([9, 17], 8)
    # the +12h teammate: 22 -> 7 wraps midnight
    assert slack_bridge._in_quiet([22, 7], 23)
    assert slack_bridge._in_quiet([22, 7], 3)
    assert not slack_bridge._in_quiet([22, 7], 12)
    assert not slack_bridge._in_quiet(None, 3)


def test_line_renders_deep_link_and_body():
    cfg = {"board_url": "http://100.1.2.3:9400"}
    msg = {"from": "architect.epic-1", "kind": "question",
           "body": {"ticket_id": "epic-1", "text": "your call on X?"}}
    line = slack_bridge._line(cfg, "x", msg)
    assert "your call on X?" in line
    # a ticketed ping deep-links the exact conversation with identity attached
    assert "http://100.1.2.3:9400/ui/ticket/epic-1?as=x" in line
    # no ticket -> fall back to the inbox
    bare = slack_bridge._line(cfg, "x", {"from": "pool", "kind": "crashed", "body": {}})
    assert "http://100.1.2.3:9400/ui/me?as=x" in bare


def test_line_base_falls_back_to_public_url(monkeypatch):
    """S17: with no board_url in bridge config, the deep link uses EDP8_PUBLIC_URL so a tagged
    person on another machine reaches the SPA; config board_url still wins when present."""
    monkeypatch.setenv("EDP8_PUBLIC_URL", "http://host.example:9400")
    msg = {"from": "owner", "kind": "steer", "body": {"ticket_id": "s-1", "text": "hi"}}
    assert "http://host.example:9400/ui/ticket/s-1?as=x" in slack_bridge._line({}, "x", msg)
    # config wins over the env fallback
    assert "http://cfg:9400/ui/ticket/s-1?as=x" in slack_bridge._line({"board_url": "http://cfg:9400"}, "x", msg)


def test_line_base_defaults_loopback(monkeypatch):
    monkeypatch.delenv("EDP8_PUBLIC_URL", raising=False)
    msg = {"from": "owner", "kind": "steer", "body": {"ticket_id": "s-1", "text": "hi"}}
    assert "http://127.0.0.1:9400/ui/ticket/s-1?as=x" in slack_bridge._line({}, "x", msg)


def test_post_prefers_dm_then_webhook(monkeypatch):
    calls = []

    class R:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"ok": True}

    monkeypatch.setattr(slack_bridge.httpx, "post",
                        lambda url, **kw: calls.append((url, kw)) or R)
    # bot token + slack_id -> DM
    assert slack_bridge._post({"bot_token": "xoxb-1"}, {"slack_id": "U1"}, "hi")
    assert calls[-1][0] == "https://slack.com/api/chat.postMessage"
    # webhook fallback with mention
    assert slack_bridge._post({"webhook_url": "https://hooks.slack.com/h"}, {"slack_id": "U1"}, "hi")
    assert calls[-1][0] == "https://hooks.slack.com/h"
    assert calls[-1][1]["json"]["text"].startswith("<@U1> ")
    # nothing configured -> dropped, not crashed
    assert not slack_bridge._post({}, {}, "hi")


def test_post_refuses_a_disallowed_webhook_host(monkeypatch):
    """Send-time allow-list (findings 10/17): a stored/legacy webhook on a host that is not
    allow-listed is never posted to, even though a DM or an allowed webhook still sends."""
    calls = []

    class R:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"ok": True}

    monkeypatch.setattr(slack_bridge.httpx, "post", lambda url, **kw: calls.append(url) or R)
    monkeypatch.delenv("EDP8_SLACK_WEBHOOK_HOSTS", raising=False)
    assert not slack_bridge._post({}, {"webhook_url": "https://evil.example/h"}, "hi")
    assert not slack_bridge._post({}, {"webhook_url": "https://10.0.0.5/h"}, "hi")
    assert calls == []  # nothing left the process
    assert slack_bridge._post({}, {"webhook_url": "https://hooks.slack.com/h"}, "hi")
    assert calls == ["https://hooks.slack.com/h"]


def test_send_test_ping_uses_stored_destination(monkeypatch):
    sent = []
    monkeypatch.setattr(slack_bridge, "_post", lambda cfg, person, text: sent.append((person, text)) or True)
    monkeypatch.setattr(slack_bridge, "_config", lambda: {})
    ok, detail = slack_bridge.send_test_ping("pat", {"slack_id": "U1", "webhook_url": None, "quiet": None})
    assert ok and "sent" in detail.lower() and sent[0][0]["slack_id"] == "U1"
    # a failed post surfaces a human reason, not a crash
    monkeypatch.setattr(slack_bridge, "_post", lambda *a, **k: False)
    ok, detail = slack_bridge.send_test_ping("pat", {"slack_id": "U1"})
    assert not ok and "allow-listed" in detail


def test_merge_people_enable_clear_disable_within_one_refresh(tmp_path, monkeypatch):
    """Finding m-93facfac8a #2: a board opt-out must reach a running bridge in one refresh, and a
    cleared field must propagate. enable -> present; clear quiet -> None (not the stale window);
    disable -> the entry and its watcher are retracted."""
    settings = tmp_path / "ui-settings.json"
    monkeypatch.setenv("EDP8_UI_SETTINGS", str(settings))
    people: dict = {}

    save_settings("pat", {"slack": {"enabled": True, "slack_id": "U1", "quiet": [22, 7]}})
    added, removed = slack_bridge._merge_people(people)
    assert added == ["pat"] and removed == []
    assert people["pat"]["slack_id"] == "U1" and people["pat"]["quiet"] == [22, 7]

    # the same dict object is kept so a live watcher thread sees the update
    entry = people["pat"]
    save_settings("pat", {"slack": {"enabled": True, "slack_id": "U1", "quiet": None}})
    added, removed = slack_bridge._merge_people(people)
    assert added == [] and removed == []
    assert people["pat"] is entry and people["pat"]["quiet"] is None  # cleared, not the stale [22,7]

    save_settings("pat", {"slack": {"enabled": False, "slack_id": "U1"}})
    added, removed = slack_bridge._merge_people(people)
    assert removed == ["pat"] and "pat" not in people


def test_merge_people_keeps_static_map_person(tmp_path, monkeypatch):
    """A person defined in slack_map.json (static) is never retracted by an empty/absent board file."""
    monkeypatch.setenv("EDP8_UI_SETTINGS", str(tmp_path / "absent.json"))
    people = {"boss": {"slack_id": "U9", "webhook_url": None, "quiet": None}}
    added, removed = slack_bridge._merge_people(people, static=frozenset({"boss"}))
    assert added == [] and removed == [] and people["boss"]["slack_id"] == "U9"
