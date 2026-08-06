"""Minimal PTY launcher — ported launch mechanics only.

Source: evolving-deep-agent/wrapper/edp_shell.py (Plan W / ADR-016).
Ported: claude-bin resolution, ConPTY spawn, `❯` TUI-ready detection,
single activation write, alive/terminate. NOT ported (old protocol,
replaced by edp-broker + activator slash commands): the human stdio
proxy, meta parser, old BrokerClient WS, HTTP-injection POC.

A pool-spawned shell is headless: it talks to the system via the
edp-broker MCP tools (driven by its `/agentic-plan` or `/worker`
activator), NOT via PTY-injected broker messages. This launcher only
needs to: start claude in a real terminal, send the one activation
line, and let the pool poll liveness / terminate.
"""

import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path

from .proctree import kill_process_tree

logger = logging.getLogger(__name__)

# S3b: extracted launch-mechanic constants (ported magic values).
_PROMPT_READY = "❯"  # ❯ — appears once claude's keyboard handler is live
# DESIGN-v7 fix C (verified live 2026-07-12): Claude Code v2.1.207's
# fullscreen TUI renders a plain '>' prompt, NOT '❯' — so the single-glyph
# marker above timed out on every HEALTHY v2 shell. A bare '>' is far too
# common in drained output to be a marker itself; instead match strings the
# v2 boot screen prints exactly once, observed live: the input-hint line
# ("shift+tab to cycle") and the placeholder prompt ('Try "'). '❯' is KEPT
# for older/other TUI builds — any one marker suffices.
_READY_MARKERS = (_PROMPT_READY, "shift+tab to cycle", 'Try "')
# The FIRST run under a fresh CLAUDE_CONFIG_DIR shows the Bypass Permissions
# acceptance dialog BEFORE the TUI. The pool must NOT answer it (accepting a
# permissions bypass is the operator's deliberate one-time act, never an
# automated keystroke) — but a ready-timeout error must SAY the dialog is
# what the shell is stuck on, so the operator knows the fix. Both fragments
# must appear; either alone is too common in ordinary output.
_BYPASS_DIALOG_FRAGMENTS = ("bypass", "accept")
# Rolling tail kept for marker matching: a multi-char marker can straddle a
# PTY read boundary, so match against the last N chars, not per-chunk.
_MARKER_TAIL_CHARS = 512
_READ_SIZE = 4096
_DEFAULT_COLS = 120
_DEFAULT_ROWS = 30
_SUBMIT_DELAY_ENV = "EDP_SUBMIT_DELAY_MS"
_SUBMIT_DELAY_DEFAULT_MS = "150"
_READY_TIMEOUT_ENV = "EDP_READY_TIMEOUT_SECS"
_READY_TIMEOUT_DEFAULT = 30.0


def _ready_timeout_default() -> float:
    """The wait_ready window when the caller passes none. Env-tunable so an
    operator on a slow host (or a test that WANTS a fast timeout) can move
    it without a code change; garbage degrades to the default."""
    try:
        return float(os.environ.get(
            _READY_TIMEOUT_ENV, str(_READY_TIMEOUT_DEFAULT)))
    except ValueError:
        return _READY_TIMEOUT_DEFAULT

# W15 (DESIGN-v6): the pool's dedicated Claude config dir. A pool-spawned
# headless shell must NOT read or write the operator's personal ~/.claude
# store (skills, memory, settings) — it needs its own clean, checked-in
# config so a spawn never pollutes the user's foreground install. This
# file is at <repo>/src/edp_pool/pty_launcher.py → parents[2] == <repo>,
# self-located exactly like main.py's _root so a clone pins its OWN
# skeleton, never a stray inherited path.
_CLAUDE_POOL_CONFIG_DIR = Path(__file__).resolve().parents[2] / ".claude-pool"


def resolve_claude_bin(override: str | None = None) -> str:
    """override → EDP_CLAUDE_BIN → which → npm .cmd shim → bare 'claude'."""
    if override:
        return override
    env_bin = os.environ.get("EDP_CLAUDE_BIN")
    if env_bin:
        return env_bin
    resolved = shutil.which("claude")
    if not resolved:
        return "claude"
    if resolved.lower().endswith((".cmd", ".bat")):
        cand = (
            Path(resolved).parent
            / "node_modules" / "@anthropic-ai" / "claude-code"
            / "bin" / "claude.exe"
        )
        return str(cand) if cand.exists() else resolved
    return resolved


# --- W14 (DESIGN-v6): claude.exe auto-update guard --------------------------
# Claude Code's auto-update intermittently leaves bin/claude.exe as a
# ~500-byte stub with unfinished npm shims (.claude*-TEMP), killing every
# subsequent pool spawn (FileNotFoundError / WinError 2). The repair is
# fully mechanical — copy the full ~219MB platform binary from the local
# versions cache over the stub and finish the interrupted npm renames — so
# it is encoded HERE as a pool function (code, not an LLM ops task): the
# neuron never runs Bash repair, it only relays a refusal (o7: the guard
# REFUSES + EXPLAINS, it never rewrites output).
_MIN_HEALTHY_BIN_BYTES = 1_000_000  # ~1MB; a healthy claude.exe is ~219MB,
#                                     a broken auto-update stub is ~500B.
_VERSIONS_CACHE_ENV = "EDP_CLAUDE_VERSIONS_CACHE"


class ClaudeInstallError(RuntimeError):
    """Refuse-and-explain: the resolved claude binary is a broken
    auto-update stub and self-repair could not complete. Raised PRE-spawn
    so the pool never launches a doomed shell; the message NAMES the fix
    (restore from the versions cache / `python -m edp_pool.doctor`) so the
    neuron only relays it — it must NOT fix the environment itself."""


def _anthropic_dir(claude_bin: str) -> Path | None:
    """The `node_modules/@anthropic-ai` dir the install lives under, if the
    resolved bin sits in an npm layout (…/@anthropic-ai/claude-code/bin/
    claude.exe). Used to locate both the versions-cache source binary and
    leftover `.claude*-TEMP` staging shims. None for a bare-PATH name."""
    for parent in Path(claude_bin).resolve().parents:
        if parent.name == "@anthropic-ai":
            return parent
    return None


def find_temp_shims(claude_bin: str) -> list[Path]:
    """Leftover `.claude*-TEMP` npm staging entries beside the install —
    the fingerprint of an interrupted auto-update."""
    adir = _anthropic_dir(claude_bin)
    if adir is None or not adir.is_dir():
        return []
    return sorted(adir.glob(".claude*-TEMP"))


def claude_bin_needs_repair(claude_bin: str) -> bool:
    """Health check: True when the resolved binary is a sub-1MB stub (or is
    missing inside a known npm layout) OR an interrupted-update
    `.claude*-TEMP` shim sits alongside it. A path that is not a file and
    not inside an npm layout (e.g. a bare 'claude' resolved off PATH) is
    NOT flagged — there is nothing to size-check and that is a different,
    healthy scenario."""
    p = Path(claude_bin)
    try:
        if p.is_file():
            if p.stat().st_size < _MIN_HEALTHY_BIN_BYTES:
                return True
        elif _anthropic_dir(claude_bin) is not None:
            # bin file is gone but we know the npm layout → broken update
            return True
    except OSError:
        return False
    return bool(find_temp_shims(claude_bin))


def _versions_cache_candidates(claude_bin: str) -> list[Path]:
    """Where the full ~219MB platform binary may live, to copy over a stub,
    most-preferred first: an explicit EDP_CLAUDE_VERSIONS_CACHE override
    (a dir or a direct file), then the npm platform package
    (@anthropic-ai/claude-code-win32-x64/claude.exe) nested under or hoisted
    beside claude-code, then any `.claude-code-*` staging dir."""
    name = Path(claude_bin).name  # claude.exe
    cands: list[Path] = []
    override = os.environ.get(_VERSIONS_CACHE_ENV)
    if override:
        op = Path(override)
        cands.append(op if op.is_file() else op / name)
    adir = _anthropic_dir(claude_bin)
    if adir is not None:
        plat = "claude-code-win32-x64"
        cands.append(adir / "claude-code" / "node_modules"
                     / "@anthropic-ai" / plat / name)
        cands.append(adir / plat / name)
        for staging in sorted(adir.glob(".claude-code-*")):
            cands.append(staging / "node_modules" / "@anthropic-ai"
                         / plat / name)
    return cands


def _first_healthy_source(claude_bin: str) -> Path | None:
    for c in _versions_cache_candidates(claude_bin):
        try:
            if c.is_file() and c.stat().st_size >= _MIN_HEALTHY_BIN_BYTES:
                return c
        except OSError:
            continue
    return None


def _refusal_message(claude_bin: str, reason: str) -> str:
    return (
        f"claude.exe stub detected at {claude_bin}; auto-repair failed: "
        f"{reason}. The pool will NOT spawn on a broken binary. Fix: run "
        "`python -m edp_pool.doctor` (or the panel's doctor button) to "
        "restore the binary from the versions cache, or reinstall Claude "
        "Code. The neuron should relay this — it must NOT run Bash repair."
    )


def _finish_temp_renames(claude_bin: str) -> None:
    """Best-effort: complete the npm rename an interrupted update left
    half-done — strip `-TEMP` from staged `.claude*-TEMP` entries. Never
    raises: cleanup failure must not fail an otherwise-good restore."""
    for shim in find_temp_shims(claude_bin):
        final = shim.with_name(shim.name[: -len("-TEMP")])
        try:
            if not final.exists():
                shim.rename(final)
            elif shim.is_dir():
                shutil.rmtree(shim, ignore_errors=True)
            else:
                shim.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "W14: could not finish -TEMP rename for %s", shim)


def repair_claude_install(claude_bin: str) -> str:
    """The known mechanical repair, encoded as a pool function (NOT an LLM
    ops task): restore a working claude binary over a stubbed bin from the
    local versions cache and finish any interrupted npm `-TEMP` renames.

    Direct copy is BY DESIGN here (d5): pty_launcher's file writes do NOT
    route through atomic.py — this is a binary restore, not an object-state
    write.

    Raises ClaudeInstallError (naming the fix) when the versions cache has
    no usable source binary, the copy fails, or the bin is still unhealthy
    afterward — the pool then REFUSES the spawn."""
    source = _first_healthy_source(claude_bin)
    if source is None:
        raise ClaudeInstallError(_refusal_message(
            claude_bin,
            f"no healthy claude binary found in the versions cache (looked "
            f"under ${_VERSIONS_CACHE_ENV} and the npm platform package)"))
    dest = Path(claude_bin)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    except OSError as exc:
        raise ClaudeInstallError(_refusal_message(
            claude_bin, f"copy from {source} failed: {exc}")) from exc
    _finish_temp_renames(claude_bin)
    if claude_bin_needs_repair(claude_bin):
        raise ClaudeInstallError(_refusal_message(
            claude_bin, "binary still unhealthy after restore"))
    logger.warning("W14: repaired stubbed claude binary at %s from %s",
                   dest, source)
    return claude_bin


def ensure_claude_healthy(claude_bin: str) -> str:
    """Pre-spawn gate (W14): if the resolved binary is a broken auto-update
    stub, attempt the encoded repair; on repair failure REFUSE the spawn
    with a self-healing message (ClaudeInstallError) — never silently
    proceed. Returns the (healthy) bin path."""
    if not claude_bin_needs_repair(claude_bin):
        return claude_bin
    logger.warning(
        "W14: claude binary at %s looks stubbed/incomplete — attempting "
        "auto-repair", claude_bin)
    return repair_claude_install(claude_bin)


def build_argv(claude_bin: str, extra: list[str] | None,
               skip_permissions: bool = False,
               model: str | None = None,
               defaults: dict | None = None) -> list[str]:
    """claude argv. `--dangerously-skip-permissions` is added ONLY when
    `skip_permissions=True`.

    W12 `defaults`: the pool-side `spawn_defaults.json` (see
    `spawn_defaults.py`), loaded from disk when None. It supplies `model` when
    the CALLER passed none — an explicit per-action tier always wins over the
    panel's default, because the caller knows something the panel does not.
    `skip_permissions` is NOT and never will be readable from that file; it
    stays a function of spawn mode + the operator's own env.

    It is REQUIRED for HEADLESS shells — there's no window for anyone to
    approve a permission prompt, so without it the shell hangs on its
    first Bash call forever. It is NOT needed for VISIBLE `monitor` shells:
    the operator can click-approve right in the window (and choose "always
    allow" per session). So monitor shells default to normal prompting —
    you keep oversight — and only opt into autonomy with
    `EDP_SKIP_PERMISSIONS=1`. Either way the PreToolUse guard hook still
    fires and blocks stack-nuking kills.

    s17 FA3 model-tiering (2026-06-07): `model` adds `--model <id>` so a
    spawned shell can run on a cheaper tier. When None (the default) NO
    `--model` flag is emitted → the host's default tier (Opus) — argv
    byte-identical to pre-FA3. Who passes one is the CALLER's business; this
    function only threads it. As of 2026-07-10 that is the worker dispatch on
    the one MEASURED tier (`("worker", "coding")` → `claude-sonnet-5`) and any
    caller that explicitly opts into a CANDIDATE tier. Everything else resolves
    to Opus and passes nothing.

    `--model` IS THE WHOLE OF WHAT THIS EMITS. There is no `--effort` flag and
    no thinking control here: both models think adaptively at CLI defaults, and
    `d53`'s `effort = medium` is wired through `.claude/settings.json`
    (`effortLevel`), not through argv. Do not add an inert field to a tier table
    to express one — model/effort/thinking belong to the Claude Code
    settings+env surface."""
    from .spawn_defaults import load_spawn_defaults
    d = load_spawn_defaults() if defaults is None else defaults
    flag = ["--dangerously-skip-permissions"] if skip_permissions else []
    model = model or d.get("model")
    model_flag = ["--model", model] if model else []
    return [claude_bin, *flag, *model_flag, *(extra or [])]


def build_session_args(
    claude_session: str | None, resume_session: str | None
) -> list[str]:
    """Specialization vision phase 5 (2026-05-22): the claude-CLI flags
    for snapshot/branch. Empirically verified:
      - fresh, pinned id:   --session-id <new>
      - branch a base:      --resume <base> --session-id <fork>
                            --fork-session   (forks base into the KNOWN
                            fork id; base stays pristine, context loads)
      - branch, auto id:    --resume <base> --fork-session
    `--session-id` with `--resume` REQUIRES `--fork-session` (the CLI
    rejects the pair otherwise — verified live)."""
    if resume_session and claude_session:
        return ["--resume", resume_session,
                "--session-id", claude_session, "--fork-session"]
    if resume_session:
        return ["--resume", resume_session, "--fork-session"]
    if claude_session:
        return ["--session-id", claude_session]
    return []


# Pool role string → the actual activator slash command. NOT f"/{role}":
# the planner's command is `/agentic-plan` (the proven concept's name),
# not `/planner`. Sending `/planner` made the planner shell print
# "Unknown command: /planner" and idle → neuron deadlocked on `wait`.
_ROLE_ACTIVATOR = {
    "planner": "/agentic-plan",
    "worker": "/worker",
    "neuron": "/neuron",
    # Team-architecture Phase 6 (2026-05-21): externality shells.
    # ("critic" retired in v2.4 — replaced by the reviewer fork below.)
    "goal_keeper": "/goal-keeper",
    "pattern_observer": "/pattern-observer",
    # Specialization vision phase 4 (2026-05-22): SME self-train shell.
    "specialist": "/specialist",
    # v2.2 (2026-05-22): per-decision interrogator.
    "curiosity": "/curiosity",
    # v2.4 (2026-05-22): recipe-end domain reviewer fork (replaces critic).
    "reviewer": "/reviewer",
}


def activation_text(role: str) -> str:
    """The single line written after readiness: the role's slash command.
    The activator then reads EDP_ROLE/EDP_HANDLE/EDP_BROKER_URL from env
    and drives itself via the edp-broker MCP tools (our design).

    Unmapped role falls back to f"/{role}" so a wiring mistake fails
    loudly ("Unknown command") rather than silently mis-activating."""
    return _ROLE_ACTIVATOR.get(role, f"/{role}")


_STEP_SUFFIX_RE = re.compile(r"-s\d+$")


def _recipe_id_from_handle(handle: str) -> str:
    """Best-effort recipe_id from a spawn handle, for OTel correlation.
    planner handle = `<recipe_id>:<step_id>`; worker handle =
    `<plan_id>:<action_id>` where plan_id = `<recipe_id>-<step_id>`. Take
    the head (before the first ':'), then strip a trailing `-s<N>` step
    suffix. recipe_ids end in a 6-hex suffix (never `-s<digits>`), so this
    is unambiguous. Non-recipe handles (curiosity-<uuid>, …) pass through
    unchanged — fine, they group by their own id."""
    head = handle.split(":", 1)[0]
    return _STEP_SUFFIX_RE.sub("", head)


def _shell_otel_env(role: str, handle: str, base: dict) -> dict:
    """OTel for spawned shells (FSM-RESPONSIBILITY follow-up, 2026-05-31).
    Each interactive `claude` shell exports its OWN token-attributed trace
    tree (the `claude_code.interaction → llm_request` span waterfall, with
    per-request input/output/cache token counts) to the operator's
    collector — so a token burn is *measured*, not guessed.

    Interactive shells export fine; they only ignore inbound TRACEPARENT,
    so spans don't auto-nest under a parent. We compensate with per-shell
    `OTEL_RESOURCE_ATTRIBUTES` (role / handle / derived recipe_id) so the
    backend groups a recipe's whole fleet by attribute instead of nesting.

    Gated by `EDP_SHELL_OTEL` (default ON). Every value respects a
    pre-set override (the operator can redirect the endpoint or disable);
    defaults target the Phoenix collector on :6006. Export failures are
    non-fatal in the OTel SDK, so a down collector never breaks a spawn."""
    if base.get("EDP_SHELL_OTEL", "1").lower() not in ("1", "true", "yes"):
        return {}
    out = {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",  # the span tree w/ tokens
        "OTEL_TRACES_EXPORTER": base.get("OTEL_TRACES_EXPORTER", "otlp"),
        "OTEL_METRICS_EXPORTER": base.get("OTEL_METRICS_EXPORTER", "none"),
        "OTEL_LOGS_EXPORTER": base.get("OTEL_LOGS_EXPORTER", "none"),
        "OTEL_EXPORTER_OTLP_PROTOCOL": base.get(
            "OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": base.get(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "http://localhost:6006/v1/traces"),
    }
    # resource attributes: clean keys for correlation-by-attribute. The
    # handle carries a ':' — sanitize for the W3C-baggage value format.
    # `openinference.project.name` routes ALL shell traces to a dedicated
    # Phoenix PROJECT (default "edp-shells") instead of dumping them into
    # "default" — Phoenix routes by THIS attribute, not service.name.
    # Within it, filter by edp.recipe_id / edp.role.
    rid = _recipe_id_from_handle(handle)
    project = base.get("EDP_OTEL_PROJECT", "edp-shells")
    attrs = [f"openinference.project.name={project}",
             f"service.name=edp-{role}", f"edp.role={role}",
             f"edp.handle={handle.replace(':', '_')}"]
    if rid:
        attrs.append(f"edp.recipe_id={rid}")
    prior = base.get("OTEL_RESOURCE_ATTRIBUTES")
    out["OTEL_RESOURCE_ATTRIBUTES"] = (
        prior + "," + ",".join(attrs) if prior else ",".join(attrs))
    return out


def build_env(session_id: str, role: str, handle: str,
              broker_url: str | None, *,
              pool_url: str | None = None,
              agent_home: str | None = None,
              log_dir: str | None = None,
              defaults: dict | None = None) -> dict:
    """Our env contract (NOT the old protocol). The activator reads these
    and drives itself via the edp-broker MCP tools.

    2026-05-28 stack-pinning fix: the spawned shell's ENTIRE stack is
    pinned to the POOL's own config — never inherited piecemeal from the
    launching shell. Before this, only EDP_BROKER_URL was overridden, so
    a clone (eda-base3) whose pool was started from a shell still carrying
    eda-base's env spawned shells that talked to the OLD pool (EDP_POOL_URL
    inherited), loaded the OLD skills (EDP_AGENT_HOME inherited → wrong
    cwd/.mcp.json), and logged to the OLD dir (EDP_LOG_DIR inherited) —
    while replying on the NEW broker. A mixed stack: pool_close_self hit
    the wrong pool, liveness lied, follow-ups dead-lettered. Now all four
    are set explicitly so the shell runs entirely on the pool's stack.

    W12 `defaults`: the pool-side `spawn_defaults.json`, loaded from disk when
    None. It may set `rtk`. It may NOT set `EDP_SKIP_PERMISSIONS` — see
    `spawn_defaults.BANNED_KEYS`."""
    from .spawn_defaults import load_spawn_defaults
    d = load_spawn_defaults() if defaults is None else defaults
    env = os.environ.copy()
    env["EDP_SPAWN_SESSION_ID"] = session_id  # correlation (kept from old)
    env["EDP_ROLE"] = role
    env["EDP_HANDLE"] = handle
    # 2026-07-21: which HARNESS this shell runs under. Behaviour that is an
    # affordance of one harness and a defect in the other keys off this
    # rather than sniffing claude-only env keys. build_env is the CLAUDE
    # spawner's path; build_env_opencode overrides it after calling us.
    # Consumed MCP-side by _park_hint (park/resume is opencode-only: there a
    # park keeps the TUI window, here it closes the shell outright).
    env["EDP_HARNESS"] = "claude"
    # W14: prevent, don't just repair — a mid-flight auto-update must not
    # break a running planner/worker (it also invalidates the prompt cache
    # on resume). Updates then happen only when the USER updates their own
    # foreground install; the pre-spawn health check catches any residue.
    env["DISABLE_AUTOUPDATER"] = "1"
    # W15 (DESIGN-v6): config-dir pin. Claude Code reads/writes its whole
    # user store (skills, memory, settings) from CLAUDE_CONFIG_DIR,
    # defaulting to ~/.claude. Left inherited, a headless pool spawn would
    # read the operator's personal store AND write memory/state back into
    # it — the shadow-store leak this kills. Pin every spawn to the repo's
    # checked-in .claude-pool skeleton so the pool runs entirely on its own
    # config, never the user's. An explicit EDP_CLAUDE_CONFIG_DIR wins (the
    # operator's intentional override knob), matching the stack-pin style
    # where every pinned value respects a deliberate pre-set override.
    env["CLAUDE_CONFIG_DIR"] = env.get(
        "EDP_CLAUDE_CONFIG_DIR", str(_CLAUDE_POOL_CONFIG_DIR))
    # W6.1 (gated wiring half of the reactive-toolkit rollout): stamp
    # EDP_RTK into the spawned shell only when the pool's own env/config
    # requests it — read from `base` exactly like EDP_SHELL_OTEL below,
    # DEFAULT OFF. While off nothing is added, so a normal spawn stays
    # byte-identical to today; flipping EDP_RTK=1 in the pool's env reaches
    # every fresh spawn with NO further code change.
    #
    # W12: the pool-side spawn_defaults.json may set `rtk` explicitly, and when
    # it does it WINS over the ambient env — the panel toggle would be a lie
    # otherwise (flip it on, and an inherited EDP_RTK=0 silently overrides).
    # Absent from the file ⇒ the env decides, exactly as before.
    rtk_default = d.get("rtk")
    if rtk_default is None:
        rtk_on = str(env.get("EDP_RTK", "0")).lower() in ("1", "true", "yes")
    else:
        rtk_on = bool(rtk_default)
    if rtk_on:
        env["EDP_RTK"] = "1"
    else:
        env.pop("EDP_RTK", None)
    # Context-diet Phase 6 (2026-07-30): ARM the worker-close-nudge Stop hook
    # for spawned shells. The hook shipped in PROBE mode (log-only) with two
    # dead-guard bugs (wrong env var, wrong plan path) — all three are fixed;
    # the guard itself stays narrow (role=worker + own action terminal +
    # block cap 2 + fail-open). An explicit pre-set 0 wins (operator knob).
    env.setdefault("EDP_WORKER_CLOSE_NUDGE", "1")
    # v7 WS4 (2026-08-06): outcome-lineage write gates ON for spawned shells
    # — the compiled boot docs teach `serves`; a NEW step/action naming no
    # outcome is refused (legacy objects unaffected). Pre-set 0 wins.
    env.setdefault("EDP_V7_WRITE_GATES", "1")
    # Phase 6: auto-compact safety net (operator request — ~350k). Treat the
    # model's 1M window as this many tokens for compaction purposes so a
    # spawned shell compacts early instead of dragging a bloated context to
    # the cliff. Per-role override via EDP_AUTO_COMPACT_WINDOW_<ROLE>, e.g.
    # EDP_AUTO_COMPACT_WINDOW_WORKER=250000; explicit pre-set wins; set the
    # generic knob to "0" to disable stamping entirely.
    # v7 WS4 (§2.4b): the SEAT REGISTRY (models.json at the agent home) is
    # the preferred source — per-seat auto_compact, one file, doctor-
    # validated. Env overrides still win (operator escape hatch); absent
    # registry / unmapped role falls back to the legacy 350000.
    _seat_acw = None
    try:
        from edp_contracts.seats import seat_for_role as _sfr
        _seat = _sfr(agent_home, role) if agent_home else None
        if _seat is not None:
            _seat_acw = str(_seat.auto_compact)
    except Exception:  # noqa: BLE001 — registry trouble never blocks a spawn
        _seat_acw = None
    _acw = env.get(f"EDP_AUTO_COMPACT_WINDOW_{role.upper()}") \
        or env.get("EDP_AUTO_COMPACT_WINDOW") or _seat_acw or "350000"
    if _acw != "0":
        env.setdefault("CLAUDE_CODE_AUTO_COMPACT_WINDOW", _acw)
    # v7 WS4 (§2.8) — HARD OUTPUT CAP per seat: only the neuron's gate
    # surfaces are read by a human; every other role's prose is written for
    # no reader, so the ceiling is enforced at the API level where no prompt
    # can exceed it. Registry-driven (models.json max_output); absent = no
    # stamp (legacy). Explicit pre-set wins (operator escape hatch).
    try:
        if _seat is not None and _seat.max_output is not None:
            env.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS",
                           str(_seat.max_output))
    except NameError:
        pass
    if broker_url:
        env["EDP_BROKER_URL"] = broker_url
    if pool_url:
        env["EDP_POOL_URL"] = pool_url
    if agent_home:
        env["EDP_AGENT_HOME"] = agent_home
    if log_dir:
        env["EDP_LOG_DIR"] = log_dir
    # OTel: every spawned shell exports its own token-attributed trace tree
    # to the operator's collector (Phoenix :6006 by default). Per-shell
    # resource attributes (role/handle/recipe_id) are the only piece the
    # pool can set — interactive shells don't inherit a parent trace.
    env.update(_shell_otel_env(role, handle, env))
    return env


class PtyLaunch:
    """One launched claude shell. Headless: PTY output is drained to a
    log so the process doesn't block on a full pipe; no human proxy."""

    def __init__(
        self,
        argv: list[str],
        env: dict,
        cwd: str | None = None,
        cols: int = _DEFAULT_COLS,
        rows: int = _DEFAULT_ROWS,
        ready_timeout: float | None = None,
        log_path: Path | None = None,
    ):
        self.argv = argv
        self.env = env
        self.cwd = cwd or os.getcwd()
        self.cols = cols
        self.rows = rows
        # None → the env-tunable default (30s). An explicit value wins.
        self.ready_timeout = (
            _ready_timeout_default() if ready_timeout is None
            else ready_timeout)
        self.log_path = log_path
        self._proc = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._drain: threading.Thread | None = None
        # DESIGN-v7 fix C: did the drain see the Bypass Permissions
        # acceptance dialog? Read by the spawner on a ready-timeout so the
        # error can NAME the cause. Detection only — the pool never answers
        # the dialog (see _BYPASS_DIALOG_FRAGMENTS).
        self._bypass_seen = False

    def spawn(self) -> None:
        from winpty import PtyProcess  # Windows-only; deferred import

        # W14: never launch on a broken auto-update stub. Self-repair the
        # resolved binary (argv[0]) or REFUSE with a self-healing message
        # (ClaudeInstallError). Defense-in-depth: the spawner gates the
        # shared resolved bin too — this also guards direct PtyLaunch use.
        ensure_claude_healthy(self.argv[0])
        self._proc = PtyProcess.spawn(
            self.argv,
            cwd=self.cwd,
            dimensions=(self.rows, self.cols),
            env=self.env,
        )
        self._drain = threading.Thread(
            target=self._drain_loop, name="edp-pool.pty-drain", daemon=True
        )
        self._drain.start()

    def _drain_loop(self) -> None:
        assert self._proc is not None
        fh = None
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            # Write a UTF-8 BOM on first creation so Windows PowerShell
            # 5.1 `Get-Content` auto-detects UTF-8 instead of rendering
            # box-drawing bytes (E2 94 80 …) as legacy-codepage mojibake
            # (â”€ â”‚). Ported from the old wrapper's log-encoding fix.
            if not self.log_path.exists():
                try:
                    self.log_path.write_bytes(b"\xef\xbb\xbf")
                except OSError:
                    pass
            fh = self.log_path.open("a", encoding="utf-8", errors="replace")
        tail = ""  # rolling window so a marker split across reads still hits
        try:
            while not self._stop.is_set():
                try:
                    data = self._proc.read(_READ_SIZE)
                except (EOFError, Exception):
                    break
                if not data:
                    if not self._proc.isalive():
                        break
                    # An empty read from a live process must NOT hot-loop:
                    # with a fake/quiet PTY this branch otherwise spins a
                    # full core per launch and starves the whole process
                    # (observed as a GIL-starved test suite). 10ms is
                    # invisible next to PTY latency.
                    time.sleep(0.01)
                    continue
                text = data if isinstance(data, str) else data.decode(
                    "utf-8", errors="replace"
                )
                tail = (tail + text)[-_MARKER_TAIL_CHARS:]
                low = tail.lower()
                # TUI keyboard handler is live (any one marker — see the
                # _READY_MARKERS rationale for why there are three).
                if not self._ready.is_set() and any(
                        m in tail for m in _READY_MARKERS):
                    self._ready.set()
                if not self._bypass_seen and all(
                        f in low for f in _BYPASS_DIALOG_FRAGMENTS):
                    self._bypass_seen = True
                if fh is not None:
                    fh.write(text)
                    fh.flush()
        finally:
            if fh is not None:
                fh.close()

    def wait_ready(self) -> bool:
        """Block until claude's TUI is keyboard-ready or timeout. Writing
        the activation before this returns risks a dropped keystroke."""
        if self.ready_timeout <= 0:
            return True
        return self._ready.wait(timeout=self.ready_timeout)

    @property
    def bypass_dialog_seen(self) -> bool:
        """True when the drain saw the Bypass Permissions acceptance dialog.
        Diagnosis for a ready-timeout, never an auto-accept trigger."""
        return self._bypass_seen

    def send_activation(self, text: str) -> None:
        """Single write: the role's task line. Submitted with a trailing
        CR (claude's Enter)."""
        assert self._proc is not None
        self._proc.write(text)
        delay_ms = float(
            os.environ.get(_SUBMIT_DELAY_ENV, _SUBMIT_DELAY_DEFAULT_MS)
        )
        time.sleep(delay_ms / 1000)
        self._proc.write("\r")  # claude's Enter — submits the activation

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.isalive()

    @property
    def pid(self) -> int | None:
        """OS pid of the spawned shell — captured so the pool can persist
        a process fingerprint and RE-ESTABLISH liveness after a restart
        (the in-memory PTY handle doesn't survive)."""
        return getattr(self._proc, "pid", None) if self._proc else None

    def terminate(self) -> None:
        # Close the WHOLE subtree this shell opened (MCP servers + rx
        # drivers), not just the root — orphaned python children were the
        # 2026-06-02 "198 shells" leak. Descendants first, then the root.
        self._stop.set()
        if self._proc is None or not self._proc.isalive():
            return
        try:
            kill_process_tree(self.pid)
        except Exception:
            pass
        try:
            self._proc.terminate(force=True)
        except Exception:
            pass
