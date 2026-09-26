"""S6 first-run wizard record (design §4.8 Onboarding): `heronry start` opens /ui/setup with a one-time
sign-in code for the init human until the wizard posts /v1/admin/setup/done; redeeming that code signs the
admin in WITHOUT rotating the token already in use (a teammate invite still mints a fresh one)."""

from __future__ import annotations

from admin_support import ADMIN_H, BOB_H, OWNER_TOKEN, make_env
from edp8 import cli
from edp8.admin import setup_api


def test_setup_state_done_and_admin_only(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    assert env.client.get("/v1/admin/setup", headers=ADMIN_H).json()["value"]["done"] is False
    assert env.client.post("/v1/admin/setup/done", headers=BOB_H).status_code == 403
    r = env.client.post("/v1/admin/setup/done", headers=ADMIN_H)
    assert r.status_code == 200 and r.json()["value"]["by"] == "owner"
    assert env.client.get("/v1/admin/setup", headers=ADMIN_H).json()["value"]["done"] is True
    assert setup_api.setup_path().is_file()


def test_setup_code_signs_in_without_rotating_the_owner_token(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    code = setup_api.issue_setup_code()
    r = env.client.post("/v1/join", json={"code": code})
    assert r.status_code == 200, r.text
    v = r.json()["value"]
    assert v["handle"] == "owner" and v["token"] == OWNER_TOKEN
    assert env.tokens_data()["owner"] == OWNER_TOKEN
    # once only
    assert env.client.post("/v1/join", json={"code": code}).status_code == 401


def test_start_opens_setup_until_done(tmp_path, monkeypatch, capsys):
    make_env(tmp_path, monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    cli._first_run_setup(open_browser=True)
    out = capsys.readouterr().out
    assert "/ui/setup?code=" in out and opened and "/ui/setup?code=" in opened[0]
    setup_api.mark_done("owner")
    opened.clear()
    cli._first_run_setup(open_browser=True)
    assert opened == [] and "/ui/setup" not in capsys.readouterr().out
