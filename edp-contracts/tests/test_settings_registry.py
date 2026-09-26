"""The settings registry is the only env reader in the four packages' src/ trees (design §4.8, OCAK A1).

`scan()` walks edp8, edp-pool, edp-broker and edp-contracts `src/` with the AST and reports every raw
`os.environ` / `os.getenv` / `os.putenv` / `os.unsetenv` use (aliases of `os` and `from os import
environ` included) outside `edp_contracts/settings/`. The planted-read tests prove it fails.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from edp_contracts import settings
from edp_contracts.settings import _core

REPO = Path(__file__).resolve().parents[2]
SRC_TREES = [REPO / "v8" / "src", REPO / "edp-pool" / "src", REPO / "edp-broker" / "src",
             REPO / "edp-contracts" / "src"]
ALLOWED = REPO / "edp-contracts" / "src" / "edp_contracts" / "settings"
RAW = {"environ", "getenv", "putenv", "unsetenv", "environb", "getenvb"}
LOOKUPS = {"get", "env_raw", "is_set", "source", "setting"}


def raw_reads(path: Path) -> list[str]:
    """`file:line  code` for every raw env access in one Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    os_names = {"os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "os":
                    os_names.add(a.asname or "os")
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            if any(a.name in RAW for a in node.names):
                hits.append(node.lineno)
        elif (isinstance(node, ast.Attribute) and node.attr in RAW
              and isinstance(node.value, ast.Name) and node.value.id in os_names):
            hits.append(node.lineno)
    lines = path.read_text(encoding="utf-8").splitlines()
    return [f"{path}:{n}  {lines[n - 1].strip()}" for n in sorted(set(hits))]


def scan(trees: list[Path] = SRC_TREES, allowed: Path = ALLOWED) -> list[str]:
    out: list[str] = []
    for tree in trees:
        for py in sorted(tree.rglob("*.py")):
            if allowed in py.parents or "__pycache__" in py.parts:
                continue
            out.extend(raw_reads(py))
    return out


def _settings_aliases(tree: ast.AST) -> set[str]:
    """Names bound to the registry module in one file (`from edp8 import settings as S`, …)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("edp8", "edp_contracts"):
            out |= {a.asname or a.name for a in node.names if a.name == "settings"}
        elif isinstance(node, ast.Import):
            out |= {a.asname for a in node.names
                    if a.name in ("edp8.settings", "edp_contracts.settings") and a.asname}
    return out


def looked_up_names(trees: list[Path] = SRC_TREES) -> dict[str, list[str]]:
    """Every string-literal name passed to settings.get/env_raw/is_set/source/setting in src/."""
    found: dict[str, list[str]] = {}
    for tree in trees:
        for py in sorted(tree.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            tree_ = ast.parse(py.read_text(encoding="utf-8"))
            owners = _settings_aliases(tree_)
            for node in ast.walk(tree_):
                if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    continue
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else None
                owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
                if name in LOOKUPS and owner in owners:
                    found.setdefault(node.args[0].value, []).append(f"{py}:{node.lineno}")
    return found


def test_no_raw_env_read_outside_the_registry() -> None:
    hits = scan()
    assert hits == [], "raw env reads outside edp_contracts.settings:\n" + "\n".join(hits)


def test_every_looked_up_name_is_declared() -> None:
    missing = {n: w for n, w in looked_up_names().items() if n not in settings.REGISTRY}
    assert missing == {}, f"undeclared settings looked up: {missing}"


@pytest.mark.parametrize("code", [
    'import os\nx = os.environ.get("EDP8_PORT")\n',
    'import os\nx = os.getenv("EDP8_PORT")\n',
    'import os as _o\nx = _o.environ["EDP8_PORT"]\n',
    'from os import environ\nx = environ.get("EDP8_PORT")\n',
    'import os\nenv = dict(os.environ)\n',
])
def test_scanner_catches_a_planted_raw_read(tmp_path: Path, code: str) -> None:
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "planted.py").write_text(code, encoding="utf-8")
    assert len(scan([tmp_path / "src"], allowed=tmp_path / "nowhere")) == 1


def test_scanner_ignores_the_registry_itself(tmp_path: Path) -> None:
    allowed = tmp_path / "src" / "settings"
    allowed.mkdir(parents=True)
    (allowed / "core.py").write_text('import os\nx = os.environ.get("A")\n', encoding="utf-8")
    assert scan([tmp_path / "src"], allowed=allowed) == []


def test_every_declaration_is_complete() -> None:
    assert len(settings.REGISTRY) > 50
    for s in settings.all_settings():
        assert s.key and s.env and s.type in settings.TYPES, s
        assert s.group.strip() and s.doc.strip(), s
        assert isinstance(s.secret, bool) and isinstance(s.restart_required, str) and s.restart_required, s
        assert hasattr(s, "default"), s


def test_declaring_twice_is_refused() -> None:
    with pytest.raises(settings.SettingsError):
        settings.declare("paths.home", "EDP_HOME_DUP", "str", None, "Paths", "dup")
    with pytest.raises(settings.SettingsError):
        settings.get("EDP_NOT_A_SETTING")


# ---------------------------------------------------------------------------- resolution + dirs

@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for s in settings.REGISTRY.values():
        for n in (s.env, *s.aliases):
            monkeypatch.delenv(n, raising=False)
    _core._toml_cache.clear()
    return tmp_path


def test_env_beats_config_beats_default(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP_HOME", str(clean))
    assert settings.get("EDP_LOG_RETENTION_DAYS") == 14 and settings.source("EDP_LOG_RETENTION_DAYS") == "default"
    (clean / "config.toml").write_text("[logging]\nretention_days = 3\n", encoding="utf-8")
    assert settings.get("EDP_LOG_RETENTION_DAYS") == 3 and settings.source("EDP_LOG_RETENTION_DAYS") == "config"
    monkeypatch.setenv("EDP_LOG_RETENTION_DAYS", "7")
    assert settings.get("EDP_LOG_RETENTION_DAYS") == 7 and settings.source("EDP_LOG_RETENTION_DAYS") == "env"


def test_env_only_ignores_config(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP_HOME", str(clean))
    (clean / "config.toml").write_text('[seat]\nhandle = "x"\n', encoding="utf-8")
    assert settings.get("EDP_HANDLE") is None


def test_legacy_alias_edp8_home(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP8_HOME", str(clean))
    assert settings.home() == clean.resolve()
    assert settings.data_dir() == clean.resolve() / ".data"
    assert settings.run_dir() == clean.resolve() / ".run"
    assert settings.get("EDP8_DB") == clean.resolve() / ".data" / "edp8.db"
    assert settings.get("EDP8_TOKENS") == clean.resolve() / "tokens.json"


def test_no_home_uses_heronry_platformdirs_with_role_subfolders(clean: Path) -> None:
    import platformdirs
    pd = platformdirs.PlatformDirs("heronry", appauthor=False, roaming=False)
    assert settings.home() is None
    assert settings.config_dir() == Path(pd.user_config_dir) / "config"
    assert settings.secrets_dir() == settings.config_dir() / "secrets"
    assert settings.get("EDP8_TOKENS") == settings.secrets_dir() / "tokens.json"
    assert settings.data_dir() == Path(pd.user_data_dir) / "data"
    assert settings.run_dir() == Path(pd.user_state_dir) / "run"
    assert settings.agent_home() == settings.data_dir() / "agent-home"


def test_resolve_names_the_source(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP8_PORT", "9999")
    assert settings.resolve("EDP8_PORT") == (9999, "env")
    monkeypatch.delenv("EDP8_PORT")
    assert settings.resolve("EDP8_PORT") == (9400, "default")


def test_dev_mode_is_a_source_checkout(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP_HOME", str(clean))
    assert not settings.dev_mode()
    (clean / "pyproject.toml").write_text('[project]\nname = "edp8"\n', encoding="utf-8")
    (clean / "src" / "edp8").mkdir(parents=True)
    assert settings.dev_mode() and settings.agent_home() == clean.resolve()


def test_admin_token_dev_refused_outside_dev_mode(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP_HOME", str(clean))
    with pytest.raises(settings.SettingsError, match="refused"):
        settings.admin_token()
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "dev")
    with pytest.raises(settings.SettingsError):
        settings.admin_token()
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "s3cret")
    assert settings.admin_token() == "s3cret"
    monkeypatch.delenv("EDP8_ADMIN_TOKEN")
    monkeypatch.setenv("EDP_DEV", "1")
    assert settings.admin_token() == "dev"


def test_admin_token_from_config(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP_HOME", str(clean))
    (clean / "config.toml").write_text('[edp8]\nadmin_token = "fromfile"\n', encoding="utf-8")
    assert settings.admin_token() == "fromfile"
