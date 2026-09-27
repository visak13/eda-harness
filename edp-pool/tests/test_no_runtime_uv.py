"""S21 c-746933569b (owner AV ruling m-631a9ad2a7): an installed pool never launches uv. The neuron driver and
recipe_ctl run on the pool's own interpreter; `uv run --project` stays for source checkouts (dev mode) only."""

import subprocess
import sys

import edp_pool.service as service_mod


class _Proc:
    pid = 4242
    stdout = '{"ok": true}\n'
    returncode = 0


def _spy(monkeypatch, tmp_path, dev: bool) -> list[list[str]]:
    seen: list[list[str]] = []
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("EDP_POOL_DIR", str(tmp_path / "pool"))
    monkeypatch.setattr(service_mod.edp_settings, "dev_mode", lambda: dev)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: seen.append(list(argv)) or _Proc())
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: seen.append(list(argv)) or _Proc())
    return seen


def _no_uv(argv: list[str]) -> bool:
    return not any(a.lower().rsplit("\\", 1)[-1].rsplit("/", 1)[-1] in ("uv", "uv.exe", "uvx", "uvx.exe")
                   for a in argv)


def test_installed_pool_runs_the_neuron_driver_and_recipe_ctl_without_uv(monkeypatch, tmp_path):
    seen = _spy(monkeypatch, tmp_path, dev=False)
    assert service_mod.spawn_neuron_driver("r-1", "echo hi", 60.0, None) == 4242
    assert service_mod.run_recipe_ctl("suspend", "r-1") == {"ok": True}
    assert len(seen) == 2 and all(_no_uv(a) for a in seen), seen
    assert [a[0] for a in seen] == [sys.executable, sys.executable]
    assert seen[0][1].endswith("neuron_heartbeat.py") and seen[1][-2:] == ["suspend", "r-1"]


def test_a_source_checkout_keeps_uv_run_for_the_dev_env(monkeypatch, tmp_path):
    seen = _spy(monkeypatch, tmp_path, dev=True)
    service_mod.spawn_neuron_driver("r-1", "echo hi", 60.0, "http://127.0.0.1:1")
    service_mod.run_recipe_ctl("resume", "r-1")
    assert [a[:2] for a in seen] == [["uv", "run"], ["uv", "run"]]
