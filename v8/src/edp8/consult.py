"""edp8.consult — the v8 bridge to GPT Sol via the OpenAI Codex CLI.

Replaces claude/src/edp_claude/tools/sol_bridge.py for v8. Keeps the landmines
that module documented (empty stdin else the CLI hangs forever; globals BEFORE
the `exec` subcommand; the prompt ALWAYS behind `--`; stdout+stderr merged
because the interesting error lands on stderr; `-o` for the final answer) but
drops the asset-authoring machinery (binary host-sibling scan, code-tree
guard, thread stickiness) that v8's read/advise-only consult() doesn't need.

PAIN POINT (claude/docs/pain-points.jsonl, 2026-08-21): the old bridge glossed
every non-zero exit as "quota cap" even when the account had headroom, and hid
the real stderr. This module never does that — a failure's `message` is always
the actual last non-empty output line from codex, and the `hint` says what to
check (login / model id / network), never a canned quota story.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Literal

Purpose = Literal["adversary", "creative", "visual", "second_opinion", "build"]

#: Short system preambles selected by purpose (user directive, this task).
_PREAMBLES: dict[str, str] = {
    "adversary": (
        "attack this delivery: find bugs, gaps vs the stated requirement, risky "
        "assumptions; classify each finding obvious-bug vs scope-question; be "
        "concrete (file, line, repro)."
    ),
    "creative": (
        "you are the visual/creative authority: judge or specify look against "
        "the references; give measurable bars. When a writable workspace is "
        "given, deliver files (SVG/CSS/code) directly into it — never describe "
        "an asset you could produce."
    ),
    "visual": (
        "you are the visual/creative authority: judge or specify look against "
        "the references; give measurable bars. When a writable workspace is "
        "given, deliver files (SVG/CSS/code) directly into it — never describe "
        "an asset you could produce."
    ),
    "second_opinion": "give an independent read; disagree where warranted.",
    "build": (
        "you are a senior implementation agent working directly in the "
        "workspace, and you OWN THE OUTCOME, not just the checklist: the "
        "stated constraints are the floor — the quality bar is your own, and "
        "'technically satisfies the instructions' is a failure if the result "
        "is lifeless. Keep the code style of the files you touch and do not "
        "break existing behavior. End your reply with the list of every file "
        "you created or edited and one line on why."
    ),
}

_BIN_ENV = "EDP8_CODEX_BIN"
_MODEL_ENV = "EDP8_SOL_MODEL"
_LOG_DIR_ENV = "EDP8_SOL_LOG_DIR"
_DEFAULT_BIN = "codex"
_DEFAULT_MODEL = "gpt-5.6-sol"  # matches claude/.bridge.json's "sol" delegate
# Reasoning effort by purpose (owner finding 2026-09-02: creative/build work at medium
# effort came out flat — screenshots pasted where the human's own high-effort prompts
# had produced crafted, animated work. Advice stays medium; CRAFT runs high.)
_EFFORT_BY_PURPOSE = {"adversary": "medium", "second_opinion": "medium",
                      "creative": "high", "visual": "high", "build": "high"}


def _log_dir() -> Path:
    override = os.environ.get(_LOG_DIR_ENV, "").strip()
    if override:
        return Path(override)
    home = os.environ.get("EDP8_HOME") or str(Path(__file__).resolve().parents[2])
    return Path(home) / ".sol"


def _resolve_bin() -> str:
    """EDP8_CODEX_BIN → PATH `codex` → the ChatGPT app's codex.exe under ~/.codex
    (plugins/.plugin-appserver first, then the first codex.exe found)."""
    import shutil
    from pathlib import Path

    override = os.environ.get(_BIN_ENV, "").strip()
    if override:
        return override
    found = shutil.which("codex") or shutil.which("codex.cmd")
    if found:
        return found
    root = Path(os.environ.get("EDP8_CODEX_HOME") or (Path.home() / ".codex"))
    preferred = root / "plugins" / ".plugin-appserver" / "codex.exe"
    if preferred.is_file():
        return str(preferred)
    if root.is_dir():
        for exe in sorted(root.rglob("codex.exe")):
            return str(exe)
    return _DEFAULT_BIN


def _build_argv(codex: str, *, prompt: str, workdir: str, last_message_file: str,
                 model: str, effort: str, sandbox: str = "read-only") -> list[str]:
    """`codex exec <globals> -- <prompt>`. Globals precede the subcommand; the
    prompt is the LAST positional behind `--` so a leading '-' is never parsed
    as a flag. Sandbox: read-only for advice; workspace-write when the caller
    hands Sol a directory to deliver into or edit in place."""
    argv = [codex, "exec", "--skip-git-repo-check",
            "-C", workdir, "-s", sandbox, "--json", "--color", "never",
            "-o", last_message_file]
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["-c", f"model_reasoning_effort={effort}"]
    argv += ["--", prompt]
    return argv


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line:
            return line
    return "codex produced no output"


def consult(purpose: Purpose, question: str, context: str = "",
            files: list[str] | None = None, timeout_s: int = 600,
            write_dir: str | None = None) -> dict[str, Any]:
    """Ask Sol one question and return the standard envelope. Never retries,
    never glosses a failure as a quota cap — `error.message` is always the
    real last output line from the codex process.

    `write_dir` unlocks delivery: Sol runs sandboxed to that directory with
    write access and can create assets or edit files in place. The proven
    shape for substantial work is TWO rounds: first no write_dir (get a plan),
    then pass the agreed plan back WITH write_dir (let Sol build it)."""
    if purpose not in _PREAMBLES:
        return {"ok": False,
                "error": {"code": "exit", "message": f"unknown purpose {purpose!r}"},
                "hint": f"purpose must be one of {sorted(_PREAMBLES)}"}
    if write_dir and not Path(write_dir).is_dir():
        return {"ok": False,
                "error": {"code": "exit", "message": f"write_dir {write_dir!r} is not a directory"},
                "hint": "create it first, or pass the directory that holds the files to edit"}

    parts = [_PREAMBLES[purpose], "", (question or "").strip()]
    if context.strip():
        parts += ["", "Context:", context.strip()]
    if files:
        parts += ["", "Relevant files (read them from the working tree):"]
        parts += [f"- {f}" for f in files]
    if write_dir:
        parts += ["", f"You have WRITE access to {write_dir} (and only there): deliver files "
                      f"into it or edit in place as asked."]
    prompt = "\n".join(parts)

    codex = _resolve_bin()
    model = os.environ.get(_MODEL_ENV, "").strip() or _DEFAULT_MODEL

    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}.jsonl"
    last_msg = log_dir / f".last-message-{run_id}.txt"

    argv = _build_argv(codex, prompt=prompt, workdir=write_dir or os.getcwd(),
                        last_message_file=str(last_msg), model=model,
                        effort=_EFFORT_BY_PURPOSE.get(purpose, "medium"),
                        sandbox="workspace-write" if write_dir else "read-only")

    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv, stdin=subprocess.DEVNULL,          # empty stdin => instant EOF
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # merge: real error is on stderr
            timeout=timeout_s, text=True, encoding="utf-8", errors="replace")
        raw = proc.stdout or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        raw = (e.stdout or "") if isinstance(e.stdout, str) else ""
        _write_log(log_path, raw)
        return {"ok": False,
                "error": {"code": "timeout",
                          "message": f"codex exceeded {timeout_s}s and was killed "
                                     f"(last output: {_last_nonempty_line(raw)})"},
                "hint": "check whether codex is stuck on a login/consent prompt; do not retry immediately"}
    except (OSError, ValueError) as e:
        return {"ok": False,
                "error": {"code": "unavailable", "message": f"could not launch {codex!r}: {e}"},
                "hint": f"check {_BIN_ENV} and that `codex` is on PATH (`codex login` may be required)"}

    elapsed = time.monotonic() - start
    _write_log(log_path, raw)

    answer = ""
    if last_msg.is_file():
        try:
            answer = last_msg.read_text(encoding="utf-8").strip()
        finally:
            try:
                last_msg.unlink()
            except OSError:
                pass

    if exit_code != 0:
        return {"ok": False,
                "error": {"code": "exit",
                          "message": f"codex exited {exit_code}: {_last_nonempty_line(raw)}"},
                "hint": "check `codex login` status, EDP8_SOL_MODEL, and network — "
                        "a non-zero exit is not automatically a quota cap"}

    if not answer:
        answer = _last_nonempty_line(raw)

    return {"ok": True,
            "value": {"answer": answer, "model": model, "elapsed_s": round(elapsed, 3),
                      "run_id": run_id, "log": str(log_path)},
            "hint": ""}


def _write_log(log_path: Path, raw: str) -> None:
    try:
        log_path.write_text(raw, encoding="utf-8")
    except OSError:
        pass
