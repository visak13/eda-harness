"""t-08612be1b0: one prerequisites manifest; detection and install plans over a fake PATH and fake versions."""

from __future__ import annotations

from pathlib import Path

import pytest

from edp_contracts import prereqs
from edp_contracts.prereqs import (
    MANIFEST,
    Recipe,
    by_name,
    detect,
    detect_all,
    parse_version,
    plan,
    run_steps,
)

VERSIONS = {
    "uv": "uv 0.9.11 (8d8aabb88 2025-11-20)",
    "git": "git version 2.47.1.windows.2",
    "node": "v22.11.0",
    "claude": "2.0.14 (Claude Code)",
    "codex": "codex-cli 0.46.0",
    "tailscale": "1.76.1\n  tailscale commit: x",
    "npm": "10.9.0",
    "winget": "v1.9.25200",
    "brew": "Homebrew 4.4.0",
    "curl": "curl 8.10",
}


def fake(present: set[str], versions: dict[str, str] | None = None):
    """(which, probe) over a PATH holding exactly `present`, answering `versions` (default VERSIONS)."""
    vs = {**VERSIONS, **(versions or {})}

    def which(p):
        name = p.command or p.name
        return f"/fake/bin/{name}" if name in present else None

    def probe(argv):
        name = Path(argv[0]).name
        return vs.get(name)

    return which, probe


@pytest.fixture(autouse=True)
def _no_python_side(monkeypatch):
    """The python/model rows read the real interpreter; pin them so tests see one machine."""
    monkeypatch.setattr(prereqs.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(prereqs, "_model_cached", lambda model, cache: None)


def rows(present, versions=None, os_key="win32", embed=True):
    which, probe = fake(present, versions)
    return detect_all(which=which, probe=probe, os_key=os_key, embed=embed), which


def test_manifest_is_complete_and_well_formed():
    names = [p.name for p in MANIFEST]
    assert len(names) == len(set(names))
    for want in (
        "uv",
        "git",
        "node",
        "claude",
        "codex",
        "pi",
        "tailscale",
        "embedder",
        "embedding model",
    ):
        assert want in names
    for p in MANIFEST:
        assert p.need in ("required", "harness", "optional", "default"), p.name
        assert p.purpose and p.docs, p.name
        assert set(p.install) == set(prereqs.OSES), (
            f"{p.name} lacks a recipe for some OS"
        )
        for d in p.needs:
            by_name(d)
        if p.need in ("optional", "default"):
            assert p.feature, f"optional {p.name} must say what it unlocks"
    assert {h.name for h in MANIFEST if h.need == "harness"} == {"claude", "codex"}
    assert prereqs.HARNESS_DEFAULT == "claude"
    assert any(n == "docker" for n, _ in prereqs.NOT_NEEDED)
    assert any(n == "sqlite" for n, _ in prereqs.BUNDLED)


@pytest.mark.parametrize(
    "text,want",
    [
        ("git version 2.47.1.windows.2", (2, 47, 1)),
        ("v22.11.0", (22, 11, 0)),
        ("codex-cli 0.46.0", (0, 46, 0)),
        ("2.0.14 (Claude Code)", (2, 0, 14)),
        ("1.76", (1, 76)),
        ("v20", (20,)),
        ("no digits", None),
    ],
)
def test_parse_version(text, want):
    assert parse_version(text) == want


def test_everything_present_is_ok():
    got, _ = rows(
        {"uv", "git", "node", "claude", "codex", "pi", "tailscale", "winget", "npm"}
    )
    by = {r.name: r for r in got}
    assert (
        by["git"].state == "ok" and by["git"].version == "git version 2.47.1.windows.2"
    )
    assert (
        by["pi"].state == "ok" and by["pi"].version is None
    )  # presence only, never probed
    assert by["tailscale"].state == "ok"
    assert (
        by["embedder"].state == "missing"
    )  # pinned off by the fixture; default-on, so missing not off


def test_missing_required_names_the_winget_fix():
    got, _ = rows({"uv", "node", "claude", "winget"})
    git = next(r for r in got if r.name == "git")
    assert git.state == "missing" and git.installable
    assert "winget" in git.fix and "Git.Git" in git.fix


def test_old_version_is_outdated_and_silent_cli_is_flagged():
    got, _ = rows(
        {"uv", "git", "node", "claude", "winget"}, {"node": "v18.19.0", "git": ""}
    )
    by = {r.name: r for r in got}
    assert by["node"].state == "outdated" and "older than 20" in by["node"].fix
    assert by["git"].state == "outdated"  # answers nothing parseable


def test_optional_missing_is_off_with_its_feature():
    got, _ = rows({"uv", "git", "node", "claude", "winget"})
    ts = next(r for r in got if r.name == "tailscale")
    assert ts.state == "off" and "remote access" in ts.feature


def test_no_embed_turns_the_embedder_off():
    got, _ = rows({"uv", "git", "node", "claude"}, embed=False)
    assert {r.name: r.state for r in got}["embedder"] == "off"


def test_setting_path_is_used(monkeypatch, tmp_path):
    """find_tool's setting wins: EDP_GIT_BIN points at a git outside PATH."""
    monkeypatch.setenv("EDP_GIT_BIN", str(tmp_path / "git.exe"))
    monkeypatch.setenv("PATH", "")
    st = detect(by_name("git"), probe=lambda argv: "git version 2.50.0", os_key="win32")
    assert st.state == "ok" and st.path == str(tmp_path / "git.exe")


def test_plan_installs_required_and_default_harness_in_order():
    got, which = rows({"uv", "winget", "npm"})
    steps, left = plan(got, os_key="win32", which=which, embed=False)
    names = [s.name for s in steps]
    assert names == [
        "git",
        "node",
        "claude",
    ]  # manifest order; claude because no harness is present
    git = steps[0]
    assert (
        git.argv[1:4] == ["install", "--id", "Git.Git"]
        and "--accept-package-agreements" in git.argv
    )
    assert steps[2].reason == "no seat harness is installed"
    assert not left


def test_plan_leaves_harness_alone_when_codex_is_present():
    got, which = rows({"uv", "git", "node", "codex", "winget", "npm"})
    steps, _ = plan(got, os_key="win32", which=which, embed=False)
    assert steps == []


def test_plan_optional_only_when_asked_and_deps_first():
    got, which = rows({"uv", "git", "claude", "winget", "npm"})  # node missing
    steps, _ = plan(got, os_key="win32", which=which, embed=False, only=["pi"])
    assert [s.name for s in steps] == ["node", "pi"]
    assert steps[1].argv[-3:] == ["install", "-g", "@earendil-works/pi-coding-agent"]


def test_plan_embed_default_installs_extra_and_model():
    got, which = rows({"uv", "git", "node", "claude", "winget"})
    steps, _ = plan(got, os_key="win32", which=which, embed=True)
    assert [s.name for s in steps] == ["embedder", "embedding model"]
    # the app's own Python, never a uv child (owner AV ruling m-631a9ad2a7)
    assert steps[0].argv[:2] == [prereqs.sys.executable, "-c"] and steps[0].argv[3] == "fastembed>=0.3"
    assert steps[1].recipe.manager == "model" and steps[1].argv is None


def test_no_package_manager_leaves_a_manual_link():
    got, which = rows({"uv", "node", "claude"})  # no winget
    steps, left = plan(got, os_key="win32", which=which, embed=False)
    assert steps == []
    git = next(r for r in left if r.name == "git")
    assert not git.installable and "https://git-scm.com/downloads" in git.fix


def test_linux_apt_needs_root_or_sudo(monkeypatch):
    monkeypatch.setattr(prereqs, "_euid", lambda: 1000)
    got, which = rows({"uv", "node", "claude"}, os_key="linux")
    steps, left = plan(got, os_key="linux", which=which, embed=False)
    assert "git" in [r.name for r in left]  # apt-get without sudo is not usable
    got, which = rows({"uv", "node", "claude", "apt-get", "sudo"}, os_key="linux")
    steps, _ = plan(got, os_key="linux", which=which, embed=False)
    assert steps[0].argv[:4] == ["/fake/bin/sudo", "apt-get", "install", "-y"]


def test_macos_cask_and_script_recipes():
    got, which = rows({"uv", "git", "node", "brew", "curl"}, os_key="darwin")
    steps, _ = plan(got, os_key="darwin", which=which, embed=False)
    assert steps[0].argv == ["/fake/bin/brew", "install", "--cask", "claude-code"]
    lx = prereqs.recipe_argv(
        Recipe("script", "https://claude.ai/install.sh"), os_key="linux"
    )
    assert lx == ["sh", "-c", "curl -fsSL https://claude.ai/install.sh | sh"]


def test_run_steps_skips_dependents_of_a_failure():
    got, which = rows({"uv", "git", "claude", "winget", "npm"})
    steps, _ = plan(got, os_key="win32", which=which, embed=False, only=["pi"])
    ran = []
    out = run_steps(steps, run=lambda argv: ran.append(argv) or 1, say=lambda s: None)
    assert out == {"node": 1, "pi": -1} and len(ran) == 1


def test_run_steps_model_step_uses_the_hook():
    s = prereqs.Step("embedding model", Recipe("model", ""), None, "semantic search")
    assert run_steps([s], model=lambda: Path("/m"), say=lambda _: None) == {
        "embedding model": 0
    }
    assert run_steps([s], model=lambda: None, say=lambda _: None) == {
        "embedding model": 1
    }


def test_model_cache_detection(tmp_path, monkeypatch):
    monkeypatch.undo()  # the real _model_cached
    d = tmp_path / "models--nomic-ai--nomic-embed-text-v1.5" / "snapshots" / "x"
    d.mkdir(parents=True)
    assert prereqs._model_cached("nomic-ai/nomic-embed-text-v1.5", tmp_path) is None
    (d / "model.onnx").write_bytes(b"")
    assert prereqs._model_cached("nomic-ai/nomic-embed-text-v1.5", tmp_path) is not None


def test_embed_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("EDP8_EMBED_CACHE", str(tmp_path))
    assert prereqs.embed_cache_dir() == tmp_path
    monkeypatch.delenv("EDP8_EMBED_CACHE")
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    monkeypatch.setattr(prereqs.settings, "dev_mode", lambda: False)
    monkeypatch.setattr(prereqs.settings, "data_dir", lambda: tmp_path / "data")
    assert prereqs.embed_cache_dir() == tmp_path / "data" / "models"


def test_markdown_table_covers_the_manifest():
    t = prereqs.markdown_table()
    for p in MANIFEST:
        assert f"`{p.name}`" in t
    assert "| docker |" in t and "| no |" in t and "| sqlite |" in t


def test_repo_readme_is_in_sync():
    readme = Path(__file__).resolve().parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert prereqs.readme_block() in text, (
        "run: python -m edp_contracts.prereqs --readme"
    )
