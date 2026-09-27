"""S21 c-746933569b (owner AV ruling m-631a9ad2a7): the installed app never launches uv at runtime, except the
detached update helper. Unsigned exe -> uv -> python is the chain behaviour-based AV flags.

One test per call site that used to spawn uv from the app's own process tree, plus a grep that the only uv argv
the runtime source still builds is the helper's (updater) and the pool's dev-checkout branch."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from edp_contracts import prereqs
from edp8 import settings, update_helper, updater

ROOT = Path(__file__).resolve().parents[2]
UV_NAMES = ("uv", "uv.exe", "uvx", "uvx.exe")


def _is_uv(arg: str) -> bool:
    return re.split(r"[\\/]", str(arg))[-1].lower() in UV_NAMES


def test_update_compat_check_runs_uv_only_in_the_detached_helper(monkeypatch, tmp_path):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(updater, "_uv", lambda: "C:/tools/uv.exe")
    monkeypatch.setattr(settings, "run_dir", lambda: tmp_path / "run")
    wheels = {w: tmp_path / f"{w}-99.0.0-py3-none-any.whl" for w in updater.WHEELS}
    in_app: list[list[str]] = []   # what this process starts (detach's intermediate included)
    in_helper: list[list[str]] = []
    rows = [{"workflow": "standard", "version": 1, "ok": True, "errors": []}]

    def fake_detach(argv, **kw):
        in_app.append(list(argv))
        assert argv[2] == "--compat"

        def helper_run(a, **k):
            in_helper.append(list(a))
            return subprocess.CompletedProcess(a, 0, json.dumps(rows), "")
        monkeypatch.setattr(update_helper.subprocess, "run", helper_run)
        update_helper.compat(argv[3])   # the helper's own code, as the detached process runs it

    import edp_contracts.proc as proc
    monkeypatch.setattr(proc, "detach", fake_detach)
    assert not hasattr(updater, "subprocess")  # the updater starts nothing itself; detach is its only launch

    rc, got, err = updater.compat_check(wheels, tmp_path / "edp8.db")
    assert (rc, got, err) == (0, rows, "")
    assert in_app and not any(_is_uv(a) for argv in in_app for a in argv), in_app
    assert in_helper and _is_uv(in_helper[0][0]) and in_helper[0][1:3] == ["tool", "run"]


def test_update_compat_helper_reports_on_every_path(tmp_path):
    out = tmp_path / "compat.json"
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"compat_argv": [str(tmp_path / "no-such-uv.exe")], "compat_out": str(out)}))
    assert update_helper.compat(str(plan)) == 0
    got = json.loads(out.read_text())
    assert got["rc"] == 2 and "could not run" in got["stderr"]


def test_embedder_install_uses_the_apps_own_python_not_uv(monkeypatch):
    monkeypatch.setattr(prereqs, "in_bundle", lambda: False)
    emb = prereqs.by_name("embedder")
    assert "uv" not in emb.needs
    for os_key in prereqs.OSES:
        # no tool on PATH at all, uv included: the recipe still resolves (pip or ensurepip is stdlib-side)
        r = prereqs.pick_recipe(emb, os_key, which=lambda p: None)
        assert r is not None and r.manager == "pip", (os_key, r)
        argv = prereqs.recipe_argv(r, which=lambda p: None, os_key=os_key)
        assert argv[0] == sys.executable and not any(_is_uv(a) for a in argv), argv
        compile(argv[2], "<pip boot>", "exec")
    assert "uv" not in prereqs.describe_recipe(emb, r)


def test_the_only_runtime_uv_argv_is_the_helpers_and_the_pools_dev_branch():
    """Grep: no runtime source builds a uv argv except updater.py (handed to the detached helper, never run
    in-process) and edp-pool service.py's dev-mode branch."""
    pat = re.compile(r'''\[\s*"uv"\s*,|find_tool\(\s*"uv"\s*\)|_find\(\s*which\s*,\s*"uv"\s*\)|"uv"\s*,\s*"(run|pip|tool)"''')
    hits = {}
    for src in ("v8/src", "edp-pool/src", "edp-contracts/src", "edp-broker/src"):
        for f in (ROOT / src).rglob("*.py"):
            n = sum(1 for line in f.read_text(encoding="utf-8").splitlines() if pat.search(line))
            if n:
                hits[f.relative_to(ROOT).as_posix()] = n
    assert hits == {"v8/src/edp8/updater.py": 1, "edp-pool/src/edp_pool/service.py": 1}, hits
    assert "if edp_settings.dev_mode():" in (ROOT / "edp-pool/src/edp_pool/service.py").read_text(encoding="utf-8")
