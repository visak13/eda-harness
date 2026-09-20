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
    # finding 17: the mask is scheme + host + last 4 of the path, no userinfo, no secret token
    assert shown["slack"]["webhook_url"] == "https://hooks.slack.com/…/B/x"
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


def test_concurrent_saves_lose_no_one(tmp_path):
    """Finding 12: two people saving at the same time must both survive — no PermissionError/500
    (the Windows atomic-replace race) and no dropped person (the read-merge-write race)."""
    import threading

    f = tmp_path / "ui-settings.json"
    handles = [f"p{i}" for i in range(24)]
    errors: list[Exception] = []
    barrier = threading.Barrier(len(handles))

    def save(h: str) -> None:
        try:
            barrier.wait()  # release every thread into the read-merge-write at once
            user_settings.save_settings(h, {"profile": {"display_name": h}}, path=f)
        except Exception as exc:  # noqa: BLE001 — a PermissionError here is the finding
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(h,)) for h in handles]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent saves raised: {errors!r}"
    on_disk = user_settings.load_all(f)
    assert set(on_disk) == set(handles)  # nobody was lost
    for h in handles:
        assert on_disk[h]["profile"]["display_name"] == h


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
    # "owner" is a static slack_map.json person — protected from a board opt-out (never removed).
    static = frozenset({"owner"})
    people = {"owner": {"quiet": None}}
    assert slack_bridge._merge_people(people, static)[0] == []
    user_settings.save_settings("owner", {"slack": {"enabled": True, "slack_id": "U9", "quiet": [22, 7]}}, path=f)
    user_settings.save_settings("ravi", {"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"}}, path=f)
    owner_ref = people["owner"]
    assert slack_bridge._merge_people(people, static)[0] == ["ravi"]
    assert people["owner"] is owner_ref and owner_ref["slack_id"] == "U9" and owner_ref["quiet"] == [22, 7]
    assert people["ravi"]["webhook_url"] == "https://hooks.slack.com/x"


def test_valid_webhook_allow_list_ip_and_userinfo(monkeypatch):
    monkeypatch.delenv("EDP8_SLACK_WEBHOOK_HOSTS", raising=False)
    assert user_settings.valid_webhook("https://hooks.slack.com/services/T/B/x")
    assert not user_settings.valid_webhook("https://evil.example/hook")        # external host (finding 10)
    assert not user_settings.valid_webhook("https://10.0.0.5/hook")            # private IP literal
    assert not user_settings.valid_webhook("https://169.254.169.254/latest")   # link-local IP
    assert not user_settings.valid_webhook("https://u:secret@hooks.slack.com/x")  # userinfo (finding 17)
    assert not user_settings.valid_webhook("http://hooks.slack.com/x")         # not https
    assert not user_settings.valid_webhook("https://hooks.slack.com/…/B/x")  # a masked echo
    monkeypatch.setenv("EDP8_SLACK_WEBHOOK_HOSTS", "hooks.example.com")
    assert user_settings.valid_webhook("https://hooks.example.com/x")          # operator allow-list


def test_save_rejects_disallowed_and_userinfo_webhooks(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP8_SLACK_WEBHOOK_HOSTS", raising=False)
    f = tmp_path / "s.json"
    for bad in ("https://evil.example/h", "https://10.0.0.5/h", "https://u:p@hooks.slack.com/h"):
        stored = user_settings.save_settings("x", {"slack": {"enabled": True, "webhook_url": bad}}, path=f)
        assert stored["slack"]["webhook_url"] == ""
    good = user_settings.save_settings("x", {"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/h"}}, path=f)
    assert good["slack"]["webhook_url"] == "https://hooks.slack.com/h"


def test_public_mask_hides_userinfo_and_token():
    shown = user_settings.public({"profile": {}, "notifications": {}, "slack": {
        "enabled": True, "slack_id": "", "webhook_url": "https://hooks.slack.com/services/T/B/secrettoken", "quiet": None}})
    masked = shown["slack"]["webhook_url"]
    assert "secrettoken" not in masked and "@" not in masked
    assert masked == "https://hooks.slack.com/…oken"


def test_slack_test_ping_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from edp8 import slack_bridge
    from edp8.board import Board
    from edp8.service import create_app
    from edp8.store import Store
    monkeypatch.setenv("EDP8_UI_SETTINGS", str(tmp_path / "s.json"))
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.setenv("EDP8_PUBLIC", "0")
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    (tmp_path / "tokens.json").write_text(json.dumps({"alice": "a", "bot": "b"}))
    sent = []
    monkeypatch.setattr(slack_bridge, "_post", lambda cfg, person, text: sent.append(person) or True)
    app = create_app(Board(Store(":memory:")), admin_token="t")
    with TestClient(app) as c:
        for pid, role, typ in (("alice", "owner", "human"), ("bot", "engineer", "agent")):
            assert c.post("/v1/participants", json={"id": pid, "handle": pid, "role": role, "type": typ},
                          headers={"X-Admin": "t"}).status_code == 200
        h = {"X-Participant": "alice", "X-Token": "a"}
        # not enabled yet -> 400, nothing sent
        assert c.post("/v1/me/settings/slack/test", headers=h).status_code == 400
        # enable with a valid webhook, then a test ping delivers using the STORED destination
        c.put("/v1/me/settings", headers=h, json={"slack": {"enabled": True, "slack_id": "U1",
              "webhook_url": "https://hooks.slack.com/services/a/b/c"}})
        # the client sends no webhook in the ping body; the masked value is never accepted or echoed
        r = c.post("/v1/me/settings/slack/test", headers=h)
        assert r.status_code == 200 and r.json()["value"]["delivered"] is True
        assert sent and sent[-1]["webhook_url"] == "https://hooks.slack.com/services/a/b/c"
        assert r.headers["cache-control"] == "private, no-store"
        # an agent seat has no Slack
        assert c.post("/v1/me/settings/slack/test", headers={"X-Participant": "bot", "X-Token": "b"}).status_code == 403


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
