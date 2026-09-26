"""uvicorn entrypoint.

Run via the console script (`uv run edp-pool`) or
`python -m edp_pool.main`. Both reach `run()` — the missing `__main__`
guard was why `python -m edp_pool.main` "did nothing".
"""

from pathlib import Path

from edp_contracts import get_logger, settings

from .service import create_app
from .spawner import SubprocessSpawner

_log = get_logger("edp-pool")

# eda-base3 stack default — broker on 9300. Override with EDP_BROKER_URL.
_broker_url = settings.get("EDP_BROKER_URL")
_log_dir = settings.get("EDP_POOL_LOG_DIR")
# cross-restart-recovery: persist locks+sessions here so a pool restart
# reloads them (orphaned shells then read as dead → reaped/recovered).
_state_path = settings.get("EDP_POOL_STATE")

# 2026-05-28 stack pin: the pool pins its agent home + shells' log dir from its
# OWN settings — never from a (possibly-stray) inherited EDP_AGENT_HOME/EDP_LOG_DIR
# — so a clone's pool spawns shells onto the clone's OWN stack (skills, .mcp.json,
# logs, pool). Dev mode (EDP_HOME=<repo>/v8): agent home <repo>/v8, logs <repo>/.logs.
_agent_home = str(settings.get("EDP_POOL_AGENT_HOME"))  # spawned shells' cwd + skills
_shell_log_dir = str(settings.get("EDP_POOL_SHELL_LOG_DIR"))  # spawned shells' EDP_LOG_DIR
# The pool's OWN url, from its own port config — so spawned shells'
# pool_close_self / liveness hit THIS pool, not an inherited EDP_POOL_URL.
_pool_host = settings.get("EDP_POOL_HOST")
_pool_port = settings.get("EDP_POOL_PORT")
_pool_url = f"http://{_pool_host}:{_pool_port}"

# Real deployment uses SubprocessSpawner; it needs the broker URL (passed
# to spawned shells as EDP_BROKER_URL) and a log dir to drain PTY output
# for debugging. Tests/S4 use FakeSpawner via create_app() directly.
_claude_spawner = SubprocessSpawner(
    broker_url=_broker_url,
    log_dir=_log_dir,
    cwd=_agent_home,           # explicit — no stray-env fallback
    pool_url=_pool_url,
    shell_log_dir=_shell_log_dir,
)
_spawner = _claude_spawner
# epic-6a8a6020fd S2 — resident GPT-6 Astra seats under pi.dev. EDP_PI_ROLES names the roles
# routed to the Pi backend (e.g. "qa"); EMPTY (the default) = zero behaviour change.
# CompositeSpawner only uses the Spawner surface + the getattr hooks, so it stacks on whatever
# _spawner already is.
_pi_roles = set(settings.get("EDP_PI_ROLES"))
# Per-spawn routing (owner m-8642d551fc): with the Pi harness installed (edp-pool/.pi-harness or
# EDP_PI_BIN) the backend is ALWAYS armed, and a spawn whose requested model is a `harness: pi`
# seat name ("astra") or an openai/… id lands on it — no role re-arming needed. Roles listed in
# EDP_PI_ROLES route there unconditionally as before.
from .pi_launcher import is_pi_model, pi_harness_cli  # noqa: E402
_pi_available = pi_harness_cli() is not None or settings.is_set("EDP_PI_BIN")
if _pi_roles or _pi_available:
    from .composite_spawner import CompositeSpawner
    from .pi_launcher import PiSpawner
    _spawner = CompositeSpawner(
        _spawner,
        PiSpawner(
            log_dir=str(Path(_shell_log_dir) / "pi"),
            broker_url=_broker_url,
            pool_url=_pool_url,
            agent_home=_agent_home,
        ),
        roles=_pi_roles,
        route_model=lambda m: is_pi_model(m, _agent_home),
    )
    _log.info("pi_backend_armed", "mixed fleet: roles + pi-seat models routed to pi (GPT-6 Astra)",
              roles=sorted(_pi_roles), by_model=True)
# s-10a2b1f9ec — resident GPT-6 Astra seats under `codex app-server`. EDP_CODEX_ROLES names the
# roles routed there; EDP_CODEX_BY_MODEL=1 also routes spawns whose model is a `harness: codex`
# seat ("astra-codex") or `codex/<id>`. BOTH empty (the default) = the stack above, untouched.
_codex_roles = set(settings.get("EDP_CODEX_ROLES"))
_codex_by_model = True  # explicit catalog entries always route; no prefix or feature flag
if _codex_roles or _codex_by_model:
    from .codex_launcher import CodexSpawner, is_codex_model
    from .composite_spawner import CompositeSpawner
    _spawner = CompositeSpawner(
        _spawner,
        CodexSpawner(
            log_dir=str(Path(_shell_log_dir) / "codex"),
            broker_url=_broker_url,
            pool_url=_pool_url,
            agent_home=_agent_home,
        ),
        roles=_codex_roles,
        route_model=(lambda m: is_codex_model(m, _agent_home))
        if _codex_by_model else None,
    )
    _log.info("codex_backend_armed", "mixed fleet: roles routed to codex app-server (GPT-6 Astra)",
              roles=sorted(_codex_roles), by_model=_codex_by_model)

# WS7 (SHADOW.md): every spawn gets a per-shell shadow (wake plane,
# brief injection, observed close) — Spawner-compatible wrapper, so the
# service is untouched. Headless rides ConPTY; monitor (the default)
# rides argv-first-line + console-input injection.
# Staged: EDP_SHADOW=0 disables outright.
from .shadow_spawner import ShadowSpawner, shadow_enabled  # noqa: E402

if shadow_enabled() and _spawner is _claude_spawner:
    _spawner = ShadowSpawner(_claude_spawner)
    _log.info("shadow_backend_armed",
              "all spawns (monitor + headless) are shadow-wrapped (WS7)")

app = create_app(
    spawner=_spawner,
    broker_url=_broker_url,
    state_path=_state_path,
)
_log.info(
    "spawner_stack_pinned", "edp-pool spawner stack pinned",
    agent_home=_agent_home, pool_url=_pool_url,
    broker_url=_broker_url, shell_log_dir=_shell_log_dir,
)


def run() -> None:
    import uvicorn

    host = settings.get("EDP_POOL_HOST")
    # eda-base3 stack default — 9301 (old eda-base stack uses 9200).
    port = settings.get("EDP_POOL_PORT")
    # The rx subscriptions poll GET /v1/locks, /v1/sessions, /v1/liveness
    # every ~2s PER subscription, so uvicorn's access log floods the console
    # with one line per request. Disable it by default — the meaningful
    # lifecycle events (launch/release/spawn/reap) still log via `_log`.
    # Re-enable for debugging with EDP_POOL_ACCESS_LOG=1.
    access_log = settings.get("EDP_POOL_ACCESS_LOG")
    _log.info(
        "startup",
        f"edp-pool listening on http://{host}:{port}",
        host=host,
        port=port,
        broker_url=_broker_url,
        log_dir=str(_log_dir),
        access_log=access_log,
    )
    # Same shutdown grace as the broker (2026-07-19): panel approvals
    # LONG-POLL here, and uvicorn's default graceful shutdown waits for
    # open connections forever — Ctrl-C with a panel open would freeze.
    uvicorn.run(app, host=host, port=port, log_level="info",
                access_log=access_log,
                timeout_graceful_shutdown=settings.get("EDP_POOL_SHUTDOWN_GRACE_SECS"))


if __name__ == "__main__":
    run()
