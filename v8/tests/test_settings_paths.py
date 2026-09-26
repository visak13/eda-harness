"""Dev mode keeps this host's paths (S1, criterion c-0dd1b51f61): with only EDP8_HOME=<repo>/v8 set, the
registry resolves the same db, tokens, run dir, data dir and agent homes the fleet launcher sets explicitly
today (v8/start.ps1: $DATA = <home>/.data, EDP8_DB = $DATA/edp8.db, $RUN = <home>/.run,
EDP_POOL_AGENT_HOME = <home>, EDP_BROKER_DATA = $DATA/broker-data; tokens at <home>/tokens.json)."""
from __future__ import annotations

from pathlib import Path

import pytest

from edp8 import settings

V8 = Path(__file__).resolve().parents[1]

#: What start.ps1 hands every service today, derived from its home the same way it does.
FLEET = {
    "EDP8_DB": V8 / ".data" / "edp8.db",
    "EDP8_TOKENS": V8 / "tokens.json",
    "EDP_POOL_AGENT_HOME": V8,
    "EDP_BROKER_DATA": V8 / ".data" / "broker-data",
}


def _clear_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset the app's own settings only: since S2 the registry also declares OS names (SystemRoot,
    COMSPEC, LOCALAPPDATA, ProgramFiles*), and without SystemRoot OpenSSL fails on Windows (m-3df6deb7ee)."""
    for s in settings.REGISTRY.values():
        for n in (s.env, *s.aliases):
            if n.upper().startswith(("EDP", "HERONRY")):
                monkeypatch.delenv(n, raising=False)


@pytest.fixture
def dev_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("EDP8_HOME", str(V8))


def test_dev_mode_is_detected_from_the_checkout(dev_only: None) -> None:
    assert settings.home() == V8 and settings.dev_mode()


def test_dev_mode_resolves_todays_fleet_paths(dev_only: None) -> None:
    assert settings.data_dir() == V8 / ".data"
    assert settings.run_dir() == V8 / ".run"
    assert settings.config_dir() == V8
    assert settings.agent_home() == V8
    for name, want in FLEET.items():
        assert Path(settings.get(name)) == want, name


def test_explicit_fleet_env_and_dev_defaults_agree(dev_only: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The live fleet sets these explicitly; dropping them changes nothing."""
    defaults = {n: Path(settings.get(n)) for n in FLEET}
    monkeypatch.setenv("EDP8_DATA", str(V8 / ".data"))
    monkeypatch.setenv("EDP8_RUN_DIR", str(V8 / ".run"))
    for n, v in FLEET.items():
        monkeypatch.setenv(n, str(v))
    assert {n: Path(settings.get(n)) for n in FLEET} == defaults
    assert settings.run_dir() == V8 / ".run" and settings.data_dir() == V8 / ".data"


def test_the_dev_admin_token_stays_legal_in_dev_mode(dev_only: None) -> None:
    assert settings.admin_token() == "dev"


def test_installed_mode_refuses_a_loose_tokens_file_and_the_dev_admin_token(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside dev mode the board refuses the 'dev' admin token and a tokens file others can read
    (design §4.2 secrets; strategyhl-86b4805322 §3). A private file created by write_secret boots."""
    import subprocess
    import sys

    from edp8.service import create_app
    from edp_contracts.settings import secrets

    _clear_app_env(monkeypatch)
    monkeypatch.setenv("EDP_HOME", str(tmp_path))
    monkeypatch.setenv("EDP8_UI", "legacy")

    def _app(name: str):
        monkeypatch.setenv("EDP8_DB", str(tmp_path / f"{name}.db"))
        return create_app()

    with pytest.raises(settings.SettingsError, match="refused"):
        _app("a")
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "not-dev")
    loose = tmp_path / "tokens.json"
    loose.write_text("{}", encoding="utf-8")
    if sys.platform == "win32":
        subprocess.run(["icacls", str(loose), "/grant", "*S-1-1-0:R"], capture_output=True, check=True)
    else:
        loose.chmod(0o644)
    with pytest.raises(RuntimeError, match="not private"):
        _app("b")
    loose.unlink()
    secrets.write_secret(loose, "{}")
    assert _app("c") is not None
