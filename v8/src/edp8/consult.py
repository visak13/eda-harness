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
_DEFAULT_MODEL = "gpt-6-astra"  # matches claude/.bridge.json's "sol" delegate (2026-09-05: Astra)
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
        # npm hands back a .cmd shim; run the REAL exe behind it so the prompt
        # never passes through cmd.exe quoting.
        if Path(found).suffix.lower() != ".exe":
            pkg_root = Path(found).resolve().parent / "node_modules" / "@openai"
            for exe in sorted(pkg_root.rglob("codex.exe")) if pkg_root.is_dir() else []:
                if exe.parent.name == "bin":
                    return str(exe)
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
                 model: str, effort: str, sandbox: str = "read-only",
                 images: list[str] | None = None,
                 resume_thread: str | None = None) -> list[str]:
    """Fresh turn:  `codex exec <globals> [-i img...] -- <prompt>`
    Resume turn: `codex exec <globals> resume [-i img]* -- <thread_id> <prompt>`

    Globals precede the subcommand; the prompt is the LAST positional behind
    `--` so a leading '-' is never parsed as a flag. On a FRESH turn `-i` is
    variadic and must be terminated by `--`; on RESUME `-i` is per-flag and
    sits AFTER the `resume` subcommand (it attaches to the follow-up prompt).
    Sandbox: read-only for advice; workspace-write when the caller hands Sol a
    directory to deliver into or edit in place. PURE — no IO."""
    imgs = [i for i in (images or []) if i]
    argv = [codex, "exec", "--skip-git-repo-check",
            "-C", workdir, "-s", sandbox, "--json", "--color", "never",
            "-o", last_message_file]
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["-c", f"model_reasoning_effort={effort}"]
    if resume_thread:
        argv.append("resume")
        for img in imgs:
            argv += ["-i", img]
        argv += ["--", resume_thread, prompt]
    else:
        if imgs:
            argv.append("-i")
            argv += imgs
        argv += ["--", prompt]
    return argv


def parse_thread_id(jsonl_text: str) -> str | None:
    """Pull the Codex thread id out of the `--json` event stream — the
    `{"type":"thread.started","thread_id":"…"}` event (first line normally).
    Defensive: never raises on lines that are not JSON or not that event."""
    import json
    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "thread.started":
            tid = ev.get("thread_id") or ev.get("session_id")
            if isinstance(tid, str) and tid:
                return tid
    return None


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line:
            return line
    return "codex produced no output"


def consult(purpose: Purpose, question: str, context: str = "",
            files: list[str] | None = None, timeout_s: int = 600,
            write_dir: str | None = None, images: list[str] | None = None,
            thread_id: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Ask Sol one question and return the standard envelope. Never retries,
    never glosses a failure as a quota cap — `error.message` is always the
    real last output line from the codex process.

    `write_dir` unlocks delivery: Sol runs sandboxed to that directory with
    write access and can create assets or edit files in place. The proven
    shape for substantial work is TWO rounds: first no write_dir (get a plan),
    then pass the agreed plan back WITH write_dir (let Sol build it).

    `thread_id` STEERS: pass the `thread_id` returned by an earlier call and
    this turn resumes that Sol session (`codex exec resume`) with full memory
    of what it said and did — the follow-up, correction, or "here is the
    screenshot of what you told me to build". Omit it for a cold start.

    `images` are attached with `-i` — the ONLY way a picture reaches Sol
    (citing a path in the prompt is a no-op). Screenshots, renders, mockups.

    `model` picks the consultant for THIS call (a Codex model id such as
    `gpt-6-astra` or `gpt-5.6-sol`); omitted → `EDP8_SOL_MODEL` → the default
    (gpt-6-astra since 2026-09-05). A resumed thread keeps whatever model it
    was started with unless overridden here."""
    if purpose not in _PREAMBLES:
        return {"ok": False,
                "error": {"code": "exit", "message": f"unknown purpose {purpose!r}"},
                "hint": f"purpose must be one of {sorted(_PREAMBLES)}"}
    if write_dir and not Path(write_dir).is_dir():
        return {"ok": False,
                "error": {"code": "exit", "message": f"write_dir {write_dir!r} is not a directory"},
                "hint": "create it first, or pass the directory that holds the files to edit"}
    images = [i for i in (images or []) if i]
    for img in images:
        if not Path(img).is_file():
            return {"ok": False,
                    "error": {"code": "exit", "message": f"image {img!r} does not exist"},
                    "hint": "attach existing files (png/jpg); attaching is the only way an image reaches Sol"}
    thread_id = (thread_id or "").strip() or None

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
    model = (model or "").strip() or os.environ.get(_MODEL_ENV, "").strip() or _DEFAULT_MODEL

    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}.jsonl"
    last_msg = log_dir / f".last-message-{run_id}.txt"

    argv = _build_argv(codex, prompt=prompt, workdir=write_dir or os.getcwd(),
                        last_message_file=str(last_msg), model=model,
                        effort=_EFFORT_BY_PURPOSE.get(purpose, "medium"),
                        sandbox="workspace-write" if write_dir else "read-only",
                        images=images, resume_thread=thread_id)

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

    out_thread = parse_thread_id(raw) or thread_id
    return {"ok": True,
            "value": {"answer": answer, "model": model, "elapsed_s": round(elapsed, 3),
                      "run_id": run_id, "log": str(log_path), "thread_id": out_thread,
                      "images_attached": len(images)},
            "hint": ("pass thread_id back on the next consult to STEER this same Sol session"
                     if out_thread else "")}


def _write_log(log_path: Path, raw: str) -> None:
    try:
        log_path.write_text(raw, encoding="utf-8")
    except OSError:
        pass
