"""S19 c-e8ce8bad0e: `heronry doctor --bundle` writes a redacted diagnostics zip.

The test plants a user-profile path, an email, a username and a token in the service logs, the pool logs
and the settings (config.toml plus tokens.json), then asserts none of them survive in any zip member, and
that every section the story names is present.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from edp8 import diagnostics, settings

USER = "plantuser"
EMAIL = "jane.planted@example.org"
TOKEN = "PlantedTok3n-9fQ2xLmZ7pVw4sRt8yUb"          # a minted-style token (tokens.json)
BARE_TOKEN = "Zq8Wv3Ln5Tr2Kp7Xs9Dy4Hb6Gm1Jc0Fa"      # never registered anywhere: only the shape catches it
WIN_PATH = rf"C:\Users\{USER}\projects\heronry\.data\edp8.db"
POSIX_PATH = f"/home/{USER}/projects/heronry/.data"
PLANTS = [USER, EMAIL, TOKEN, BARE_TOKEN, WIN_PATH, POSIX_PATH, "C:\\\\Users\\\\" + USER, f"/Users/{USER}/"]


@pytest.fixture
def planted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = Path(os.environ["EDP8_HOME"])
    monkeypatch.setenv("USERNAME", USER)
    monkeypatch.setenv("USER", USER)
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps({"owner": TOKEN, "agents": {"engineer.x": "AgentSecret-abc123XYZ"}}),
                      encoding="utf-8")
    monkeypatch.setenv("EDP8_TOKENS", str(tokens))
    logs = settings.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "board.log").write_text(
        "\n".join([
            "INFO boot ok",
            f"ERROR open failed: {WIN_PATH}",
            f"WARN request from {EMAIL} X-Token: {TOKEN}",
            f"DEBUG json {json.dumps({'path': WIN_PATH})}",
            f"INFO user {USER} home {POSIX_PATH} mac /Users/{USER}/Library",
            f"INFO header Authorization: Bearer {BARE_TOKEN}",
            f"INFO raw {BARE_TOKEN} end",
        ]) + "\n", encoding="utf-8")
    pool_logs = settings.data_dir() / "pool-logs"
    pool_logs.mkdir(parents=True, exist_ok=True)
    (pool_logs / "pool.log").write_text(f"spawn cwd={WIN_PATH} owner={EMAIL} token={TOKEN}\n", encoding="utf-8")
    # settings: a non-secret value carrying an email and a user path (config.toml is plain text)
    (home / "config.toml").write_text(
        f'[plane]\nurl = "https://plane.example.org/ws?who={EMAIL}"\n'
        f'[ui]\nsettings_file = "{WIN_PATH.replace(chr(92), "/")}"\n', encoding="utf-8")
    return home


def _members(zp: Path) -> dict[str, str]:
    with zipfile.ZipFile(zp) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def test_scrubber_removes_every_plant() -> None:
    s = diagnostics.Scrubber(secrets=[TOKEN], usernames=[USER], homes=[])
    text = "\n".join(PLANTS) + f"\nX-Token: {TOKEN}\nBearer {BARE_TOKEN}\n{json.dumps(WIN_PATH)}"
    out = s(text)
    for p in PLANTS:
        assert p not in out, p
    assert USER not in out.lower()
    # ordinary text survives: a hex hash, a word, a port
    keep = "git_rev 57dd4cf0a1b2c3d4e5f60718293a4b5c6d7e8f90 port 9400 board healthy"
    assert s(keep) == keep


def test_bundle_zip_has_every_section_and_no_plant(planted: Path, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostics, "versions", lambda: {"packages": {"edp8": "0.0"}, "planted": WIN_PATH,
                                                          "who": EMAIL})
    out, names = diagnostics.write_bundle(tmp_path / "out")
    assert out.is_file() and out.suffix == ".zip"
    members = _members(out)
    for need in ("versions.json", "settings.json", "services.json", "workflows.json", "logs/board.log",
                 "logs/pool-logs-pool.log"):
        assert need in members, sorted(members)
    for name, text in members.items():
        for p in PLANTS:
            assert p not in text, f"{p!r} survived in {name}"
        assert USER not in text.lower(), f"username survived in {name}"
    # the sections carry real content: masked settings listing, the Standard workflow, the log lines
    listing = json.loads(members["settings.json"])
    values = {r["key"]: r.get("value") for g in listing["groups"] for r in g["settings"]}
    assert values["plane.url"] == "https://plane.example.org/ws?who=<email>", values["plane.url"]
    assert "<user>" in str(values["ui.settings_file"])
    assert any(w.get("id") == "standard" for w in json.loads(members["workflows.json"])["workflows"])
    assert "ERROR open failed" in members["logs/board.log"] and "<user>" in members["logs/board.log"]


def test_cli_doctor_bundle_writes_the_zip(planted: Path, tmp_path: Path) -> None:
    """`heronry doctor --bundle PATH` end to end in a subprocess on the planted private home."""
    dest = tmp_path / "diag.zip"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-m", "edp8.cli", "doctor", "--bundle", str(dest)], env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert dest.is_file(), r.stdout
    assert str(dest) in r.stdout
    for name, text in _members(dest).items():
        for p in PLANTS:
            assert p not in text, f"{p!r} survived in {name}"
