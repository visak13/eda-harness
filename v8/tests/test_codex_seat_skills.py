"""A codex seat is normal codex with its role's skills visible (owner ruling m-56c204aa9a, steer m-bbc97e7861).

  * features: only `apps` is forced off (it injects the codex_apps MCP server, measured); the rest keep
    codex's values (tests/test_codex_seat.py::test_containment_disables_every_discovered_server_and_only_…)
  * skills: the role card's **SKILLS** bundle, bound per seat with the app-server's skills/extraRoots/set
    BEFORE thread/start|resume, read back with skills/list; nothing is written to the tree or ~/.codex
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from edp8.codex_seat import seat as seat_mod

V8 = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent / "codex_seat"
DESC = V8 / "guides" / "harness-parity" / "descriptions.ours.json"


def _names(roots):
    return [Path(r).name for r in roots]


def test_role_skill_roots_follow_the_role_cards_skills_line():
    assert _names(seat_mod.role_skill_roots(V8, "reviewer")) == ["verify", "deviation", "doubt", "pain"]
    assert _names(seat_mod.role_skill_roots(V8, "engineer")) == ["methodology", "demo", "verify", "deviation",
                                                                  "doubt", "learn", "pain"]
    for r in seat_mod.role_skill_roots(V8, "qa"):
        assert Path(r).is_absolute() and (Path(r) / "SKILL.md").is_file()


def test_a_card_without_a_skills_line_gets_every_skill_and_missing_names_are_dropped(tmp_path):
    for n in ("alpha", "beta"):
        (tmp_path / ".claude" / "skills" / n).mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / n / "SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    (tmp_path / ".claude" / "commands" / "plain.md").write_text("# no skills line\n", encoding="utf-8")
    (tmp_path / ".claude" / "commands" / "picky.md").write_text("**SKILLS** /beta · /ghost\n", encoding="utf-8")
    assert _names(seat_mod.role_skill_roots(tmp_path, "plain")) == ["alpha", "beta"]
    assert _names(seat_mod.role_skill_roots(tmp_path, "picky")) == ["beta"]
    assert seat_mod.role_skill_roots(tmp_path / "nowhere", "plain") == []


def _mirror_out_methods(path: Path) -> list[str]:
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [r["msg"].get("method") for r in rows if r.get("dir") == "out" and r["msg"].get("method")]


@pytest.mark.parametrize("resume", [False, True])
def test_the_role_bundle_is_bound_before_the_thread_and_read_back(tmp_path, monkeypatch, resume):
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(tmp_path / "fake.jsonl"))
    kw = dict(cwd=V8, role="reviewer", handle="reviewer.skills", log_dir=tmp_path,
              codex_bin=str(HERE / "fake_app_server.py"), board=False,
              env={"EDP_PARITY_DESCRIPTIONS": str(DESC)}, discover=lambda _c: ([], None))
    if resume:
        first = seat_mod.CodexSeat(**kw)
        first.start()
        first.stop()
    s = seat_mod.CodexSeat(**kw)
    s.start(resume=resume)
    try:
        assert s.skills == sorted(["verify", "deviation", "doubt", "pain"])  # the bundle, not imagegen
        methods = _mirror_out_methods(s.log_path)[-6:] if resume else _mirror_out_methods(s.log_path)
        thread = "thread/resume" if resume else "thread/start"
        assert methods.index("skills/extraRoots/set") < methods.index(thread)
        sent = [json.loads(ln)["msg"]["params"]["extraRoots"] for ln in s.log_path.read_text(encoding="utf-8").splitlines()
                if '"skills/extraRoots/set"' in ln and '"dir": "out"' in ln][-1]
        assert sent == seat_mod.role_skill_roots(V8, "reviewer")
    finally:
        s.stop()


def test_binding_writes_nothing_to_the_tree(tmp_path, monkeypatch):
    """The ruling's alternative was a v8/.agents/skills junction; the RPC needs no file at all."""
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(tmp_path / "fake.jsonl"))
    s = seat_mod.CodexSeat(cwd=V8, role="qa", handle="qa.skills", log_dir=tmp_path,
                           codex_bin=str(HERE / "fake_app_server.py"), board=False,
                           env={"EDP_PARITY_DESCRIPTIONS": str(DESC)}, discover=lambda _c: ([], None))
    s.start()
    try:
        assert s.skills == ["pain", "verify"]
        assert not (V8 / ".agents").exists() and not (V8 / ".codex" / "skills").exists()
    finally:
        s.stop()


def test_a_codex_without_the_skills_rpc_still_boots_and_logs_the_gap(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(tmp_path / "fake.jsonl"))
    s = seat_mod.CodexSeat(cwd=V8, role="qa", handle="qa.noskills", log_dir=tmp_path,
                           codex_bin=str(HERE / "fake_app_server.py"), board=False,
                           env={"EDP_PARITY_DESCRIPTIONS": str(DESC)}, discover=lambda _c: ([], None))

    def refuse(method, params=None, timeout=None, _real=None):
        if method.startswith("skills/"):
            raise seat_mod.RpcError(method, {"message": "Invalid request: unknown variant"})
        return _real(method, params, timeout=timeout) if timeout else _real(method, params)
    orig_start = seat_mod.AppServer.start

    def start(self):
        orig_start(self)
        real = self.request
        self.request = lambda m, p=None, timeout=None: refuse(m, p, timeout, real)
    monkeypatch.setattr(seat_mod.AppServer, "start", start)
    s.start()
    try:
        assert s.skills == [] and s.thread_id
        assert "skills not bound" in (tmp_path / "codex-seat.qa.noskills.events.log").read_text(encoding="utf-8")
    finally:
        s.stop()


def test_the_seats_standing_context_says_monitor_runs_under_bash(tmp_path):
    """m-2485ca32e7: every codex seat's first Monitor began with PowerShell's `&` (CLAUDE.md says PowerShell
    is primary) and exited 2; the thread's developer instructions now end with the shell note."""
    from edp8.codex_seat import run as run_mod
    ctx = run_mod.standing_context(V8)
    assert ctx.startswith((V8 / "CLAUDE.md").read_text(encoding="utf-8").rstrip()[:200])
    assert ctx.rstrip().endswith(run_mod.SHELL_NOTE) and "Git bash" in ctx and "&" in run_mod.SHELL_NOTE
    (tmp_path / "AGENTS.md").write_text("codex reads me itself", encoding="utf-8")
    assert run_mod.standing_context(tmp_path).strip() == run_mod.SHELL_NOTE
