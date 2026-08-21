"""The provider bridge engine — any external model as a deterministic tool.

WHY THIS EXISTS (v7 ruling, 2026-08-05). The framework runs 100% on Claude Code
shells; model diversity happens INSIDE the shells: frontier models author plans
and judgments, cheap external models execute bulk generation, review pre-screens,
cross-family consults, and adversarial challenges. sol_bridge.py proved the
pattern for one backend (the Codex CLI); this module generalizes it to a named
DELEGATE registry with two backend kinds, while keeping sol_bridge's discipline:

  * NEVER retries, NEVER grinds, NEVER silently shrinks a request. A failure is
    a returned BridgeRun(ok=False) for the tool to surface upward.
  * PURE where possible: config parsing, work-order assembly, payload building,
    route resolution, and cost estimation take no ctx and do no IO — unit-tested
    without ever touching a network or the codex binary.
  * Preconditions raise BridgeError (the tool layer converts to
    TOOL_PRECONDITION); genuine provider failures are returned, not raised.

BACKENDS
  cli   — the Codex CLI via sol_bridge.run_sol. Bills the user's ChatGPT plan
          quota (no API dollars). ALWAYS sandbox=read-only here: bridge
          delegates return TEXT; they never write files. (Asset authoring keeps
          its own dedicated path: sol_author_asset.)
  http  — any OpenAI-compatible chat-completions endpoint (OpenAI, DeepSeek,
          Mistral, Google-compat gateways, local servers) with the user's key
          from an env var. stdlib urllib only — no SDK sprawl.

CONTAINMENT (adversarial ruling). A delegate exists only inside one tool call's
request/response: no MCP surface, no broker access, no filesystem, no exec.
Challenge output is normalized to a FINDINGS structure — data for adjudication,
never an instruction stream. The broker-side kind allowlist for the adversary
sender identity lives with the kind registry, not here.

AUDIT. Every call appends one JSONL row (delegate, model, sizes, usage, cost
estimate, outcome) to `.bridge/audit-<scope>.jsonl` under the agent home — the
per-role cost accounting the budget machinery reads.
"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import sol_bridge

# ── configuration seams ──────────────────────────────────────────────────────

#: Path override for the delegate registry; default <EDP_AGENT_HOME>/.bridge.json
_CONFIG_ENV = "EDP_BRIDGE_CONFIG"

#: Wall-clock ceiling for one HTTP delegate turn (the CLI backend keeps
#: sol_bridge's own 900s default).
_HTTP_TIMEOUT_ENV = "EDP_BRIDGE_HTTP_TIMEOUT_SECS"
_HTTP_TIMEOUT_DEFAULT = 600.0

#: ~4 chars/token — the same estimator _bounds.py uses; good enough to refuse
#: an oversized work order BEFORE it is sent (never truncated silently).
_CHARS_PER_TOKEN = 4

#: The tool-call kinds a delegate can serve. `challenge` is the adversary.
KINDS = ("generate", "review", "consult", "challenge")

#: Challenge findings must land in this shape — data, never directives.
_CHALLENGE_CONTRACT = (
    "Respond ONLY with a JSON array of findings. Each finding: "
    '{"finding": <one-sentence defect claim>, "evidence": <why, concretely>, '
    '"severity": "low"|"medium"|"high", "target": <the id/part attacked>}. '
    "No prose outside the JSON. An empty array means you found nothing.")


class BridgeError(RuntimeError):
    """A precondition the engine refuses to proceed past (unknown delegate,
    oversized work order, missing key). Tool layer → TOOL_PRECONDITION."""


# ── delegate registry (PURE parsing; IO only in load_config) ─────────────────
@dataclass(frozen=True)
class Delegate:
    name: str
    backend: str                       # "cli" | "http"
    model: str                         # exact pinned id (doctrine: never aliases)
    effort: str | None = None          # medium is the fleet ruling default
    base_url: str | None = None        # http only
    api_key_env: str | None = None     # http only
    max_context_tokens: int = 250_000  # refuse oversized work orders up front
    max_output_tokens: int = 16_000
    price_in_per_mtok: float = 0.0     # 0.0 = subscription/plan quota (cli)
    price_out_per_mtok: float = 0.0
    # F34-h (2026-08-18, campaign R3 lesson): per-delegate wall-clock ceiling
    # for one CLI turn. None → sol_bridge's default (EDP_SOL_TIMEOUT_SECS,
    # 900s). A deliberately DEEP delegate (a repo-scale adversary) gets its
    # longer leash HERE, in config — a timeout is a config decision, never an
    # agent's whim. The right-sizing law still applies first: one artifact
    # per turn; a hunt that needs more than one turn is a multi-turn thread,
    # not a mega-turn.
    timeout_secs: float | None = None


def parse_config(raw: dict) -> tuple[dict[str, Delegate], dict[str, str]]:
    """PURE. `raw` is the decoded .bridge.json: {"delegates": {name: {...}},
    "routes": {"role:task_class": delegate_name}}. Validates hard — a bad
    registry entry is a config bug to fix now, not a runtime surprise later."""
    delegates: dict[str, Delegate] = {}
    for name, row in (raw.get("delegates") or {}).items():
        if not isinstance(row, dict):
            raise BridgeError(f"delegate {name!r}: entry must be an object")
        backend = row.get("backend")
        if backend not in ("cli", "http"):
            raise BridgeError(
                f"delegate {name!r}: backend must be 'cli' or 'http', "
                f"got {backend!r}")
        model = row.get("model")
        if not model or not isinstance(model, str):
            raise BridgeError(f"delegate {name!r}: 'model' (exact id) is required")
        if backend == "http" and not row.get("base_url"):
            raise BridgeError(f"delegate {name!r}: http backend needs 'base_url'")
        if backend == "http" and not row.get("api_key_env"):
            raise BridgeError(f"delegate {name!r}: http backend needs "
                              f"'api_key_env' (env var NAME, never the key itself)")
        delegates[name] = Delegate(
            name=name, backend=backend, model=model,
            effort=row.get("effort"),
            base_url=row.get("base_url"),
            api_key_env=row.get("api_key_env"),
            max_context_tokens=int(row.get("max_context_tokens", 250_000)),
            max_output_tokens=int(row.get("max_output_tokens", 16_000)),
            price_in_per_mtok=float(row.get("price_in_per_mtok", 0.0)),
            price_out_per_mtok=float(row.get("price_out_per_mtok", 0.0)),
            timeout_secs=(float(row["timeout_secs"])
                          if row.get("timeout_secs") else None),
        )

    routes: dict[str, str] = {}
    for key, target in (raw.get("routes") or {}).items():
        if key.startswith("_"):
            continue        # comment key (the _doc convention), not a route
        if target not in delegates:
            raise BridgeError(
                f"route {key!r} names unknown delegate {target!r} "
                f"(known: {sorted(delegates)})")
        routes[key] = target
    return delegates, routes


def config_path() -> Path:
    override = os.environ.get(_CONFIG_ENV, "").strip()
    if override:
        return Path(override)
    home = os.environ.get("EDP_AGENT_HOME") or os.getcwd()
    return Path(home) / ".bridge.json"


def load_config() -> tuple[dict[str, Delegate], dict[str, str]]:
    f = config_path()
    if not f.is_file():
        raise BridgeError(
            f"no bridge config at {f} — create .bridge.json with a 'delegates' "
            f"map (see docs) or set {_CONFIG_ENV}.")
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BridgeError(f"bridge config {f} unreadable: {e}") from e
    return parse_config(raw)


def route_for(role: str, task_class: str, routes: dict[str, str]) -> str | None:
    """PURE. Deterministic route lookup — `role:task_class`, then `role:*`,
    then None (= do not delegate). No agent ever chooses a model."""
    return routes.get(f"{role}:{task_class}") or routes.get(f"{role}:*")


# ── work-order assembly (PURE) ───────────────────────────────────────────────
def approx_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def build_work_order(*, task: str, context: str = "",
                     acceptance: str = "", kind: str = "generate") -> str:
    """PURE. One self-contained prompt: the delegate sees ONLY this — it has no
    tools and no way to ask follow-ups, so the caller must include everything
    (action fields, relevant file content, the spec-doc excerpt it selected)."""
    if kind not in KINDS:
        raise BridgeError(f"kind must be one of {KINDS}, got {kind!r}")
    if not task or not task.strip():
        raise BridgeError("task is empty — nothing to delegate.")
    parts = [f"# Task ({kind})", task.strip()]
    if context.strip():
        parts += ["# Context (complete — you cannot ask follow-ups)",
                  context.strip()]
    if acceptance.strip():
        parts += ["# Acceptance criteria (your output is judged against these)",
                  acceptance.strip()]
    if kind == "challenge":
        parts += ["# Output contract", _CHALLENGE_CONTRACT]
    elif kind == "review":
        parts += ["# Output contract",
                  "List concrete defects with evidence, then a one-line "
                  "verdict: PASS or FAIL(reasons). You are a pre-screen; a "
                  "senior reviewer adjudicates — be precise, not polite."]
    return "\n\n".join(parts)


def check_budget(delegate: Delegate, work_order: str) -> None:
    """Refuse an order that cannot fit the delegate's window — loudly, before
    any spend. Silent truncation is forbidden (CONTENT-payload doctrine)."""
    # F38#11: a CLI delegate ALSO has the 30KB argv cap (Windows command
    # line) — far tighter than any token window. Refuse here, in the
    # documented BridgeError shape, before a slot is taken or spend risked.
    if delegate.backend == "cli":
        from . import sol_bridge as _sb
        nbytes = len(work_order.encode("utf-8"))
        if nbytes > _sb._PROMPT_MAX_BYTES:
            raise BridgeError(
                f"work order is {nbytes} bytes; a CLI delegate passes it as "
                f"one argv element and Windows caps the command line near "
                f"32KB — keep it under {_sb._PROMPT_MAX_BYTES} bytes "
                f"(tighter context, or reference files the delegate can "
                f"read from its workspace).")
    need = approx_tokens(work_order) + delegate.max_output_tokens
    if need > delegate.max_context_tokens:
        raise BridgeError(
            f"work order ≈{approx_tokens(work_order)} tokens + "
            f"{delegate.max_output_tokens} output exceeds {delegate.name}'s "
            f"{delegate.max_context_tokens}-token window. Shrink the context "
            f"(reference fewer files / tighter spec excerpt) — the bridge never "
            f"truncates silently.")


# ── HTTP payload (PURE) ──────────────────────────────────────────────────────
def build_http_payload(delegate: Delegate, work_order: str) -> dict:
    payload = {
        "model": delegate.model,
        "messages": [{"role": "user", "content": work_order}],
        "max_tokens": delegate.max_output_tokens,
        "stream": False,
    }
    if delegate.effort:
        payload["reasoning_effort"] = delegate.effort
    return payload


def estimate_cost(delegate: Delegate, tokens_in: int, tokens_out: int) -> float:
    """PURE. USD estimate; 0.0 for subscription-billed (cli) delegates."""
    return (tokens_in * delegate.price_in_per_mtok
            + tokens_out * delegate.price_out_per_mtok) / 1_000_000


# ── result shape ─────────────────────────────────────────────────────────────
@dataclass
class BridgeRun:
    """`ok` is the ONLY branch point: False → surface a blocker upward, STOP.
    `findings` is populated for kind=challenge (parsed, best-effort)."""
    ok: bool
    delegate: str
    model: str
    kind: str
    content: str = ""
    findings: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    error: str | None = None


def parse_findings(content: str) -> list[dict] | None:
    """PURE, defensive. Extract the findings array from a challenge reply.

    F38#6 — the return now DISTINGUISHES the two zero-findings cases:
    * [] — the delegate returned a VALID (possibly empty) findings array:
      a real hunt found nothing. Legal, satisfies the contract.
    * None — the reply broke the contract (no parseable JSON array). The
      caller must treat this as a FAILED challenge, never a clean pass:
      arbitrary/prompt-injected prose used to read as findings=[] and
      satisfy G-CHALLENGE.
    """
    text = content.strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        arr = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list):
        return None
    out = []
    for f in arr:
        if isinstance(f, dict) and isinstance(f.get("finding"), str):
            out.append({
                "finding": f["finding"],
                "evidence": str(f.get("evidence", "")),
                "severity": f.get("severity") if f.get("severity") in
                            ("low", "medium", "high") else "medium",
                "target": str(f.get("target", "")),
            })
    if arr and not out:
        # F40#4: a NON-empty array in which no element conforms is a
        # contract break, not a clean hunt — the old filter turned
        # [{"finding": 123}] into [] and satisfied the gate.
        return None
    return out


# ── audit sidecar ────────────────────────────────────────────────────────────
def _audit_file(scope: str) -> Path:
    home = os.environ.get("EDP_AGENT_HOME") or os.getcwd()
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in scope) or "anon"
    return Path(home) / ".bridge" / f"audit-{safe}.jsonl"


# F40#6 — audit-degradation latch. An audit append failure still never
# blocks the RESULT (the provider was already paid), but it must not
# vanish either: the failure is latched to a marker file the budget
# aggregation reads, so "actuals complete" can never be claimed after a
# lost row. File-based because every shell's MCP server is its own
# process — an in-process counter would hide fleet-wide loss.
_AUDIT_DEGRADED_MARKER = "audit-degraded"


def audit(scope: str, row: dict) -> None:
    """Append-only, best-effort — an audit failure never blocks a result,
    but it LATCHES the degradation marker (F40#6)."""
    home = Path(os.environ.get("EDP_AGENT_HOME") or os.getcwd())
    try:
        f = _audit_file(scope)
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        try:
            (home / ".bridge" / _AUDIT_DEGRADED_MARKER).write_text(
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                encoding="utf-8")
        except OSError:
            pass    # disk truly gone — nothing durable left to say it with


# ── the impure entrypoints ───────────────────────────────────────────────────
def _redact_secret(text: str, secret: str) -> str:
    """F37#8 — provider error bodies / response echoes return to the agent
    AND land in the audit sidecar; strip the bearer key before either."""
    if secret and secret in text:
        return text.replace(secret, "«redacted-api-key»")
    return text


def _run_http(delegate: Delegate, work_order: str) -> tuple[str, int, int, str | None]:
    """One chat-completions call. Returns (content, tokens_in, tokens_out,
    error). No retries — a provider failure is the caller's signal, not ours to
    massage away."""
    key_env = delegate.api_key_env or ""
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise BridgeError(
            f"delegate {delegate.name!r}: env var {key_env!r} is empty — export "
            f"the provider API key there (the registry stores the NAME only).")
    url = (delegate.base_url or "").rstrip("/") + "/chat/completions"
    body = json.dumps(build_http_payload(delegate, work_order)).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    timeout = float(os.environ.get(_HTTP_TIMEOUT_ENV, _HTTP_TIMEOUT_DEFAULT))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body_text = resp.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError:
            # F38#12: HTTP 200 with a non-JSON body (proxy error page,
            # truncated stream) is a PROVIDER failure — the documented
            # ok=false path, never an uncaught exception that skips audit.
            return "", 0, 0, (
                f"{delegate.name} returned HTTP 200 with a non-JSON body: "
                f"{_redact_secret(body_text[:300], key)!r}. First-class "
                f"blocker — surface upward, do NOT retry-loop.")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except OSError:
            pass
        detail = _redact_secret(detail, key)  # F37#8
        return "", 0, 0, (f"HTTP {e.code} from {delegate.name}: {detail or e.reason}. "
                          f"First-class blocker — surface upward, do NOT retry-loop.")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "", 0, 0, (f"could not reach {delegate.name} "
                          f"({_redact_secret(str(e), key)}). First-class "
                          f"blocker — surface upward, do NOT retry-loop.")
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return "", 0, 0, (f"{delegate.name} returned an unrecognized response "
                          f"shape: {_redact_secret(str(data)[:300], key)}")
    usage = data.get("usage") or {}
    try:
        tin = int(usage.get("prompt_tokens", 0) or 0)
        tout = int(usage.get("completion_tokens", 0) or 0)
    except (TypeError, ValueError):
        tin = tout = 0     # malformed usage: report unknown, never raise
    return content, tin, tout, None


#: ToS-safety concurrency cap for subscription-CLI delegates (user ruling
#: 2026-08-07): N shells calling codex simultaneously looks like automated
#: hammering of a consumer ChatGPT plan. Cross-PROCESS slot lock (every
#: shell's MCP server is a separate process, so an in-process semaphore
#: guards nothing): atomic mkdir slots under the agent home. Default 2
#: concurrent codex turns fleet-wide; EDP_BRIDGE_CLI_MAX=1 serializes.
_CLI_MAX_ENV = "EDP_BRIDGE_CLI_MAX"
_CLI_SLOT_WAIT_S = 900.0            # matches sol_bridge's turn ceiling
# F38#4: staleness must EXCEED every legal delegate timeout (per-delegate
# timeout_secs goes to 1800), or the reaper steals a slot from a live
# long-running turn and the concurrency cap collapses. 2400 = 1800 + margin.
_CLI_SLOT_STALE_S = 2400.0          # reap a slot from a crashed process


def _pid_alive(pid: int) -> bool:
    """Best-effort cross-platform liveness probe; unknown reads as ALIVE
    (never steal a slot we cannot prove is dead). NOTE: os.kill(pid, 0) is a
    POSIX idiom — on Windows signal 0 is CTRL_C_EVENT, not a probe — so
    Windows takes a ctypes OpenProcess path (F38#4)."""
    if pid <= 0:
        return False
    import sys
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_INVALID_PARAMETER = 87
        # use_last_error=True + get_last_error(): the raw
        # windll.kernel32.GetLastError() reads whatever the interpreter's
        # own intervening Win32 calls left behind — a stale value here
        # would misclassify dead-vs-alive. restype=HANDLE: the default
        # c_int restype truncates a 64-bit HANDLE.
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL,
                                    wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # invalid-parameter = no such process → dead; anything else
            # (e.g. access-denied) is unprovable → treat as alive.
            return ctypes.get_last_error() != ERROR_INVALID_PARAMETER
        try:
            code = wintypes.DWORD()
            if k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True     # exists but not ours to signal


def _cli_slot_acquire() -> tuple[Path, str] | None:
    home = Path(os.environ.get("EDP_AGENT_HOME") or os.getcwd())
    slots_dir = home / ".bridge" / "cli-slots"
    slots_dir.mkdir(parents=True, exist_ok=True)
    try:
        n = max(1, int(os.environ.get(_CLI_MAX_ENV, "2")))
    except ValueError:
        n = 2
    nonce = f"{os.getpid()}-{time.time_ns()}"
    deadline = time.time() + _CLI_SLOT_WAIT_S
    while time.time() < deadline:
        reaped = False
        for i in range(n):
            slot = slots_dir / f"slot-{i}.lock"
            try:
                slot.mkdir()                     # atomic acquire
                (slot / "pid").write_text(str(os.getpid()))
                # F38#4: ownership nonce — release only removes a slot it
                # still owns, so a reaped-and-reacquired slot cannot be
                # deleted by its previous holder's finally block.
                (slot / "nonce").write_text(nonce)
                return slot, nonce
            except FileExistsError:
                # reap ONLY a slot that is both aged AND provably dead —
                # age alone stole slots from live long-running turns.
                try:
                    age = time.time() - slot.stat().st_mtime
                    if age <= _CLI_SLOT_STALE_S:
                        continue
                    # F40#14: a crash between mkdir and the pid write left a
                    # slot with NO pid file — the old read raised OSError
                    # into the blanket `pass` and the orphan lived forever
                    # (a permanent one-slot leak). Missing/junk pid after
                    # the stale age = dead, reapable.
                    try:
                        pid_raw = (slot / "pid").read_text().strip()
                    except OSError:
                        pid_raw = ""
                    if pid_raw.isdigit() and _pid_alive(int(pid_raw)):
                        continue
                    (slot / "pid").unlink(missing_ok=True)
                    (slot / "nonce").unlink(missing_ok=True)
                    slot.rmdir()
                    reaped = True                # retry acquisition at once
                except OSError:
                    pass
        if reaped:
            continue                             # skip the wait — a slot freed
        time.sleep(2.0)
    return None


def _cli_slot_release(slot: Path | None, nonce: str | None = None) -> None:
    if slot is None:
        return
    try:
        if nonce is not None:
            try:
                if (slot / "nonce").read_text().strip() != nonce:
                    return      # no longer ours (reaped + reacquired)
            except OSError:
                pass            # nonce unreadable — fall through, best effort
        (slot / "pid").unlink(missing_ok=True)
        (slot / "nonce").unlink(missing_ok=True)
        slot.rmdir()
    except OSError:
        pass


def _run_cli(delegate: Delegate, work_order: str, caller: str,
             kind: str,
             out_dir: str | None = None,
             images: list[str] | None = None
             ) -> tuple[str, int, int, str | None]:
    """One Codex-CLI turn via sol_bridge — ALWAYS read-only sandbox: bridge
    delegates return text, they never write. Thread stickiness per
    (caller, delegate) via sol_bridge's own store; a challenge always starts a
    FRESH thread so the adversary never accretes sympathy for prior context.
    Fleet-wide concurrency is slot-capped (see _CLI_MAX_ENV above): a shell
    that cannot get a slot within the wait window gets a BLOCKER, never a
    pile-on."""
    acquired = _cli_slot_acquire()
    if acquired is None:
        return "", 0, 0, (
            f"no codex slot free within {_CLI_SLOT_WAIT_S:.0f}s "
            f"({_CLI_MAX_ENV} caps fleet-wide concurrent sol turns to "
            f"protect the ChatGPT plan) — surface upward and continue other "
            f"work; do NOT retry-loop.")
    slot, nonce = acquired
    try:
        import tempfile
        workdir = str(Path(tempfile.gettempdir()) / "edp-bridge"
                      / delegate.name)
        sandbox = "read-only"
        if out_dir:
            # QoL Phase 4 (operator ruling 2026-08-21): ASSET GENERATION is
            # the ONE write-capable delegate turn — "just use the bridge and
            # tell it to generate image files in a dir". The sandbox opens
            # to workspace-write scoped at out_dir (the CLI's own sandbox
            # keeps writes inside the workdir); every other delegate stays
            # read-only text.
            workdir = out_dir
            sandbox = "workspace-write"
        run = sol_bridge.run_sol(
            prompt=work_order, workdir=workdir, sandbox=sandbox,
            images=images,
            caller=caller, advisor=delegate.name, effort=delegate.effort,
            new_thread=(kind == "challenge"),
            timeout_secs=delegate.timeout_secs,
            # F38#1: the registry's pin reaches the CLI (-m) instead of the
            # CLI default running while the audit claims the pinned model.
            model=delegate.model)
        content = run.last_message or "\n".join(run.agent_messages)
        return content, 0, 0, (None if run.ok else run.error)
    except sol_bridge.SolBridgeError as e:
        # F38#11: a CLI precondition (oversized argv, missing binary) must
        # cross the tool boundary as the documented BridgeError shape, not
        # an uncaught exception that skips the audit row.
        raise BridgeError(str(e)) from e
    finally:
        _cli_slot_release(slot, nonce)


def delegate_call(*, kind: str, delegate_name: str, task: str,
                  context: str = "", acceptance: str = "",
                  caller: str = "anon",
                  out_dir: str | None = None,
                  images: list[str] | None = None) -> BridgeRun:
    """Run ONE delegated turn. Preconditions raise BridgeError; provider
    failures return BridgeRun(ok=False). Every call is audit-logged."""
    delegates, _routes = load_config()
    d = delegates.get(delegate_name)
    if d is None:
        raise BridgeError(f"unknown delegate {delegate_name!r} "
                          f"(known: {sorted(delegates)})")
    order = build_work_order(task=task, context=context,
                             acceptance=acceptance, kind=kind)
    check_budget(d, order)

    t0 = time.time()
    if d.backend == "http":
        content, tin, tout, err = _run_http(d, order)
    else:
        content, tin, tout, err = _run_cli(d, order, caller, kind,
                                           out_dir=out_dir, images=images)
    # F38#13: usage is estimated (and cost computed) only for a call the
    # provider actually served — a connection-refused attempt used to be
    # audited as full estimated spend and eat the budget for money never
    # spent. A failed call records zeros; billing truth stays with `ok`.
    if err is None:
        tin = tin or approx_tokens(order)      # cli reports no usage; estimate
        tout = tout or approx_tokens(content)
        cost = estimate_cost(d, tin, tout)
    else:
        tin = tout = 0
        cost = 0.0

    run = BridgeRun(ok=err is None, delegate=d.name, model=d.model, kind=kind,
                    content=content, tokens_in=tin, tokens_out=tout,
                    cost_usd=round(cost, 6), error=err)
    if kind == "challenge" and run.ok:
        parsed = parse_findings(content)
        if parsed is None:
            # F38#6: a reply that broke the findings contract is a FAILED
            # challenge — ok=false, raw text quarantined in content for
            # diagnostics, never returned as a satisfied adversarial pass.
            run.ok = False
            run.error = (
                "challenge reply broke the findings contract (no JSON "
                "array) — the adversarial pass did NOT happen. Re-run the "
                "challenge; do not treat the raw text as findings.")
        else:
            run.findings = parsed

    audit(caller, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind, "delegate": d.name, "model": d.model,
        # F38#5: lineage for budget attribution — the caller handle rides
        # on every row so spend can be scoped to its recipe.
        "caller": caller,
        "order_bytes": len(order.encode("utf-8")),
        "tokens_in": tin, "tokens_out": tout, "cost_usd": run.cost_usd,
        "ok": run.ok, "error": (run.error or "")[:300],
        "findings": len(run.findings), "secs": round(time.time() - t0, 1),
    })
    return run
