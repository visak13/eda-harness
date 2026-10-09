"""owner m-314348ee1d: the edp-code extension defaulted to the board on :9400 while this install's board runs at
19400 (the port block moves). `heronry start code` now writes `edp.boardUrl` in code-server's user settings from
the running board; a remote board the user signed in to (a non-loopback URL) is kept."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edp8 import code_service


@pytest.fixture
def seed(tmp_path, monkeypatch):
    monkeypatch.setattr(code_service, "user_dir", lambda: tmp_path)
    monkeypatch.setattr(code_service, "_board_url", lambda: "http://127.0.0.1:19400")
    path = tmp_path / "User" / "settings.json"

    def run(existing: dict | None = None) -> dict:
        if existing is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(existing), encoding="utf-8")
        code_service._seed_settings([], {})
        return json.loads(path.read_text(encoding="utf-8"))

    return run


def test_a_fresh_profile_points_the_extension_at_the_running_board(seed):
    assert seed()["edp.boardUrl"] == "http://127.0.0.1:19400"


@pytest.mark.parametrize("stale", ["http://127.0.0.1:9400", "http://localhost:9400/", "", None])
def test_a_loopback_or_empty_value_follows_the_board_port(seed, stale):
    assert seed({"edp.boardUrl": stale, "editor.fontSize": 15}) == {**seed(), "editor.fontSize": 15}
    assert seed({"edp.boardUrl": stale})["edp.boardUrl"] == "http://127.0.0.1:19400"


def test_a_remote_board_the_user_signed_in_to_is_kept(seed):
    assert seed({"edp.boardUrl": "https://board.example.ts.net"})["edp.boardUrl"] == "https://board.example.ts.net"


# The extension declares edp.boardUrl `scope: machine`, and code-server ignores a machine-scoped key in
# User/settings.json: the panel fell back to :9400 and said "board unreachable" (architect m-7edf94ce8d).
MACHINE = "Machine"


def _machine(tmp_path) -> dict:
    return json.loads((tmp_path / MACHINE / "settings.json").read_text(encoding="utf-8"))


def test_seed_settings_writes_the_machine_file(seed, tmp_path):
    seed()
    assert _machine(tmp_path)["edp.boardUrl"] == "http://127.0.0.1:19400"


def test_the_machine_file_follows_the_board_port_and_keeps_other_keys(seed, tmp_path):
    (tmp_path / MACHINE).mkdir()
    (tmp_path / MACHINE / "settings.json").write_text(
        json.dumps({"edp.boardUrl": "http://127.0.0.1:9400", "edp.chat.commitWindow": {"count": 5, "days": 2}}),
        encoding="utf-8")
    seed()
    assert _machine(tmp_path) == {"edp.boardUrl": "http://127.0.0.1:19400",
                                  "edp.chat.commitWindow": {"count": 5, "days": 2}}


def test_a_remote_board_is_kept_in_the_machine_file_too(seed, tmp_path):
    seed({"edp.boardUrl": "https://board.example.ts.net"})
    assert _machine(tmp_path)["edp.boardUrl"] == "https://board.example.ts.net"
    seed()  # a re-seed from the now-remote Machine file does not take the remote board back
    assert _machine(tmp_path)["edp.boardUrl"] == "https://board.example.ts.net"


def test_every_machine_scoped_edp_setting_the_board_seeds_lands_in_the_machine_file(seed, tmp_path):
    pkg = json.loads((Path(__file__).resolve().parents[1] / "vscode-ext" / "edp-code" / "package.json")
                     .read_text(encoding="utf-8-sig"))
    props = pkg["contributes"]["configuration"]["properties"]
    machine_scoped = {k for k, v in props.items() if k.startswith("edp.") and v.get("scope") == "machine"}
    seeded = {k for k in seed() if k.startswith("edp.") and k in machine_scoped}
    assert "edp.boardUrl" in seeded
    assert seeded <= set(_machine(tmp_path)), f"seeded machine-scoped keys missing from Machine: {seeded}"


def test_the_extension_default_board_is_the_running_boards_port():
    root = Path(__file__).resolve().parents[1] / "vscode-ext" / "edp-code"
    pkg = json.loads((root / "package.json").read_text(encoding="utf-8-sig"))
    assert pkg["contributes"]["configuration"]["properties"]["edp.boardUrl"]["default"] == "http://127.0.0.1:19400"
    for src in ("auth.ts", "extension.ts"):
        text = (root / "src" / "vscode" / src).read_text(encoding="utf-8")
        assert "127.0.0.1:9400" not in text, f"{src} still falls back to :9400"
