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


class _Tty:
    def __init__(self, tty: bool):
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty

    def write(self, s):  # stdout stand-in
        return len(s)

    def flush(self):
        pass


def test_start_never_opens_a_browser_for_a_seat_a_test_or_the_fleet(tmp_path, monkeypatch):
    """m-98e4f2770f: test and seat `start`s opened /ui/setup tabs in the owner's own browser. A browser opens only
    for a person at a TTY with no seat identity, outside dev mode and without HERONRY_NO_BROWSER/--no-browser;
    otherwise the URL is only printed — asserted on start() itself with the opener monkeypatched."""
    make_env(tmp_path, monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    monkeypatch.setattr(cli, "_targets", lambda pos: ["board"])
    monkeypatch.setattr(cli, "_via_control", lambda *a: {"service": "board", "state": "already_running"})
    import edp8.launcher as launcher
    monkeypatch.setattr(launcher, "ensure_supervisor", lambda: {"service": "supervisor", "state": "already_running"})
    monkeypatch.setenv("HERONRY_NO_UPDATE_CHECK", "1")
    for k in ("EDP_HANDLE", "EDP8_PARTICIPANT", "HERONRY_NO_BROWSER"):
        monkeypatch.delenv(k, raising=False)
    import edp8.settings as st0
    monkeypatch.setattr(st0, "dev_mode", lambda: False)

    def run(stdin_tty=True, stdout_tty=True, argv=()):
        monkeypatch.setattr("sys.stdin", _Tty(stdin_tty))
        monkeypatch.setattr("sys.stdout", _Tty(stdout_tty))
        assert cli.start(list(argv)) == 0

    run(stdin_tty=False)                       # a test/script: stdin not a TTY
    run(stdout_tty=False)                      # output piped
    run(argv=["--no-browser"])
    monkeypatch.setenv("EDP_HANDLE", "engineer.s-x")   # a seat shell
    run()
    monkeypatch.delenv("EDP_HANDLE")
    monkeypatch.setenv("HERONRY_NO_BROWSER", "1")      # edp.ps1 / the test fixture
    run()
    monkeypatch.delenv("HERONRY_NO_BROWSER")
    import edp8.settings as st
    monkeypatch.setattr(st, "dev_mode", lambda: True)  # the fleet's source checkout
    run()
    assert opened == []
    monkeypatch.setattr(st, "dev_mode", lambda: False)  # a person at a terminal on an installed copy
    run()
    assert len(opened) == 1 and "/ui/setup?code=" in opened[0]


def test_whoami_says_who_is_an_admin(tmp_path, monkeypatch):
    """The SPA shows Admin only to admins: /v1/whoami carries the computed flag (init human or admin flag)."""
    env = make_env(tmp_path, monkeypatch)
    assert env.client.get("/v1/whoami", headers=ADMIN_H).json()["value"]["admin"] is True
    assert env.client.get("/v1/whoami", headers=BOB_H).json()["value"]["admin"] is False


def test_token_writes_keep_the_tokens_file_private(tmp_path, monkeypatch):
    """S6 walkthrough finding: an invite/revoke/rotate/agent mint rewrote tokens.json through a plain temp
    file, which inherited the directory's ACL; an installed board then refused its next start ("the tokens
    file is not private"). Every writer now keeps it owner-only."""
    import json

    from edp_contracts.settings import secrets as secret_files
    env = make_env(tmp_path, monkeypatch)
    data = env.tokens.read_text(encoding="utf-8")
    env.tokens.unlink()
    secret_files.write_secret(env.tokens, data)
    assert secret_files.problems(env.tokens) == []
    assert env.client.post("/v1/admin/teammates", headers=ADMIN_H, json={"handle": "carol"}).status_code == 200
    code = env.client.post("/v1/admin/teammates/carol/invite", headers=ADMIN_H).json()["value"]["code"]
    assert env.client.post("/v1/join", json={"code": code}).status_code == 200         # human token minted
    assert secret_files.problems(env.tokens) == []
    assert env.client.post("/v1/admin/teammates/carol/rotate", headers=ADMIN_H).status_code == 200
    assert env.client.post("/v1/admin/teammates/carol/revoke", headers=ADMIN_H).status_code == 200
    assert secret_files.problems(env.tokens) == []
    env.board._mint_token("eng.y")                                                      # agent mint at spawn
    assert secret_files.problems(env.tokens) == []
    assert "eng.y" in json.loads(env.tokens.read_text(encoding="utf-8"))["agents"]
    assert not list(tmp_path.glob("tokens.json*.tmp"))
