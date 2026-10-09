"""S10 (s-b431082892): ci.yml's `security` job runs bandit, semgrep and pip-audit on ubuntu only, with pinned
tools and actions, no schedule trigger, and its scanner configs exist and parse."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
JOB = CI["jobs"]["security"]
RUN = "\n".join(s.get("run", "") for s in JOB["steps"])


def test_job_is_ubuntu_only_and_bounded():
    assert JOB["runs-on"] == "ubuntu-latest"
    assert "strategy" not in JOB
    assert JOB["timeout-minutes"] <= 15


def test_job_runs_the_three_scanners_with_pinned_versions():
    assert re.search(r"--from bandit==\d+\.\d+\.\d+ bandit .*-ll", RUN)
    assert re.search(r"--from semgrep==\d+\.\d+\.\d+ semgrep scan .*--error", RUN)
    assert re.search(r"--from pip-audit==\d+\.\d+\.\d+ pip-audit .*--strict", RUN)
    for pkg in ("v8/src", "edp-pool/src", "edp-broker/src", "edp-contracts/src"):
        assert pkg in RUN


def test_no_schedule_trigger_and_no_new_workflow():
    on = CI.get("on", CI.get(True))
    assert "schedule" not in on
    assert sorted(p.name for p in (ROOT / ".github" / "workflows").glob("security*")) == []


def test_every_action_is_pinned_by_sha_and_the_uv_cache_is_on():
    for step in JOB["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
    uv = next(s for s in JOB["steps"] if s.get("uses", "").startswith("astral-sh/setup-uv@"))
    assert uv["with"]["enable-cache"] is True


def test_scan_steps_all_run_even_after_one_fails():
    steps = [s for s in JOB["steps"] if "run" in s]
    assert all("cancelled" in s.get("if", "") for s in steps[1:])


def test_scanner_configs_exist_and_parse():
    sec = ROOT / ".github" / "security"
    cfg = yaml.safe_load((sec / "bandit.yaml").read_text(encoding="utf-8"))
    assert "tests" in cfg["exclude_dirs"] and set(cfg["skips"]) <= {"B104", "B608"}
    rules = yaml.safe_load((sec / "semgrep-rules.yml").read_text(encoding="utf-8"))["rules"]
    assert rules and all(r["languages"] == ["python"] and r["severity"] == "ERROR" and r["message"] for r in rules)
    assert len({r["id"] for r in rules}) == len(rules)
    ignore = (sec / "pip-audit-ignore.txt").read_text(encoding="utf-8").splitlines()
    for line in ignore:
        if line.strip() and not line.lstrip().startswith("#"):
            assert "#" in line, f"a pip-audit ignore needs a reason: {line!r}"


def test_every_baselined_nosec_has_a_reason():
    bad = []
    for pkg in ("v8/src", "edp-pool/src", "edp-broker/src", "edp-contracts/src"):
        for f in (ROOT / pkg).rglob("*.py"):
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = re.search(r"#\s*nosec\b([^#]*)#(.*)$", line)
                if "nosec" in line and not (m and re.search(r"B\d{3}", m.group(1)) and m.group(2).strip()):
                    bad.append(f"{f.relative_to(ROOT)}:{n}")
    assert not bad, bad


def test_security_inputs_script_drops_the_edp_siblings(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    import runpy
    import sys
    monkeypatch.setattr(sys, "argv", ["security_inputs.py", str(tmp_path)])
    runpy.run_path(str(ROOT / ".github" / "scripts" / "security_inputs.py"), run_name="__main__")
    pool = (tmp_path / "edp-pool.in").read_text(encoding="utf-8")
    assert pool.strip() and "edp-contracts" not in pool
    deps = tomllib.loads((ROOT / "edp-pool" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert len(pool.splitlines()) == len([d for d in deps if not d.startswith("edp-")])
