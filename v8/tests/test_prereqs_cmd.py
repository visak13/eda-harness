"""t-08612be1b0: `heronry prereqs [install]` — one question, then the package manager; fake PATH and versions."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from edp_contracts import prereqs as pq
from edp8 import prereqs_cmd

VERSIONS = {"uv": "uv 0.9.11", "git": "git version 2.47.1", "node": "v22.11.0", "claude": "2.0.14 (Claude Code)",
            "codex": "codex-cli 0.46.0", "tailscale": "1.76.1"}


class Machine:
    """A fake PATH: `present` tools answer VERSIONS; an install puts the tool on it."""

    def __init__(self, present: set[str]):
        self.present = set(present)
        self.ran: list[list[str]] = []

    def which(self, p):
        name = p.command or p.name
        return f"C:/fake/{name}.exe" if name in self.present else None

    def probe(self, argv):
        return VERSIONS.get(argv[0].rsplit("/", 1)[-1].removesuffix(".exe"))

    def rows(self, embed=True):
        return pq.detect_all(which=self.which, probe=self.probe, os_key="win32", embed=embed)

    def run(self, argv):
        self.ran.append(argv)
        pkg = argv[argv.index("--id") + 1]
        self.present.add({"Git.Git": "git", "OpenJS.NodeJS.LTS": "node", "Anthropic.ClaudeCode": "claude",
                          "Tailscale.Tailscale": "tailscale"}[pkg])
        return 0


@pytest.fixture
def machine(monkeypatch):
    m = Machine({"uv", "node", "claude", "winget", "npm"})  # git deliberately missing
    monkeypatch.setattr(prereqs_cmd, "rows", m.rows)
    monkeypatch.setattr(pq, "_which", m.which)
    monkeypatch.setattr(pq, "this_os", lambda: "win32")
    monkeypatch.setattr(pq.importlib.util, "find_spec", lambda name: SimpleNamespace(origin="C:/site/fastembed/__init__.py"))
    monkeypatch.setattr(pq.importlib.metadata, "version", lambda name: "0.8.0")
    monkeypatch.setattr(pq, "_model_cached", lambda model, cache: "C:/models/x")
    monkeypatch.setattr(pq, "refresh_path", lambda: None)
    real = pq.run_steps
    monkeypatch.setattr(pq, "run_steps", lambda steps, **kw: real(steps, run=m.run, say=lambda s: None))
    monkeypatch.setattr("edp8.admin.harnesses.signed_in", lambda h: True)
    return m


def test_asks_once_then_installs_the_missing_required_tool(machine, capsys):
    asked = []
    rc = prereqs_cmd.install({}, ask=lambda q: asked.append(q) or "y", isatty=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert asked == ["Install this now? [Y/n] "]
    assert "git              required: winget install --id Git.Git --exact" in out
    assert machine.ran and machine.ran[0][1:4] == ["install", "--id", "Git.Git"]
    assert "installed git: git version 2.47.1" in out
    assert "tailscale        turns on remote access for teammates" in out  # optional: listed, not installed


def test_no_means_nothing_installed(machine, capsys):
    rc = prereqs_cmd.install({}, ask=lambda q: "n", isatty=True)
    assert rc == 1 and machine.ran == []


def test_yes_skips_the_question(machine):
    rc = prereqs_cmd.install({"yes": True}, ask=lambda q: pytest.fail("asked"), isatty=False)
    assert rc == 0 and len(machine.ran) == 1


def test_no_input_without_yes_installs_nothing(machine, capsys):
    def eof(q):
        raise EOFError

    rc = prereqs_cmd.install({}, ask=eof, isatty=False)
    assert rc == 1 and machine.ran == []
    assert "no --yes; nothing installed" in capsys.readouterr().out


def test_piped_answer_must_say_yes(machine, capsys):
    assert prereqs_cmd.install({}, ask=lambda q: "", isatty=False) == 1 and machine.ran == []
    assert prereqs_cmd.install({}, ask=lambda q: "\ufeffn", isatty=False) == 1 and machine.ran == []
    machine.present.discard("git")
    assert prereqs_cmd.install({}, ask=lambda q: "\ufeffy\r", isatty=False) == 0 and len(machine.ran) == 1
    machine.present.discard("git")
    machine.ran.clear()
    assert prereqs_cmd.install({}, ask=lambda q: "y", isatty=False) == 0 and len(machine.ran) == 1


def test_only_installs_just_that_tool(machine):
    machine.present.add("git")
    rc = prereqs_cmd.install({"yes": True, "only": ["tailscale"]}, isatty=False)
    assert rc == 0 and [a[3] for a in machine.ran] == ["Tailscale.Tailscale"]


def test_failed_install_is_reported_and_exits_1(machine, capsys, monkeypatch):
    monkeypatch.setattr(pq, "run_steps", lambda steps, **kw: {s.name: 1 for s in steps})
    rc = prereqs_cmd.install({"yes": True}, isatty=False)
    out = capsys.readouterr().out
    assert rc == 1 and "FAILED    git" in out and "still missing: git" in out


def test_no_harness_installs_claude(machine, capsys):
    machine.present -= {"claude"}
    machine.present.add("git")
    rc = prereqs_cmd.install({"yes": True}, isatty=False)
    assert rc == 0 and machine.ran[0][3] == "Anthropic.ClaudeCode"
    assert "no seat harness is installed" in capsys.readouterr().out


def test_inside_heronry_desktop_uv_is_optional_and_nothing_pip_installs_into_the_app(machine, capsys, monkeypatch):
    monkeypatch.setattr(pq.sys, "executable", r"C:\Programs\Heronry Desktop\heronry.exe")
    assert pq.in_bundle()
    machine.present -= {"uv"}
    machine.present.add("git")
    monkeypatch.setattr(pq.importlib.util, "find_spec", lambda name: None)  # embedder missing from the bundle
    rows = {r.name: r for r in machine.rows()}
    assert rows["uv"].need == "optional" and rows["uv"].state == "off"
    assert rows["embedder"].installable is False and "reinstall Heronry Desktop" in rows["embedder"].fix
    steps, left = pq.plan(list(rows.values()), os_key="win32", which=machine.which)
    assert steps == [] and "embedder" in [r.name for r in left]
    assert prereqs_cmd.install({"yes": True}, isatty=False) == 0 and machine.ran == []
    assert "uv pip" not in capsys.readouterr().out


def test_check_json_and_exit_code(machine, capsys):
    assert prereqs_cmd.main(["--json"]) == 1  # git missing
    import json
    got = json.loads(capsys.readouterr().out)
    assert {r["name"]: r["state"] for r in got["rows"]}["git"] == "missing"
    assert got["not_needed"][0]["name"] == "docker"


def test_unknown_names_are_refused():
    with pytest.raises(SystemExit, match="unknown prerequisite 'docker'"):
        prereqs_cmd.main(["install", "--only", "docker"])


def test_cli_lists_the_verb(capsys):
    from edp8 import cli
    cli.help_cmd([])
    assert "prereqs [install]" in capsys.readouterr().out
    assert "prereqs" in cli._COMMANDS


def test_updater_keeps_the_embed_extra(monkeypatch, tmp_path):
    from edp8 import updater
    monkeypatch.setattr(updater, "_uv", lambda: "uv")
    wheels = {w: tmp_path / f"{w}.whl" for w in updater.WHEELS}
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object() if name == "fastembed" else None)
    argv = updater.install_argv(wheels)
    assert argv[-2:] == ["--with", "fastembed>=0.3"]
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert "fastembed>=0.3" not in updater.install_argv(wheels)
