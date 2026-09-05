"""The deterministic Sol (GPT / codex CLI) bridge engine.

WHY THIS EXISTS (user directive, 2026-07-16). Sol is reached through the OpenAI
Codex CLI, whose invocation has five landmines and a binary-selection trap that
a shell WILL get wrong (the reverse-engineered record is C:\\Projects\\NightSky\\
docs\\SOL-BRIDGE.md). This module hard-wires every one of them so the agent-facing
tools (`sol_author_asset`, `sol_consult` in tools/_tools.py) expose the MINIMUM
surface — even a Sonnet worker cannot mis-invoke Sol, because there is nothing to
mis-invoke: it passes a brief and a directory, and this engine builds the argv.

WHAT IS HARD-WIRED HERE (nothing below is the agent's job):
  * BINARY SELECTION by the only rule that is stable across ChatGPT-app updates:
    the copy of `codex.exe` that has `codex-code-mode-host.exe` BESIDE it. The
    `.sandbox-bin` copy talks to Sol, exits 0, and CANNOT let Sol write a file —
    and the failure is silent unless you read stderr. Never selected here.
  * ARGV ORDER: exec globals BEFORE the subcommand; `-i` variadic on a fresh
    turn is terminated with `--`; `-i` is per-flag on resume (attaches to the
    post-resume prompt); the prompt is ALWAYS behind `--` so a brief that starts
    with `-` is never parsed as a flag.
  * EMPTY STDIN: the CLI hangs forever waiting for EOF on a non-TTY stdin. We
    always pass an empty stdin (DEVNULL) and the prompt as a positional argv
    element (the verified path — SOL-BRIDGE §2/§4).
  * FULL CAPTURE: stdout AND stderr merged into one JSONL blob, because the
    code-mode-host router error goes to stderr and never to `-o`.
  * NON-ZERO EXIT IS A FIRST-CLASS BLOCKER. Sol spend bills the user's ChatGPT
    plan quota and this CLI exposes NO rate-limit telemetry, so a cap is only
    discoverable on failure. `run_sol` NEVER retries, NEVER grinds, NEVER
    silently shrinks the request. It returns the failure for the tool to surface
    upward immediately.
  * SESSION STICKINESS: a thread id is persisted per (caller, advisor) so a long
    worker accretes one Sol thread instead of re-briefing from scratch, and can
    hold SEPARATE threads for separate advisors so context is not cross-polluted.
  * CODE-TREE GUARD (author path): Sol's write root (`-C`) is refused if it lands
    inside a protected code tree or names a source directory — Sol authors ASSETS,
    never code. `-s workspace-write` then confines every write to that one dir.

This module is deliberately framework-agnostic and mostly PURE: `build_argv`,
`parse_events`, `resolve_codex_binary`, and `refuse_code_tree` take no ctx and do
no IO beyond a filesystem existence probe, so they are unit-tested without ever
calling Sol. Only `run_sol` spawns the subprocess.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── configuration seams (env-overridable; defaults match this machine) ───────

#: Explicit binary override. When set it wins outright (still validated for the
#: host sibling below, so an override at the broken copy is refused loudly).
_ENV_BIN = "EDP_SOL_CODEX_BIN"

#: The sibling that distinguishes the working copy from the broken `.sandbox-bin`
#: one. Its ABSENCE is the whole bug — Sol can talk but not write.
_HOST_SIBLING = "codex-code-mode-host.exe"

#: Where to search when no override is set. `~/.codex` holds every app-managed
#: copy; we pick the one with the host beside it, preferring the appserver path.
_SEARCH_ROOT_ENV = "CODEX_HOME"

#: Per-(caller, advisor) thread store. Under the agent home so every pool-spawned
#: shell in this stack shares it.
_THREADS_ENV = "EDP_SOL_THREADS_FILE"

#: Wall-clock ceiling for a single Sol turn. A real asset turn ran ~6 min
#: (SOL-BRIDGE §3); 15 min leaves headroom. On timeout we KILL and surface a
#: blocker — never a silent retry.
_TIMEOUT_ENV = "EDP_SOL_TIMEOUT_SECS"
_TIMEOUT_DEFAULT = 900.0

#: Windows caps a command line near 32 KB. The prompt rides as one argv element
#: (the verified path), so guard well under that; a longer brief is refused with
#: an actionable message rather than truncated.
_PROMPT_MAX_BYTES = 30000

#: Protected code trees: Sol's `-C` write root may not land inside any of these.
#: The framework repo and the user's read-only Codex working tree (SOL-BRIDGE §7)
#: are always protected; extend via EDP_SOL_CODE_ROOTS (os.pathsep-separated).
_CODE_ROOTS_ENV = "EDP_SOL_CODE_ROOTS"
_DEFAULT_CODE_ROOTS = (
    r"C:\Projects\Learning\eda-base3",
    r"C:\Users\aksou\Documents\Codex",
)

#: Directory names that mean "source", never "asset". A `-C` target that IS one
#: of these (or sits directly under a repo root as one) is refused.
_CODE_DIR_NAMES = frozenset({
    "src", "source", "lib", "libs", "tests", "test", "node_modules",
    "scripts", "__pycache__", ".git", ".venv", "site-packages",
})


# ── binary selection ─────────────────────────────────────────────────────────
class SolBridgeError(RuntimeError):
    """A precondition the engine refuses to proceed past (bad binary, bad write
    target, oversized prompt). The tool layer turns this into a TOOL_PRECONDITION
    ToolError — never a raised exception across the MCP boundary."""


def _has_host_sibling(codex_exe: Path) -> bool:
    return (codex_exe.parent / _HOST_SIBLING).is_file()


def _path_codex() -> Path | None:
    """The `codex` on PATH (the npm-installed CLI, updated by update-claude.bat),
    resolved to its REAL exe. `shutil.which` hands back the npm `.cmd` shim; we
    never run that — a prompt would then pass through cmd.exe quoting — so walk
    from the shim's directory into the platform package and take the `codex.exe`
    that has the host sibling beside it. None when there is no usable copy."""
    shim = shutil.which("codex") or shutil.which("codex.cmd")
    if not shim:
        return None
    here = Path(shim).resolve().parent
    if here.name.lower() == "codex.exe" or Path(shim).suffix.lower() == ".exe":
        exe = Path(shim)
        return exe if _has_host_sibling(exe) else None
    pkg_root = here / "node_modules" / "@openai"
    if not pkg_root.is_dir():
        return None
    for exe in sorted(pkg_root.rglob("codex.exe")):
        if exe.parent.name == "bin" and _has_host_sibling(exe):
            return exe
    return None


def resolve_codex_binary() -> Path:
    """The one `codex.exe` that can actually let Sol WRITE — i.e. the copy with
    `codex-code-mode-host.exe` beside it. Selection rule, never a hard-coded path
    (the ChatGPT app moves these on update; SOL-BRIDGE §2).

    Order: explicit env override (still validated) → the `codex` on PATH (the npm
    CLI: it is what update-claude.bat keeps current, and a NEW model such as
    gpt-6-astra is served only to a new-enough client) → the app's appserver
    path → a recursive scan under ~/.codex for any codex.exe with the host beside
    it. Raises SolBridgeError naming the fix if none qualifies. NEVER returns the
    `.sandbox-bin` copy.
    """
    override = os.environ.get(_ENV_BIN, "").strip()
    if override:
        p = Path(override)
        if not p.is_file():
            raise SolBridgeError(
                f"{_ENV_BIN}={override!r} does not exist. Point it at the "
                f"codex.exe that has {_HOST_SIBLING} beside it, or unset it to "
                f"auto-resolve.")
        if not _has_host_sibling(p):
            raise SolBridgeError(
                f"{_ENV_BIN}={override!r} has no {_HOST_SIBLING} beside it — it "
                f"is the copy that can TALK to Sol but cannot let Sol write "
                f"files (the write failure is silent). Pick the copy with the "
                f"host sibling.")
        return p

    on_path = _path_codex()
    if on_path is not None:
        return on_path

    home = os.environ.get(_SEARCH_ROOT_ENV) or str(Path.home() / ".codex")
    root = Path(home)
    preferred = root / "plugins" / ".plugin-appserver" / "codex.exe"
    if preferred.is_file() and _has_host_sibling(preferred):
        return preferred

    # Fall back to a scan: the FIRST codex.exe with the host beside it. Sorted so
    # the choice is deterministic across runs.
    if root.is_dir():
        for exe in sorted(root.rglob("codex.exe")):
            if _has_host_sibling(exe):
                return exe

    raise SolBridgeError(
        f"no working codex.exe found under {root} — need one with "
        f"{_HOST_SIBLING} beside it (the copy that can let Sol WRITE files; the "
        f".sandbox-bin copy cannot and must not be used). Set {_ENV_BIN} to the "
        f"correct path, or check that the ChatGPT/Codex app is installed.")


# ── code-tree guard (author path only) ───────────────────────────────────────
def _code_roots() -> list[Path]:
    roots = list(_DEFAULT_CODE_ROOTS)
    extra = os.environ.get(_CODE_ROOTS_ENV, "").strip()
    if extra:
        roots += [r for r in extra.split(os.pathsep) if r.strip()]
    out: list[Path] = []
    for r in roots:
        try:
            out.append(Path(r).resolve())
        except (OSError, ValueError):
            continue
    return out


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def refuse_code_tree(asset_dir: str) -> Path:
    """Validate `asset_dir` as a place Sol may WRITE assets — and refuse it if it
    is (or is inside) a protected code tree, or names a source directory. Returns
    the resolved absolute Path on success.

    This is the structural guarantee behind the user's rule that Sol never
    touches code: `-C` confines every Sol write to this directory, and this guard
    refuses to let that directory be a code location in the first place. PURE
    apart from `.resolve()` (which does not require the path to exist).
    """
    if not asset_dir or not str(asset_dir).strip():
        raise SolBridgeError("asset_dir is required — it is Sol's write root.")
    p = Path(asset_dir)
    if not p.is_absolute():
        raise SolBridgeError(
            f"asset_dir must be ABSOLUTE (the MCP server's cwd is not yours): "
            f"{asset_dir!r}")
    resolved = p.resolve()

    for root in _code_roots():
        if resolved == root or _is_within(resolved, root):
            raise SolBridgeError(
                f"asset_dir {resolved} is inside a protected code tree ({root}). "
                f"Sol authors ASSETS, never code — point -C at a dedicated asset "
                f"directory OUTSIDE the source tree (e.g. an assets/ folder in "
                f"the target project). Extend {_CODE_ROOTS_ENV} to protect more.")

    lowered = {seg.lower() for seg in resolved.parts}
    hit = lowered & _CODE_DIR_NAMES
    if hit:
        raise SolBridgeError(
            f"asset_dir {resolved} contains a source directory ({sorted(hit)}). "
            f"Sol authors assets only — choose an asset directory whose path has "
            f"no source segment ({sorted(_CODE_DIR_NAMES)}).")
    return resolved


# ── thread store (session stickiness per caller+advisor) ─────────────────────
def _threads_file() -> Path:
    override = os.environ.get(_THREADS_ENV, "").strip()
    if override:
        return Path(override)
    home = os.environ.get("EDP_AGENT_HOME") or os.getcwd()
    return Path(home) / ".sol" / "threads.json"


def thread_key(caller: str, advisor: str) -> str:
    """The stickiness key. `caller` is the shell's EDP_HANDLE (or role when it has
    none, e.g. the neuron); `advisor` names the Sol thread, so one caller can hold
    SEPARATE threads for separate advisors and never cross-pollute their context."""
    return f"{(caller or 'anon').strip()}|{(advisor or 'sol').strip()}"


def load_thread(caller: str, advisor: str) -> str | None:
    f = _threads_file()
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    row = data.get(thread_key(caller, advisor))
    return (row or {}).get("thread_id") if isinstance(row, dict) else None


def save_thread(caller: str, advisor: str, thread_id: str, workdir: str) -> None:
    """Persist (caller, advisor) -> thread_id atomically. Last-writer-wins per
    key; keys are per-caller so concurrent shells rarely collide."""
    if not thread_id:
        return
    f = _threads_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            data = {}
    key = thread_key(caller, advisor)
    prior = data.get(key) if isinstance(data.get(key), dict) else {}
    data[key] = {
        "thread_id": thread_id,
        "workdir": workdir,
        "created_at": prior.get("created_at") or _now_iso(),
        "last_used": _now_iso(),
    }
    # F38#8: a UNIQUE temp name per writer — the old shared `.json.tmp`
    # meant two concurrent finishers raced the same file (one replace wins,
    # the other loses its key or hits FileNotFoundError AFTER a paid,
    # successful provider turn). Last-writer-wins per whole-file stays the
    # accepted model (keys are per-caller, collisions rare); losing a
    # last_used refresh is harmless, losing the RESULT is not — callers
    # additionally wrap this in try/except (run_sol) so persistence can
    # never fail the turn.
    tmp = f.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── argv construction (PURE) ─────────────────────────────────────────────────
_SANDBOX_VALUES = ("read-only", "workspace-write", "danger-full-access")


def build_argv(
    codex: str,
    *,
    prompt: str,
    workdir: str,
    sandbox: str,
    last_message_file: str,
    images: list[str] | None = None,
    resume_thread: str | None = None,
    effort: str | None = None,
    model: str | None = None,
) -> list[str]:
    """The complete, landmine-safe argv for one Sol turn. PURE — no IO.

    Fresh turn:   codex exec <globals> [-i img... --] -- <prompt>
    Resume turn:  codex exec <globals> resume [-i img]* -- <thread_id> <prompt>

    Globals (exec-level, BEFORE any subcommand): --skip-git-repo-check, -C, -s,
    --json, --color never, -o, and an optional -c model_reasoning_effort=. The
    prompt is ALWAYS the last positional behind `--` so a leading '-' is safe.
    On a FRESH turn `-i` is variadic and MUST be terminated by `--`; on RESUME
    `-i` is per-flag and attaches to the post-resume prompt, so it sits AFTER the
    `resume` subcommand.
    """
    if sandbox not in _SANDBOX_VALUES:
        raise SolBridgeError(
            f"sandbox must be one of {_SANDBOX_VALUES}, got {sandbox!r}")
    imgs = [i for i in (images or []) if i]

    argv = [codex, "exec", "--skip-git-repo-check",
            "-C", workdir, "-s", sandbox, "--json", "--color", "never",
            "-o", last_message_file]
    # F38#1: the registry's model pin actually reaches the CLI. Without -m
    # the CLI runs its own default while the bridge reports the pinned id —
    # every audit row and cost comparison then lies about the model.
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["-c", f"model_reasoning_effort={effort}"]

    if resume_thread:
        argv.append("resume")
        for img in imgs:                       # resume -i is per-flag, not variadic
            argv += ["-i", img]
        argv += ["--", resume_thread, prompt]
    else:
        if imgs:                               # fresh -i is variadic → terminate it
            argv.append("-i")
            argv += imgs
        argv += ["--", prompt]
    return argv


# ── event-stream parsing (PURE) ──────────────────────────────────────────────
@dataclass
class SolRun:
    """The structured result of one Sol turn. `ok` is the ONLY thing a caller
    must branch on: False means surface a blocker upward and STOP (do not retry).
    """
    ok: bool
    exit_code: int
    thread_id: str | None
    agent_messages: list[str] = field(default_factory=list)
    file_changes: list[str] = field(default_factory=list)
    last_message: str = ""
    error: str | None = None
    raw_path: str | None = None
    argv: list[str] = field(default_factory=list)


def parse_events(jsonl_text: str) -> dict:
    """Best-effort structured read of the `--json` event stream. Defensive by
    design: the CLI exposes no stable schema and this must never raise on a line
    it does not recognise. Extracts the thread id, agent message texts, and any
    file-change item paths, and flags the code-mode-host router error (which
    means the WRONG binary reached Sol — a talk-but-cannot-write failure)."""
    thread_id: str | None = None
    messages: list[str] = []
    files: list[str] = []
    host_error = False

    def _walk_for_text(obj) -> str | None:
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            for k in ("text", "message", "content"):
                v = obj.get(k)
                s = _walk_for_text(v)
                if s:
                    return s
        if isinstance(obj, list):
            parts = [p for p in (_walk_for_text(x) for x in obj) if p]
            return "\n".join(parts) if parts else None
        return None

    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "failed to spawn code-mode host" in line:
            host_error = True
        if not (line.startswith("{") or line.startswith("[")):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        # thread id: seen on thread.started; accept it wherever it appears
        for k in ("thread_id", "threadId", "session_id", "sessionId"):
            if isinstance(ev.get(k), str) and not thread_id:
                thread_id = ev[k]
        nested = ev.get("thread") if isinstance(ev.get("thread"), dict) else None
        if nested and isinstance(nested.get("id"), str) and not thread_id:
            thread_id = nested["id"]

        etype = str(ev.get("type", ""))
        item = ev.get("item") if isinstance(ev.get("item"), dict) else None
        if "item" in etype and item is not None:
            itype = str(item.get("type", "") or item.get("item_type", ""))
            if any(m in itype for m in ("message", "agent", "assistant")):
                txt = _walk_for_text(item)
                if txt:
                    messages.append(txt)
            if any(m in itype for m in ("file", "patch", "apply")):
                for pk in ("path", "file", "target"):
                    if isinstance(item.get(pk), str):
                        files.append(item[pk])
        elif any(m in etype for m in ("agent_message", "assistant")):
            txt = _walk_for_text(ev)
            if txt:
                messages.append(txt)

    return {"thread_id": thread_id, "messages": messages,
            "files": files, "host_error": host_error}


# ── the one impure entrypoint ────────────────────────────────────────────────
def run_sol(
    *,
    prompt: str,
    workdir: str,
    sandbox: str,
    caller: str,
    advisor: str = "sol",
    images: list[str] | None = None,
    effort: str | None = None,
    new_thread: bool = False,
    timeout_secs: float | None = None,
    model: str | None = None,
) -> SolRun:
    """Run ONE Sol turn and return a structured SolRun. Resumes the sticky thread
    for (caller, advisor) when one exists (unless `new_thread`), else starts a
    fresh thread and persists its id. NEVER retries and NEVER shrinks the request:
    a non-zero exit, a timeout, or the code-mode-host router error each return
    `ok=False` with `error` set, for the tool to surface upward immediately.

    Raises SolBridgeError only for PRECONDITIONS the caller can fix (missing
    binary, oversized prompt, bad sandbox) — the tool converts those to a
    TOOL_PRECONDITION. A genuine Sol/quota FAILURE is a returned SolRun(ok=False),
    not an exception.
    """
    if not prompt or not prompt.strip():
        raise SolBridgeError("prompt is empty — nothing to send to Sol.")
    if len(prompt.encode("utf-8")) > _PROMPT_MAX_BYTES:
        raise SolBridgeError(
            f"prompt is {len(prompt.encode('utf-8'))} bytes; the CLI passes it "
            f"as one argv element and Windows caps the command line near 32 KB. "
            f"Keep the brief under {_PROMPT_MAX_BYTES} bytes (link large context "
            f"as files Sol can read from its -C workspace instead).")
    for img in (images or []):
        if not Path(img).is_file():
            raise SolBridgeError(
                f"image {img!r} does not exist — attaching is the ONLY way an "
                f"image reaches Sol (citing a path in the prompt is a no-op), so "
                f"a missing file is a hard error, not a warning.")

    codex = str(resolve_codex_binary())
    resume_thread = None if new_thread else load_thread(caller, advisor)

    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    # F38#3: PER-INVOCATION output files. The old fixed `.sol-last-message
    # .txt` was shared by every call in the same delegate workdir, so a
    # concurrent (or stale prior) turn's answer could be read back as THIS
    # call's result — the worst kind of wrong (a plausible answer to a
    # different question). Unique names isolate the read; stale files also
    # can't survive because the destination never pre-exists.
    run_tag = f"{os.getpid()}-{time.time_ns()}"
    last_msg = work / f".sol-last-message-{run_tag}.txt"
    last_msg.unlink(missing_ok=True)
    # bound the per-run artifact accumulation: sweep run files older than
    # 7 days (best-effort; the raw stream is evidence, not a store).
    _cutoff = time.time() - 7 * 24 * 3600
    for pat in (".sol-last-message-*.txt", ".sol-run-*.jsonl"):
        for old in work.glob(pat):
            try:
                if old.stat().st_mtime < _cutoff:
                    old.unlink()
            except OSError:
                pass

    argv = build_argv(
        codex, prompt=prompt, workdir=str(work), sandbox=sandbox,
        last_message_file=str(last_msg), images=images,
        resume_thread=resume_thread, effort=effort, model=model)

    timeout = timeout_secs or float(os.environ.get(_TIMEOUT_ENV, _TIMEOUT_DEFAULT))
    raw = ""
    try:
        proc = subprocess.run(
            argv, stdin=subprocess.DEVNULL,     # empty stdin => instant EOF
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # merge: host error is on stderr
            timeout=timeout, text=True, encoding="utf-8", errors="replace")
        raw = proc.stdout or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        raw = (e.stdout or "") if isinstance(e.stdout, str) else ""
        return SolRun(
            ok=False, exit_code=124, thread_id=resume_thread, argv=argv,
            error=(f"Sol turn exceeded {timeout:.0f}s and was killed. This is a "
                   f"first-class blocker: surface it upward, do NOT retry-loop "
                   f"(Sol spend bills the user's ChatGPT plan quota)."))
    except (OSError, ValueError) as e:
        return SolRun(ok=False, exit_code=-1, thread_id=resume_thread, argv=argv,
                      error=f"could not launch codex ({e}).")

    # persist the raw stream as evidence (stdout+stderr merged; per-run
    # name — F38#3, same isolation as the last-message file)
    raw_path = work / f".sol-run-{run_tag}.jsonl"
    try:
        raw_path.write_text(raw, encoding="utf-8")
    except OSError:
        raw_path = None

    parsed = parse_events(raw)
    tid = parsed["thread_id"] or resume_thread
    last_message = ""
    if last_msg.is_file():
        try:
            last_message = last_msg.read_text(encoding="utf-8").strip()
        except OSError:
            last_message = ""

    if parsed["host_error"]:
        return SolRun(
            ok=False, exit_code=exit_code, thread_id=tid, argv=argv,
            raw_path=str(raw_path) if raw_path else None,
            agent_messages=parsed["messages"], file_changes=parsed["files"],
            last_message=last_message,
            error=("Sol reached but the code-mode host failed to spawn — the "
                   "WRONG codex binary was used (talk-but-cannot-write). No file "
                   "was written. This is a bridge bug, not a Sol failure; report "
                   "it — do not retry."))

    if exit_code != 0:
        return SolRun(
            ok=False, exit_code=exit_code, thread_id=tid, argv=argv,
            raw_path=str(raw_path) if raw_path else None,
            agent_messages=parsed["messages"], file_changes=parsed["files"],
            last_message=last_message,
            error=(f"codex exited {exit_code}. Treat as a first-class blocker "
                   f"(the CLI exposes no rate-limit telemetry, so a quota cap is "
                   f"only visible on failure): surface it upward immediately, do "
                   f"NOT retry-loop, grind, or silently shrink the request. "
                   f"Last message: {last_message[:400]!r}"))

    if tid:
        # F38#8: stickiness persistence is best-effort — a filesystem race
        # here must NEVER turn a paid, successful provider turn into an
        # exception. Worst case the next call starts a fresh thread.
        try:
            save_thread(caller, advisor, tid, str(work))
        except OSError:
            pass

    return SolRun(
        ok=True, exit_code=0, thread_id=tid, argv=argv,
        raw_path=str(raw_path) if raw_path else None,
        agent_messages=parsed["messages"], file_changes=parsed["files"],
        last_message=last_message)
