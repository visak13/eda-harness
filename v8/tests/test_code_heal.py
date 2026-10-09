"""qa 0.10.7 -> 0.10.8 (architect m-6136dd7f7c): the update helper that ran was the OLD version's, so the code-server it
left running kept serving the old EDP Chat. The NEW version's `heronry start` now compares what code-server serves
(extensions.json) with the vsix this install carries and restarts the code server once when they differ. And
`heronry update --help` prints usage instead of running a real update check. Private temp dirs only."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from edp8 import cli, code_service, launcher


def _vsix(vendor: Path, version: str) -> None:
    (vendor / "edp-code").mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(vendor / "edp-code" / "edp-code.vsix", "w") as z:
        z.writestr("extension/package.json", json.dumps({"name": "edp-code", "version": version}))


def _served(ext: Path, version: str | None) -> None:
    ext.mkdir(parents=True, exist_ok=True)
    rows = [{"identifier": {"id": "vscode.git"}, "version": "1.0.0"}]
    if version:
        rows.append({"identifier": {"id": "edp.edp-code"}, "version": version})
    (ext / "extensions.json").write_text(json.dumps(rows), encoding="utf-8")


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    vendor, ext = tmp_path / "vscode-ext", tmp_path / "extensions"
    monkeypatch.setattr(code_service, "_vendor_dir", lambda: vendor)
    monkeypatch.setattr(code_service, "ext_dir", lambda: ext)
    state = {"state": "up", "restarts": 0}
    monkeypatch.setattr(code_service, "status", lambda: {"state": state["state"]})

    def restart(**kw):
        state["restarts"] += 1
        return {"service": "code", "state": "restarted"}
    monkeypatch.setattr(code_service, "restart", restart)
    return vendor, ext, state


def test_a_code_server_serving_an_older_extension_is_restarted_once_onto_the_packaged_one(fake):
    vendor, ext, state = fake
    _vsix(vendor, "0.10.8")
    _served(ext, "0.10.7")
    got = code_service.heal_extension()
    assert got == {"service": "code", "state": "restarted", "from": "0.10.7", "to": "0.10.8"}
    assert state["restarts"] == 1


def test_a_code_server_with_no_edp_chat_at_all_is_refreshed_too(fake):
    vendor, ext, state = fake
    _vsix(vendor, "0.10.8")
    _served(ext, None)
    assert code_service.heal_extension()["from"] is None
    assert state["restarts"] == 1


def test_the_same_version_touches_nothing(fake):
    vendor, ext, state = fake
    _vsix(vendor, "0.10.8")
    _served(ext, "0.10.8")
    assert code_service.heal_extension() is None
    assert state["restarts"] == 0


def test_a_code_server_that_is_not_running_is_left_for_its_own_start(fake):
    vendor, ext, state = fake
    _vsix(vendor, "0.10.8")
    _served(ext, "0.10.7")
    state["state"] = "down"
    assert code_service.heal_extension() is None
    assert state["restarts"] == 0


def test_no_packaged_vsix_means_nothing_to_compare(fake):
    _vendor, ext, state = fake
    _served(ext, "0.10.7")
    assert code_service.heal_extension() is None
    assert state["restarts"] == 0


def test_start_says_one_line_and_restarts_only_the_code_server(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "update_block", lambda: None)
    monkeypatch.setattr(cli, "_via_control", lambda *a, **k: {"service": "board", "state": "started"})
    monkeypatch.setattr(launcher, "ensure_supervisor", lambda: {"service": "supervisor", "state": "started"})
    monkeypatch.setattr(code_service, "autostart", lambda: False)
    monkeypatch.setattr(cli, "_say", lambda out: None)
    monkeypatch.setattr(code_service, "heal_extension", lambda: {"state": "restarted", "from": "0.10.7", "to": "0.10.8"})
    assert cli.start(["all", "--no-update-check"]) in (0, 1)
    out = capsys.readouterr().out.strip().splitlines()
    assert [ln for ln in out if ln.startswith("code")] == [
        "code       EDP Chat 0.10.7 -> 0.10.8: restarted the code server so it serves the new one"]


def test_a_failed_refresh_is_said_and_never_fails_the_start(monkeypatch, capsys):
    def boom():
        raise code_service.CodeError("port busy")
    monkeypatch.setattr(code_service, "heal_extension", boom)
    cli._heal_code()
    assert "could not refresh EDP Chat (port busy)" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_update_help_prints_usage_and_touches_nothing(monkeypatch, capsys, flag):
    from edp8 import settings, updater

    def forbidden(*a, **k):
        raise AssertionError("update --help must not run an update check")
    monkeypatch.setattr(updater, "main", forbidden)
    monkeypatch.setattr(updater, "check", forbidden)
    monkeypatch.setattr(updater, "apply", forbidden)
    monkeypatch.setattr(settings, "home_guard", forbidden)
    monkeypatch.setitem(cli._COMMANDS, "update", forbidden)
    assert cli.main(["update", flag]) == 0
    out = capsys.readouterr().out
    assert "usage: " in out and "update" in out and "--check" in out and "--dry-run" in out
