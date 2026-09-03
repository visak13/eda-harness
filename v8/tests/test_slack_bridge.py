"""Slack doorbell: quiet hours, line rendering, webhook vs bot delivery."""

from __future__ import annotations

from edp8 import slack_bridge


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
