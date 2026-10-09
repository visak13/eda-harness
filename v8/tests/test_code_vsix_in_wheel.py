"""An installed Heronry installs and updates EDP Chat (the edp-code extension) in its code-server.

Before 0.10.5 only a source checkout did: code_service._vendor_dir read <home>/vscode-ext, which an installed
wheel has no home for, so `heronry start code` skipped every pinned extension and never installed the vsix.
The wheel now carries the pin list, its sha256 lock and the vsix as edp8/vscode_ext (pyproject force-include
plus hatch_build.py), and _vendor_dir falls back to that package data.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from edp8 import code_service

V8 = Path(__file__).resolve().parents[1]


def _vendor(d: Path, vsix: bool = True) -> Path:
    (d / "edp-code").mkdir(parents=True)
    (d / "extensions.txt").write_text("a.b@1.0.0\n", encoding="utf-8")
    (d / "extensions.lock.json").write_text('{"extensions": {}}', encoding="utf-8")
    if vsix:
        (d / "edp-code" / "edp-code.vsix").write_bytes(b"PK")
    return d


def test_an_installed_wheel_reads_its_packaged_extension_list(tmp_path, monkeypatch):
    pkg = _vendor(tmp_path / "site" / "edp8" / "vscode_ext")
    monkeypatch.setattr(code_service.settings, "home", lambda: None)
    monkeypatch.setattr(code_service, "__file__", str(pkg.parent / "code_service.py"))
    assert code_service._vendor_dir() == pkg


def test_a_checkout_prefers_its_own_vscode_ext(tmp_path, monkeypatch):
    home = tmp_path / "v8"
    own = _vendor(home / "vscode-ext")
    _vendor(tmp_path / "site" / "edp8" / "vscode_ext")
    monkeypatch.setattr(code_service.settings, "home", lambda: home)
    monkeypatch.setattr(code_service, "__file__", str(tmp_path / "site" / "edp8" / "code_service.py"))
    assert code_service._vendor_dir() == own


def test_no_list_anywhere_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(code_service.settings, "home", lambda: None)
    monkeypatch.setattr(code_service, "__file__", str(tmp_path / "edp8" / "code_service.py"))
    assert code_service._vendor_dir() is None


def test_the_wheel_and_sdist_carry_the_list_and_the_vsix():
    cfg = tomllib.loads((V8 / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["hatch"]["build"]["targets"]
    fi = cfg["wheel"]["force-include"]
    assert fi["vscode-ext/extensions.txt"] == "edp8/vscode_ext/extensions.txt"
    assert fi["vscode-ext/extensions.lock.json"] == "edp8/vscode_ext/extensions.lock.json"
    for f in ("vscode-ext/extensions.txt", "vscode-ext/extensions.lock.json", "vscode-ext/edp-code/edp-code.vsix"):
        assert f in cfg["sdist"]["only-include"]
    assert "vscode-ext/edp-code/edp-code.vsix" in cfg["sdist"]["artifacts"]  # gitignored, so an artifact


@pytest.fixture
def hook(monkeypatch):
    try:
        import hatchling.builders.hooks.plugin.interface  # noqa: F401
    except ImportError:  # the test venv has no hatchling: the hook only subclasses its interface
        iface = ModuleType("hatchling.builders.hooks.plugin.interface")
        iface.BuildHookInterface = object
        monkeypatch.setitem(sys.modules, "hatchling.builders.hooks.plugin.interface", iface)
        for name in ("hatchling", "hatchling.builders", "hatchling.builders.hooks", "hatchling.builders.hooks.plugin"):
            monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.syspath_prepend(str(V8))
    sys.modules.pop("hatch_build", None)
    import hatch_build
    warned: list[str] = []
    return hatch_build.WebBundleFreshness._include_vsix, SimpleNamespace(
        app=SimpleNamespace(display_warning=warned.append)), warned


def test_the_build_hook_adds_the_vsix(tmp_path, hook):
    include, self_, _ = hook
    _vendor(tmp_path / "vscode-ext")
    data: dict = {"force_include": {}}
    include(self_, tmp_path, data)
    assert data["force_include"] == {
        str(tmp_path / "vscode-ext" / "edp-code" / "edp-code.vsix"): "edp8/vscode_ext/edp-code/edp-code.vsix"}


def test_a_release_build_without_the_vsix_fails(tmp_path, hook, monkeypatch):
    include, self_, warned = hook
    _vendor(tmp_path / "vscode-ext", vsix=False)
    data: dict = {"force_include": {}}
    monkeypatch.delenv("EDP8_REQUIRE_VSIX", raising=False)
    include(self_, tmp_path, data)
    assert data["force_include"] == {} and "EDP Chat" in warned[0]
    monkeypatch.setenv("EDP8_REQUIRE_VSIX", "1")
    with pytest.raises(RuntimeError, match="EDP Chat extension is missing"):
        include(self_, tmp_path, data)


def test_the_release_workflows_package_the_vsix_before_the_wheel():
    root = V8.parent / ".github" / "workflows"
    for name in ("installers.yml", "release.yml"):
        text = (root / name).read_text(encoding="utf-8")
        pkg = text.index("npm --prefix vscode-ext/edp-code run package")
        build = text.index("uv build")
        assert pkg < build and 'EDP8_REQUIRE_VSIX: "1"' in text, name
