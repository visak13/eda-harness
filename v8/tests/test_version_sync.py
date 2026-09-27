"""S9: one version for the four packages, the desktop app, the web app and the VS Code extension. edp8.__version__
is the source constant the board, MCP and CLI report; every manifest must carry the same string."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

import edp8

V8 = Path(__file__).resolve().parents[1]
REPO = V8.parent
pytestmark = pytest.mark.skipif(not (REPO / "edp-pool" / "pyproject.toml").exists(), reason="needs the full repo")


def _pyproject(p: Path) -> str:
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return data["project"]["version"] if "project" in data else data["tool"]["briefcase"]["version"]


def _json_version(p: Path) -> str:
    return json.loads(p.read_text(encoding="utf-8"))["version"]


def _init(p: Path) -> str:
    return re.search(r'^__version__ = "([^"]+)"', p.read_text(encoding="utf-8"), re.M).group(1)


def test_every_manifest_carries_the_edp8_version():
    v = edp8.__version__
    found = {
        "v8/pyproject.toml": _pyproject(V8 / "pyproject.toml"),
        "v8/desktop/pyproject.toml": _pyproject(V8 / "desktop" / "pyproject.toml"),
        "v8/web/package.json": _json_version(V8 / "web" / "package.json"),
        "edp-code/package.json": _json_version(V8 / "vscode-ext" / "edp-code" / "package.json"),
        "edp-code heronry.release": json.loads((V8 / "vscode-ext" / "edp-code" / "package.json").read_text(encoding="utf-8"))
        ["heronry"]["release"],
    }
    for pkg, mod in (("edp-contracts", "edp_contracts"), ("edp-pool", "edp_pool"), ("edp-broker", "edp_broker")):
        found[f"{pkg}/pyproject.toml"] = _pyproject(REPO / pkg / "pyproject.toml")
        found[f"{mod}.__version__"] = _init(REPO / pkg / "src" / mod / "__init__.py")
    assert {k: x for k, x in found.items() if x != v} == {}, f"expected {v} everywhere"


def test_siblings_are_pinned_to_the_same_version():
    v = edp8.__version__
    text = "".join((V8 / p).read_text(encoding="utf-8") for p in ("pyproject.toml", "desktop/pyproject.toml"))
    pins = re.findall(r'"(edp8|edp-contracts|edp-pool|edp-broker)==([^"]+)"', text)
    assert pins and all(x == v for _, x in pins), pins


def test_the_board_and_cli_report_the_source_constant(monkeypatch):
    from edp8 import cli, run_state, updater
    assert cli._version_string().endswith(" " + edp8.__version__)
    assert updater.current_version() == edp8.__version__
    assert run_state._package_rev() == "v" + edp8.__version__
