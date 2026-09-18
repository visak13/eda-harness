"""Settings tab store + /v1/me/settings + Slack bridge merge (epic-44a0576511 · s-7f663c6322)."""

from __future__ import annotations

import json

from edp8 import slack_bridge, user_settings


def test_store_round_trip_normalises_and_masks(tmp_path):
    f = tmp_path / "ui-settings.json"
    stored = user_settings.save_settings("owner", {
        "profile": {"display_name": "  Morgan ", "junk": 1},
        "notifications": {"browser": True, "quiet": ["22", "7"]},
        "slack": {"enabled": True, "slack_id": "U123", "webhook_url": "https://hooks.slack.com/services/T/B/x"},
        "unknown": {"x": 1},
    }, path=f)
    assert stored["profile"]["display_name"] == "Morgan"
    assert stored["notifications"]["quiet"] == [22, 7]
    assert stored["slack"]["webhook_url"].endswith("/T/B/x")
    assert "unknown" not in stored
    shown = user_settings.public(user_settings.load_settings("owner", path=f))
    assert shown["slack"]["webhook_set"] is True
    assert "/T/B/x" not in shown["slack"]["webhook_url"]
    assert shown["slack"]["webhook_url"].startswith("https://***hooks.slack.com")
    # a save that echoes the masked url keeps the secret on disk
    again = user_settings.save_settings("owner", shown, path=f)
    assert again["slack"]["webhook_url"].endswith("/T/B/x")
    # a damaged file behaves as empty
    f.write_text("{not json", encoding="utf-8")
    assert user_settings.load_settings("owner", path=f) == user_settings.default_settings()


def test_bad_quiet_and_http_webhook_are_dropped(tmp_path):
    f = tmp_path / "s.json"
    stored = user_settings.save_settings("x", {
        "notifications": {"quiet": [9, 9]},
        "slack": {"enabled": True, "webhook_url": "http://plain.example/hook", "quiet": [25, 3]},
    }, path=f)
    assert stored["notifications"]["quiet"] is None
    assert stored["slack"]["quiet"] is None
    assert stored["slack"]["webhook_url"] == ""


def test_bridge_people_only_lists_enabled_reachable(tmp_path):
    f = tmp_path / "s.json"
    user_settings.save_settings("on", {"slack": {"enabled": True, "slack_id": "U1", "quiet": [22, 7]}}, path=f)
    user_settings.save_settings("off", {"slack": {"enabled": False, "slack_id": "U2"}}, path=f)
    user_settings.save_settings("nowhere", {"slack": {"enabled": True}}, path=f)
    people = user_settings.bridge_people(path=f)
    assert list(people) == ["on"]
    assert people["on"] == {"slack_id": "U1", "webhook_url": None, "quiet": [22, 7]}


def test_bridge_merge_adds_and_updates_in_place(tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    monkeypatch.setenv("EDP8_UI_SETTINGS", str(f))
    people = {"owner": {"quiet": None}}
    assert slack_bridge._merge_people(people) == []
    user_settings.save_settings("owner", {"slack": {"enabled": True, "slack_id": "U9", "quiet": [22, 7]}}, path=f)
    user_settings.save_settings("ravi", {"slack": {"enabled": True, "webhook_url": "https://h/x"}}, path=f)
    owner_ref = people["owner"]
    assert slack_bridge._merge_people(people) == ["ravi"]
    assert people["owner"] is owner_ref and owner_ref["slack_id"] == "U9" and owner_ref["quiet"] == [22, 7]
    assert people["ravi"]["webhook_url"] == "https://h/x"


def test_settings_endpoint_is_human_only(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from edp8.board import Board
    from edp8.service import create_app
    from edp8.store import Store
    monkeypatch.setenv("EDP8_UI_SETTINGS", str(tmp_path / "s.json"))
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.setenv("EDP8_PUBLIC", "0")
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    (tmp_path / "tokens.json").write_text(json.dumps({"alice": "a", "bot": "b"}))
    app = create_app(Board(Store(":memory:")), admin_token="t")
    with TestClient(app) as c:
        assert c.post("/v1/participants", json={"id": "alice", "handle": "alice", "role": "owner", "type": "human"},
                      headers={"X-Admin": "t"}).status_code == 200
        assert c.post("/v1/participants", json={"id": "bot", "handle": "bot", "role": "engineer", "type": "agent"},
                      headers={"X-Admin": "t"}).status_code == 200
        h = {"X-Participant": "alice", "X-Token": "a"}
        assert c.get("/v1/me/settings").status_code == 401
        r = c.get("/v1/me/settings", headers=h)
        assert r.status_code == 200 and r.json()["value"]["slack"]["enabled"] is False
        r = c.put("/v1/me/settings", headers=h, json={"slack": {"enabled": True, "slack_id": "U1",
                                                                "webhook_url": "https://hooks.slack.com/services/a/b/c"}})
        assert r.status_code == 200
        v = r.json()["value"]
        assert v["slack"]["webhook_set"] is True and "/a/b/c" not in json.dumps(v)
        assert r.headers["cache-control"] == "private, no-store"
        assert c.get("/v1/me/settings", headers={"X-Participant": "bot", "X-Token": "b"}).status_code == 403
        # the secret went to disk, keyed by handle, for the bridge
        assert user_settings.bridge_people(tmp_path / "s.json")["alice"]["webhook_url"].endswith("/a/b/c")
