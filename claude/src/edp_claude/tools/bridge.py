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


def parse_findings(content: str) -> list[dict]:
    """PURE, defensive. Extract the findings array from a challenge reply; a
    reply that ignores the contract yields [] — the audit row still records the
    raw content, so a noisy lens is measurable, never silently trusted."""
    text = content.strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        arr = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for f in arr if isinstance(arr, list) else []:
        if isinstance(f, dict) and isinstance(f.get("finding"), str):
            out.append({
                "finding": f["finding"],
                "evidence": str(f.get("evidence", "")),
                "severity": f.get("severity") if f.get("severity") in
                            ("low", "medium", "high") else "medium",
                "target": str(f.get("target", "")),
            })
    return out


# ── audit sidecar ────────────────────────────────────────────────────────────
def _audit_file(scope: str) -> Path:
    home = os.environ.get("EDP_AGENT_HOME") or os.getcwd()
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in scope) or "anon"
    return Path(home) / ".bridge" / f"audit-{safe}.jsonl"


def audit(scope: str, row: dict) -> None:
    """Append-only, best-effort — an audit failure never blocks a result."""
    try:
        f = _audit_file(scope)
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ── the impure entrypoints ───────────────────────────────────────────────────
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
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except OSError:
            pass
        return "", 0, 0, (f"HTTP {e.code} from {delegate.name}: {detail or e.reason}. "
                          f"First-class blocker — surface upward, do NOT retry-loop.")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "", 0, 0, (f"could not reach {delegate.name} ({e}). First-class "
                          f"blocker — surface upward, do NOT retry-loop.")
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return "", 0, 0, (f"{delegate.name} returned an unrecognized response "
                          f"shape: {str(data)[:300]}")
    usage = data.get("usage") or {}
    return (content, int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)), None)


#: ToS-safety concurrency cap for subscription-CLI delegates (user ruling
#: 2026-08-07): N shells calling codex simultaneously looks like automated
#: hammering of a consumer ChatGPT plan. Cross-PROCESS slot lock (every
#: shell's MCP server is a separate process, so an in-process semaphore
#: guards nothing): atomic mkdir slots under the agent home. Default 2
#: concurrent codex turns fleet-wide; EDP_BRIDGE_CLI_MAX=1 serializes.
_CLI_MAX_ENV = "EDP_BRIDGE_CLI_MAX"
_CLI_SLOT_WAIT_S = 900.0            # matches sol_bridge's turn ceiling
_CLI_SLOT_STALE_S = 1200.0          # reap a slot from a crashed process


def _cli_slot_acquire() -> Path | None:
    home = Path(os.environ.get("EDP_AGENT_HOME") or os.getcwd())
    slots_dir = home / ".bridge" / "cli-slots"
    slots_dir.mkdir(parents=True, exist_ok=True)
    try:
        n = max(1, int(os.environ.get(_CLI_MAX_ENV, "2")))
    except ValueError:
        n = 2
    deadline = time.time() + _CLI_SLOT_WAIT_S
    while time.time() < deadline:
        for i in range(n):
            slot = slots_dir / f"slot-{i}.lock"
            try:
                slot.mkdir()                     # atomic acquire
                (slot / "pid").write_text(str(os.getpid()))
                return slot
            except FileExistsError:
                # reap a stale slot left by a crashed process
                try:
                    age = time.time() - slot.stat().st_mtime
                    if age > _CLI_SLOT_STALE_S:
                        (slot / "pid").unlink(missing_ok=True)
                        slot.rmdir()
                except OSError:
                    pass
        time.sleep(2.0)
    return None


def _cli_slot_release(slot: Path | None) -> None:
    if slot is None:
        return
    try:
        (slot / "pid").unlink(missing_ok=True)
        slot.rmdir()
    except OSError:
        pass


def _run_cli(delegate: Delegate, work_order: str, caller: str,
             kind: str) -> tuple[str, int, int, str | None]:
    """One Codex-CLI turn via sol_bridge — ALWAYS read-only sandbox: bridge
    delegates return text, they never write. Thread stickiness per
    (caller, delegate) via sol_bridge's own store; a challenge always starts a
    FRESH thread so the adversary never accretes sympathy for prior context.
    Fleet-wide concurrency is slot-capped (see _CLI_MAX_ENV above): a shell
    that cannot get a slot within the wait window gets a BLOCKER, never a
    pile-on."""
    slot = _cli_slot_acquire()
    if slot is None:
        return "", 0, 0, (
            f"no codex slot free within {_CLI_SLOT_WAIT_S:.0f}s "
            f"({_CLI_MAX_ENV} caps fleet-wide concurrent sol turns to "
            f"protect the ChatGPT plan) — surface upward and continue other "
            f"work; do NOT retry-loop.")
    try:
        import tempfile
        workdir = str(Path(tempfile.gettempdir()) / "edp-bridge"
                      / delegate.name)
        run = sol_bridge.run_sol(
            prompt=work_order, workdir=workdir, sandbox="read-only",
            caller=caller, advisor=delegate.name, effort=delegate.effort,
            new_thread=(kind == "challenge"))
        content = run.last_message or "\n".join(run.agent_messages)
        return content, 0, 0, (None if run.ok else run.error)
    finally:
        _cli_slot_release(slot)


def delegate_call(*, kind: str, delegate_name: str, task: str,
                  context: str = "", acceptance: str = "",
                  caller: str = "anon") -> BridgeRun:
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
        content, tin, tout, err = _run_cli(d, order, caller, kind)
    tin = tin or approx_tokens(order)          # cli reports no usage; estimate
    tout = tout or approx_tokens(content)
    cost = estimate_cost(d, tin, tout)

    run = BridgeRun(ok=err is None, delegate=d.name, model=d.model, kind=kind,
                    content=content, tokens_in=tin, tokens_out=tout,
                    cost_usd=round(cost, 6), error=err)
    if kind == "challenge" and run.ok:
        run.findings = parse_findings(content)

    audit(caller, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind, "delegate": d.name, "model": d.model,
        "order_bytes": len(order.encode("utf-8")),
        "tokens_in": tin, "tokens_out": tout, "cost_usd": run.cost_usd,
        "ok": run.ok, "error": (err or "")[:300],
        "findings": len(run.findings), "secs": round(time.time() - t0, 1),
    })
    return run
