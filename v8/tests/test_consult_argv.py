"""consult bridge — pure argv/parse contracts for steer (thread resume) and images."""

from __future__ import annotations

import json

import pytest

from edp8 import consult as consult_mod
from edp8.consult import _build_argv, parse_thread_id


def _base(**kw):
    kw.setdefault("prompt", "hello")
    kw.setdefault("workdir", "C:/w")
    kw.setdefault("last_message_file", "C:/w/last.txt")
    kw.setdefault("model", "gpt-6-astra")
    kw.setdefault("effort", "medium")
    return _build_argv("codex", **kw)


def test_fresh_turn_prompt_last_behind_double_dash():
    argv = _base()
    assert argv[:2] == ["codex", "exec"]
    assert argv[-2:] == ["--", "hello"]
    assert "resume" not in argv and "-i" not in argv


def test_fresh_turn_images_are_variadic_and_terminated():
    argv = _base(images=["a.png", "b.png"])
    i = argv.index("-i")
    assert argv[i:i + 3] == ["-i", "a.png", "b.png"]
    assert argv[i + 3:] == ["--", "hello"]        # `--` terminates the variadic -i


def test_resume_turn_shape():
    argv = _base(resume_thread="0199-thread", images=["shot.png"])
    r = argv.index("resume")
    # globals (model/effort) come BEFORE the subcommand
    assert argv.index("-m") < r and argv.index("-c") < r
    # per-flag -i after resume, then -- <thread_id> <prompt>
    assert argv[r:] == ["resume", "-i", "shot.png", "--", "0199-thread", "hello"]


def test_resume_without_images():
    argv = _base(resume_thread="t1")
    assert argv[-4:] == ["resume", "--", "t1", "hello"]


def test_parse_thread_id_from_stream():
    raw = "\n".join([
        "Reading additional input from stdin...",
        json.dumps({"type": "thread.started", "thread_id": "01a05efd-dea4-7ed3-b289-444bda9e744d"}),
        json.dumps({"type": "turn.started"}),
        "2026-09-01T22:01:33Z ERROR rmcp::transport::worker: worker quit",
        "{not json",
    ])
    assert parse_thread_id(raw) == "01a05efd-dea4-7ed3-b289-444bda9e744d"


def test_parse_thread_id_absent():
    assert parse_thread_id("no events here\n{\"type\":\"turn.completed\"}") is None


def test_consult_rejects_missing_image(tmp_path):
    resp = consult_mod.consult("second_opinion", "look", images=[str(tmp_path / "nope.png")])
    assert resp["ok"] is False
    assert "does not exist" in resp["error"]["message"]


def test_consult_threads_and_images_reach_argv(tmp_path, monkeypatch):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    seen: dict = {}

    class _Proc:
        returncode = 0
        stdout = json.dumps({"type": "thread.started", "thread_id": "tid-42"}) + "\n"

    def fake_run(argv, **kw):
        seen["argv"] = argv
        # emulate -o last-message file
        o = argv[argv.index("-o") + 1]
        with open(o, "w", encoding="utf-8") as fh:
            fh.write("the image shows a nebula")
        return _Proc()

    monkeypatch.setattr(consult_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: "codex")
    monkeypatch.setenv("EDP8_SOL_LOG_DIR", str(tmp_path / "logs"))

    resp = consult_mod.consult("visual", "critique", images=[str(img)], thread_id="prev-7")
    assert resp["ok"], resp
    assert resp["value"]["thread_id"] == "tid-42"       # parsed from the stream wins
    assert resp["value"]["images_attached"] == 1
    assert resp["value"]["answer"] == "the image shows a nebula"
    argv = seen["argv"]
    r = argv.index("resume")
    assert argv[r:] == ["resume", "-i", str(img), "--", "prev-7", argv[-1]]


def test_consult_fresh_returns_thread_id_and_hint(tmp_path, monkeypatch):
    class _Proc:
        returncode = 0
        stdout = json.dumps({"type": "thread.started", "thread_id": "tid-1"}) + "\nfinal line\n"

    monkeypatch.setattr(consult_mod.subprocess, "run", lambda argv, **kw: _Proc())
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: "codex")
    monkeypatch.setenv("EDP8_SOL_LOG_DIR", str(tmp_path / "logs"))
    resp = consult_mod.consult("second_opinion", "q")
    assert resp["ok"]
    assert resp["value"]["thread_id"] == "tid-1"
    assert "STEER" in resp["hint"]


def test_consult_model_override_beats_env_and_default(tmp_path, monkeypatch):
    """Per-call `model=` wins over EDP8_SOL_MODEL, which wins over the default."""
    from edp8 import consult as c
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        raise FileNotFoundError("no codex in this test")

    monkeypatch.setattr(c.subprocess, "run", fake_run)
    monkeypatch.setattr(c, "_resolve_bin", lambda: "codex")
    monkeypatch.setenv(c._LOG_DIR_ENV, str(tmp_path))

    monkeypatch.delenv(c._MODEL_ENV, raising=False)
    c.consult("second_opinion", "q")
    assert seen["argv"][seen["argv"].index("-m") + 1] == "gpt-6-astra"

    monkeypatch.setenv(c._MODEL_ENV, "gpt-5.6-sol")
    c.consult("second_opinion", "q")
    assert seen["argv"][seen["argv"].index("-m") + 1] == "gpt-5.6-sol"

    c.consult("second_opinion", "q", model="gpt-6-astra")
    assert seen["argv"][seen["argv"].index("-m") + 1] == "gpt-6-astra"
