"""uvicorn entrypoint.

Run via the console script (`uv run edp-pool`) or
`python -m edp_pool.main`. Both reach `run()` — the missing `__main__`
guard was why `python -m edp_pool.main` "did nothing".
"""

import os
from pathlib import Path

from edp_contracts import get_logger

from .service import create_app
from .spawner import SubprocessSpawner

_log = get_logger("edp-pool")

# eda-base3 stack default — broker on 9300. Override with EDP_BROKER_URL.
_broker_url = os.environ.get("EDP_BROKER_URL", "http://127.0.0.1:9300")
_log_dir = Path(os.environ.get("EDP_POOL_LOG_DIR", ".pool-logs"))
# cross-restart-recovery: persist locks+sessions here so a pool restart
# reloads them (orphaned shells then read as dead → reaped/recovered).
_state_path = Path(
    os.environ.get("EDP_POOL_STATE", ".pool-logs/pool-state.json")
)

# 2026-05-28 SELF-LOCATING stack pin. The pool computes its sibling claude
# repo + .logs from its OWN path — never from a (possibly-stray) inherited
# EDP_AGENT_HOME/EDP_LOG_DIR. This is the eda-base3 wiring fix: a clone's
# pool spawns shells onto the clone's OWN stack (skills, .mcp.json, logs,
# pool), not whatever repo the launching shell's env happened to point at.
# Layout: <root>/{claude, edp-pool, edp-broker, ...}; this file is at
# <root>/edp-pool/src/edp_pool/main.py → parents[3] == <root>.
_root = Path(__file__).resolve().parents[3]
_agent_home = str(_root / "claude")          # spawned shells' cwd + skills
_shell_log_dir = str(_root / ".logs")        # spawned shells' EDP_LOG_DIR
# The pool's OWN url, from its own port config — so spawned shells'
# pool_close_self / liveness hit THIS pool, not an inherited EDP_POOL_URL.
_pool_host = os.environ.get("EDP_POOL_HOST", "127.0.0.1")
_pool_port = os.environ.get("EDP_POOL_PORT", "9301")
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
# PORT-OPENCODE M1 — mixed-fleet opt-in. EDP_OPENCODE_ROLES names the roles
# routed to the opencode/gpt-5.6 backend (e.g. "worker" or "worker,reviewer");
# EMPTY (the default) keeps the fleet 100% Claude — zero behavior change.
_oc_roles = {r.strip() for r in
             os.environ.get("EDP_OPENCODE_ROLES", "").split(",") if r.strip()}
if _oc_roles:
    from .opencode_launcher import CompositeSpawner, OpencodeSpawner
    _spawner = CompositeSpawner(
        _claude_spawner,
        OpencodeSpawner(
            log_dir=str(_root / ".logs" / "opencode"),
            broker_url=_broker_url,
            pool_url=_pool_url,
            agent_home=_agent_home,
        ),
        opencode_roles=_oc_roles,
    )
    _log.info("opencode_backend_armed",
              "mixed fleet: roles routed to opencode",
              roles=sorted(_oc_roles))
else:
    _spawner = _claude_spawner

# WS7 (SHADOW.md): headless spawns get a per-shell shadow (wake plane,
# brief injection, observed close) — Spawner-compatible wrapper, so the
# service is untouched. Monitor-mode spawns pass through to legacy.
# Staged: EDP_SHADOW=0 disables outright.
from .shadow_spawner import ShadowSpawner, shadow_enabled  # noqa: E402

if shadow_enabled() and _spawner is _claude_spawner:
    _spawner = ShadowSpawner(_claude_spawner)
    _log.info("shadow_backend_armed",
              "headless spawns are shadow-wrapped (WS7)")

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

    host = os.environ.get("EDP_POOL_HOST", "127.0.0.1")
    # eda-base3 stack default — 9301 (old eda-base stack uses 9200).
    port = int(os.environ.get("EDP_POOL_PORT", "9301"))
    # The rx subscriptions poll GET /v1/locks, /v1/sessions, /v1/liveness
    # every ~2s PER subscription, so uvicorn's access log floods the console
    # with one line per request. Disable it by default — the meaningful
    # lifecycle events (launch/release/spawn/reap) still log via `_log`.
    # Re-enable for debugging with EDP_POOL_ACCESS_LOG=1.
    access_log = os.environ.get("EDP_POOL_ACCESS_LOG", "0").lower() in (
        "1", "true", "yes", "on")
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
                timeout_graceful_shutdown=int(
                    os.environ.get("EDP_POOL_SHUTDOWN_GRACE_SECS", "5")))


if __name__ == "__main__":
    run()
