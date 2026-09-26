"""S4 (s-733de6e29f, design-e963c656f5 §4.7): the claude shell output rule mirrored 1:1 to codex seats.

One file feeds both harnesses: the agent home's `.claude/output-styles/edp-terse.md`. A Claude seat runs with
cwd = the agent home, so the pool's `outputStyle: edp-terse` resolves to that project style (the pool config
dir carries no copy that could shadow it); a codex seat's developerInstructions carry its body verbatim (front
matter stripped) plus the resident-seat contract, on thread/start AND thread/resume.
"""
import json
from pathlib import Path

import pytest

from edp8.codex_seat import run as run_mod
from edp8.codex_seat.seat import CodexSeat, idle_waiter

V8 = Path(__file__).resolve().parents[1]
POOL_CFG = V8.parent / "edp-pool" / ".claude-pool"
FAKE = V8 / "tests" / "codex_seat" / "fake_app_server.py"
STYLE = V8 / run_mod.OUTPUT_STYLE


def _body() -> str:
    """The style file minus its YAML front matter, computed independently of run.output_style_body."""
    text = STYLE.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[1].strip("\n")


def test_the_single_source_is_the_agent_home_style_and_the_claude_pool_resolves_to_it():
    settings = json.loads((POOL_CFG / "settings.json").read_text(encoding="utf-8-sig"))
    assert settings["outputStyle"] == "edp-terse"
    front = STYLE.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    assert "name: edp-terse" in front  # the name the pool's settings select
    # no user-level copy in the pool config dir: the project style under the seat's cwd is the one resolved
    assert not (POOL_CFG / "output-styles" / "edp-terse.md").exists()


def test_standing_context_carries_the_style_body_byte_identical_plus_the_contract():
    ctx = run_mod.standing_context(V8)
    body = _body()
    assert run_mod.output_style_body(V8) == body
    assert body in ctx and "name: edp-terse" not in ctx
    assert ctx.index(run_mod.SHELL_NOTE) < ctx.index(body) < ctx.index(run_mod.RESIDENT_CONTRACT)
    for must in ("supersedes your default preambles", "ZERO assistant text", "at most one short receipt line",
                 "pyramid"):
        assert must in ctx


def test_a_home_without_the_style_file_refuses_the_seat(tmp_path):
    with pytest.raises(OSError):
        run_mod.standing_context(tmp_path)


def _seat(tmp_path, log, effort=None):
    return CodexSeat(cwd=V8, role="engineer", handle="engineer.outrule", log_dir=tmp_path, codex_bin=str(FAKE),
                     board=False, discover=lambda _c: ([], None), skill_roots=[], effort=effort,
                     developer_instructions=run_mod.standing_context(V8),
                     env={"FAKE_APPSERVER_LOG": str(log), "EDP_SKIP_PERMISSIONS": "0", "EDP_CODEX_SANDBOX": ""})


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("effort", [None, "high"])
def test_developer_instructions_and_quiet_settings_go_on_start_and_resume(tmp_path, resume, effort):
    log = tmp_path / "fake.jsonl"
    seat = _seat(tmp_path, log, effort)
    if resume:
        seat.state_path.parent.mkdir(parents=True, exist_ok=True)
        seat.state_path.write_text(json.dumps({"threadId": "thr-prior"}), encoding="utf-8")
    try:
        seat.start(resume=resume)
        sent = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        method = "thread/resume" if resume else "thread/start"
        p = next(m for m in sent if m.get("method") == method)["params"]
        assert _body() in p["developerInstructions"]
        assert run_mod.RESIDENT_CONTRACT in p["developerInstructions"]
        assert p["personality"] == "none"
        want = {"model_verbosity": "low", "model_reasoning_summary": "none"}
        if effort:
            want["model_reasoning_effort"] = effort  # merged, never overwritten
        assert p["config"] == want
    finally:
        seat.stop()


def test_a_turn_with_no_final_message_still_ends_the_turn(tmp_path):
    """§4.7 limit: prompting cannot guarantee zero text, so the runner never waits for one — turn/completed
    with no agentMessage leaves the seat idle and ready for the next wake."""
    log = tmp_path / "fake.jsonl"
    seat = _seat(tmp_path, log)
    try:
        seat.start()
        seat.enqueue_turn("a quiet wake: nothing changed")
        assert idle_waiter(seat, 20)
        seat.enqueue_turn("SAY one receipt line")
        assert idle_waiter(seat, 20)
        sent = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        assert sum(1 for m in sent if m.get("method") == "turn/start") == 2
    finally:
        seat.stop()
