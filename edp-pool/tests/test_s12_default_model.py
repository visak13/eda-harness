"""S12 c-d38bf82b4a (owner bug m-549b8adc3a): every spawned role launches with `--model <catalog id>`.

A Help `doctor` seat once started with no `--model` and ran on the CLI's own default. The pool's spawn seam
now resolves an unpassed model as: the role's first `role_models` entry, else its legacy `roles` seat, else
the catalog's `default_model`, so a custom (S13) role and a role no table names still carry `--model`."""

import json

import pytest

from edp_pool import pty_launcher
from edp_pool import spawner as pl

CATALOG = {
    "default_model": "claude-opus-5-5",
    "models": {"claude-opus-5-5": {"harness": "claude", "provider": "claude"},
               "claude-fable-5-1": {"harness": "claude", "provider": "claude"}},
    "role_models": {"doctor": ["claude-fable-5-1"], "engineer": ["claude-opus-5-5"]},
    "seats": {"builder": {"model": "claude-opus-5-5"}},
    "roles": {"engineer": "builder"},
}


@pytest.fixture
def home(tmp_path):
    (tmp_path / "models.json").write_text(json.dumps(CATALOG), encoding="utf-8")
    return tmp_path


def _launch_argv(home, monkeypatch, role: str, handle: str) -> list[str]:
    captured: dict = {}

    class FakePty:
        def __init__(self, argv, env, cwd, log_path, name):
            captured["argv"] = list(argv)
            self.pid = 4243

        def spawn(self):
            pass

        def kill(self):
            pass

    monkeypatch.setattr(pty_launcher, "PtyLaunch", FakePty)
    monkeypatch.setattr(pty_launcher, "resolve_claude_bin", lambda b: "claude.exe")
    monkeypatch.setattr(pty_launcher, "ensure_claude_healthy", lambda b: b)
    monkeypatch.setattr(pty_launcher, "ensure_claude_runs", lambda b: b)
    monkeypatch.setattr(pl.SubprocessSpawner, "_activate_pty", lambda self, *a: None)
    sp = pl.SubprocessSpawner(cwd=str(home), log_dir=home)
    sp.launch(f"{role}:1", role, handle, mode="headless", model=None)
    return captured["argv"]


def _model_flag(argv: list[str]) -> str | None:
    return argv[argv.index("--model") + 1] if "--model" in argv else None


@pytest.mark.parametrize("role,handle,expected", [
    ("doctor", "doctor.topic-x", "claude-fable-5-1"),          # listed in role_models
    ("designer", "designer.s-custom", "claude-opus-5-5"),      # an S13 custom role: catalog default
    ("unlisted", "unlisted.x", "claude-opus-5-5"),             # no table names it: catalog default
])
def test_every_role_spawns_with_a_catalog_model(home, monkeypatch, role, handle, expected):
    assert _model_flag(_launch_argv(home, monkeypatch, role, handle)) == expected


def test_seat_model_for_order(home):
    assert pl.seat_model_for("engineer", str(home)) == "claude-opus-5-5"   # role_models first
    assert pl.seat_model_for("owner", str(home)) == "claude-opus-5-5"      # no row: default_model
    raw = dict(CATALOG, roles={"owner": "builder"}, seats={"builder": {"model": "claude-fable-5-1"}})
    (home / "models.json").write_text(json.dumps(raw), encoding="utf-8")
    assert pl.seat_model_for("owner", str(home)) == "claude-fable-5-1"     # legacy roles seat before default
    assert pl.seat_model_for("x", None) is None
