"""S9 release.yml (adversary R2-E): the draft release carries install.ps1 and install.sh pinned to its own tag,
and the asset guard fails when either is missing. The two workflow steps run as written, under bash."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WF = REPO / ".github" / "workflows" / "release.yml"
def _working_bash() -> str | None:
    """The first bash that runs a command: on Windows `bash` can resolve to WSL's system32 stub (no distro: exit
    0x8007072c), which is no bash at all for this test."""
    for cand in (shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"):
        if not cand or not Path(cand).exists():
            continue
        try:
            r = subprocess.run([cand, "-c", "echo ok"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip() == "ok":
            return cand
    return None


BASH = _working_bash()
pytestmark = [
    pytest.mark.skipif(not WF.exists(), reason="the workflow lives at the repo root, not in an installed wheel"),
    pytest.mark.skipif(BASH is None, reason="needs bash"),
]


def _step(name: str) -> str:
    steps = yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["assets"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == name)


def _bash(script: str, cwd: Path, tag: str = "v0.9.0") -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-e", "-c", script], cwd=cwd, env={"TAG": tag, "PATH": os.environ.get("PATH", "")}, capture_output=True,
                          text=True)


def _full_set(assets: Path) -> None:
    for name in ("edp8-0.9.0-py3-none-any.whl", "edp_pool-0.9.0-py3-none-any.whl", "edp_broker-0.9.0-py3-none-any.whl",
                 "edp_contracts-0.9.0-py3-none-any.whl", "edp8-0.9.0.tar.gz", "edp_pool-0.9.0.tar.gz",
                 "edp_broker-0.9.0.tar.gz", "edp_contracts-0.9.0.tar.gz", "edp-code-0.9.0.vsix",
                 "Heronry Desktop-0.9.0.msi", "Heronry Desktop-0.9.0.dmg", "heronry_0.9.0-1~ubuntu-noble_amd64.deb"):
        (assets / name).write_bytes(b"x")


def test_install_scripts_are_attached_and_pinned_to_the_tag(tmp_path):
    for f in ("install.ps1", "install.sh"):
        shutil.copyfile(REPO / f, tmp_path / f)
    (tmp_path / "assets").mkdir()
    r = _bash(_step("The install scripts, pinned to this tag"), tmp_path, tag="v9.8.7")
    assert r.returncode == 0, r.stdout + r.stderr
    ps1 = (tmp_path / "assets" / "install.ps1").read_text(encoding="utf-8")
    sh = (tmp_path / "assets" / "install.sh").read_text(encoding="utf-8")
    assert '  [string]$Version = "v9.8.7",' in ps1 and '$Version = "",' not in ps1
    assert 'VERSION="v9.8.7"; RELEASE_URL=""' in sh and 'VERSION=""' not in sh
    # nothing else changed: the pin is one line in each
    for f, text in (("install.ps1", ps1), ("install.sh", sh)):
        orig = (REPO / f).read_text(encoding="utf-8").splitlines()
        assert sum(a != b for a, b in zip(orig, text.splitlines())) == 1 and len(orig) == len(text.splitlines())


def test_the_asset_guard_requires_both_install_scripts(tmp_path):
    guard = _step("Require the full asset set")
    _full_set(tmp_path)
    assert _bash(guard, tmp_path).returncode == 1  # the R2-E shape: everything but the scripts
    (tmp_path / "install.ps1").write_text("x")
    assert _bash(guard, tmp_path).returncode == 1
    (tmp_path / "install.sh").write_text("x")
    r = _bash(guard, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


# -- S10 (s-b431082892): Cut release. The dispatch path validates first, a dry run builds and publishes nothing ----

def _wf() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _needs(job: dict) -> list[str]:
    n = job.get("needs") or []
    return [n] if isinstance(n, str) else list(n)


def _closure(jobs: dict, name: str) -> set[str]:
    seen: set[str] = set()
    todo = _needs(jobs[name])
    while todo:
        j = todo.pop()
        if j not in seen:
            seen.add(j)
            todo += _needs(jobs[j])
    return seen


def test_dispatch_inputs_are_tag_dry_run_and_publish():
    inputs = _wf()[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"tag", "dry_run", "publish"}
    assert inputs["tag"]["required"] is True
    assert inputs["dry_run"]["type"] == "boolean" and inputs["dry_run"]["default"] is True
    assert inputs["publish"]["type"] == "boolean" and inputs["publish"]["default"] is False
    assert _wf()[True]["push"]["tags"] == ["v*"]  # a hand-pushed tag still builds a draft


def test_every_build_job_waits_for_prepare_and_is_skipped_by_a_dry_run():
    jobs = _wf()["jobs"]
    build = {"python-dist", "installers", "assets", "attest", "draft"}
    for name in build:
        assert "prepare" in _closure(jobs, name), name
    for name in ("python-dist", "installers"):  # the roots carry the gate; the rest follow through needs
        assert "needs.prepare.outputs.build == 'true'" in jobs[name]["if"], name
    for name in build - {"python-dist", "installers"}:
        assert _closure(jobs, name) & {"python-dist", "installers"}, name
        assert "if" not in jobs[name] or "always()" not in jobs[name]["if"], name


def test_only_the_gated_tag_step_creates_a_tag_and_only_publish_publishes():
    jobs = _wf()["jobs"]
    for name, job in jobs.items():
        for step in job.get("steps") or []:
            run = step.get("run", "")
            if "gh release edit" in run:
                assert name == "publish", name
            if "gh release create" in run:
                assert name == "draft", name
            if "git/refs" in run or "git push" in run or "git tag" in run:
                assert (name, step["name"]) == ("prepare", "Create the tag"), (name, step.get("name"))
                assert step["if"] == "${{ steps.plan.outputs.create_tag == 'true' }}"
    assert _closure(jobs, "publish") >= {"prepare", "draft"}
    assert jobs["publish"]["if"] == "${{ needs.prepare.outputs.publish == 'true' }}"


def test_write_permissions_are_minimal_per_job():
    wf = _wf()
    assert wf["permissions"] == {"contents": "read"}
    writers = {n for n, j in wf["jobs"].items() if (j.get("permissions") or {}).get("contents") == "write"}
    assert writers == {"prepare", "draft", "publish"}
    assert wf["jobs"]["attest"]["permissions"] == {"contents": "read", "id-token": "write", "attestations": "write"}


GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _repo(tmp_path: Path, version: str = "0.10.0", changelog: str = "## [0.10.0] - 2026\n", tagged: bool = False) -> Path:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(origin), str(work))
    (work / "v8" / "src" / "edp8").mkdir(parents=True)
    (work / "v8" / "src" / "edp8" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (work / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "x")
    _git(work, "push", "origin", "HEAD")
    if tagged:
        _git(work, "tag", "v0.10.0")
        _git(work, "push", "origin", "v0.10.0")
    return work


def _plan(work: Path, tmp_path: Path, tag="v0.10.0", event="workflow_dispatch", dry="true", publish="false"):
    step = next(s for s in _wf()["jobs"]["prepare"]["steps"] if s.get("name") == "Plan the run")
    out, summary = tmp_path / "out.txt", tmp_path / "summary.md"
    out.write_text("")
    summary.write_text("")
    env = {**os.environ, "TAG": tag, "EVENT": event, "DRY_RUN": dry, "PUBLISH": publish,
           "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)}
    r = subprocess.run([BASH, "-e", "-c", step["run"]], cwd=work, env=env, capture_output=True, text=True)
    vals = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return r, vals, summary.read_text()


def test_a_dry_run_validates_and_does_nothing(tmp_path):
    work = _repo(tmp_path)
    r, vals, summary = _plan(work, tmp_path, dry="true", publish="true")
    assert r.returncode == 0, r.stdout + r.stderr
    assert vals == {"build": "false", "create_tag": "false", "publish": "false"}
    assert "DRY RUN" in summary and "create the tag at this commit" in summary and "publish after the draft: true" in summary
    assert _git(work, "ls-remote", "--tags", "origin").strip() == ""  # nothing was tagged


def test_a_real_dispatch_tags_when_absent_builds_and_can_publish(tmp_path):
    work = _repo(tmp_path)
    r, vals, _ = _plan(work, tmp_path, dry="false", publish="true")
    assert r.returncode == 0, r.stdout + r.stderr
    assert vals == {"build": "true", "create_tag": "true", "publish": "true"}


def test_a_real_dispatch_on_an_existing_tag_does_not_tag_again(tmp_path):
    work = _repo(tmp_path, tagged=True)
    r, vals, _ = _plan(work, tmp_path, dry="false", publish="false")
    assert r.returncode == 0, r.stdout + r.stderr
    assert vals == {"build": "true", "create_tag": "false", "publish": "false"}


def test_a_tag_push_builds_a_draft_and_never_publishes(tmp_path):
    work = _repo(tmp_path, tagged=True)
    r, vals, _ = _plan(work, tmp_path, event="push", dry="", publish="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert vals == {"build": "true", "create_tag": "false", "publish": "false"}


@pytest.mark.parametrize("kw,tag,why", [
    ({"version": "0.9.9"}, "v0.10.0", "does not match edp8.__version__"),
    ({"changelog": "## [0.9.0]\n"}, "v0.10.0", "no '## [0.10.0]' section"),
    ({}, "0.10.0", "is not v<X.Y.Z>"),
    ({}, "latest", "is not v<X.Y.Z>"),
])
def test_a_bad_tag_stops_every_mode(tmp_path, kw, tag, why):
    work = _repo(tmp_path, **kw)
    for dry in ("true", "false"):
        r, vals, _ = _plan(work, tmp_path, tag=tag, dry=dry)
        assert r.returncode == 1 and why in r.stdout, (dry, r.stdout, r.stderr)
        assert vals.get("build") is None
