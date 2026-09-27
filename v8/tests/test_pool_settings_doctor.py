"""Item 14 (qa m-96b136614b): `heronry doctor` reports a missing or unreadable pool settings.json, and `heronry
init` seeds it from edp_pool's shipped template, never over an existing file."""
import importlib.util
import json

import pytest

from edp8 import setup


def test_doctor_names_a_missing_an_unreadable_and_a_good_settings_file(tmp_path):
    assert "is missing" in setup.pool_settings_problem(tmp_path)
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert "is unreadable" in setup.pool_settings_problem(tmp_path)
    (tmp_path / "settings.json").write_text('{"outputStyle": "edp-terse"}', encoding="utf-8")
    assert setup.pool_settings_problem(tmp_path) is None


@pytest.mark.skipif(importlib.util.find_spec("edp_pool") is None, reason="edp_pool not installed in this env")
def test_init_seeds_the_template_then_keeps_an_edit(tmp_path):
    store = tmp_path / "claude-pool"
    assert "(written)" in setup.seed_pool_settings(tmp_path / "home", store)
    assert json.loads((store / "settings.json").read_text(encoding="utf-8"))["outputStyle"] == "edp-terse"
    (store / "settings.json").write_text("{}", encoding="utf-8")
    assert "(kept)" in setup.seed_pool_settings(tmp_path / "home", store)
    assert (store / "settings.json").read_text(encoding="utf-8") == "{}"


def test_init_without_the_pool_package_says_the_pool_seeds_it(tmp_path, monkeypatch):
    import builtins
    real = builtins.__import__

    def no_pool(name, *a, **k):
        if name.startswith("edp_pool"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_pool)
    line = setup.seed_pool_settings(tmp_path, tmp_path / "store")
    assert "the pool seeds it at start" in line and not (tmp_path / "store").exists()
