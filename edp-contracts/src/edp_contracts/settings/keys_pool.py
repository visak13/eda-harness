"""Settings declared for pool (see keys_common for shared ones)."""
from __future__ import annotations

from pathlib import Path

from ._core import _is_source_checkout, agent_home, data_dir, declare, home


def _repo_root() -> Path | None:
    """The source checkout's root in dev mode (EDP_HOME is <repo>/v8), else None."""
    h = home()
    return h.parent if h is not None and _is_source_checkout(h) else None


def _dev_or_data(dev_rel: str, installed: str) -> Path:
    """<repo>/<dev_rel> in a source checkout (today's dev path, unchanged), else <data>/<installed>."""
    root = _repo_root()
    return root / dev_rel if root is not None else data_dir() / installed


# ---- paths
declare("pool.dir", "EDP_POOL_DIR", "path", lambda: _dev_or_data("edp-pool", "pool"), "Paths",
        "The pool's own runtime dir (.shadows, .pi-harness, the pause watchdog's cwd).",
        default_doc="<repo>/edp-pool in dev mode, else <data>/pool", restart_required="pool")
declare("pool.log_dir", "EDP_POOL_LOG_DIR", "path", Path(".pool-logs"), "Paths",
        "Dir the pool drains spawned shells' PTY output into (relative to the pool's cwd).",
        restart_required="pool")
declare("pool.state", "EDP_POOL_STATE", "path", Path(".pool-logs/pool-state.json"), "Paths",
        "The pool's persisted locks+sessions file, reloaded across a pool restart.", restart_required="pool")
declare("pool.shell_log_dir", "EDP_POOL_SHELL_LOG_DIR", "path", lambda: _dev_or_data(".logs", "logs"), "Paths",
        "EDP_LOG_DIR pinned on every spawned shell (and the pi/codex backends' log root).",
        default_doc="<repo>/.logs in dev mode, else <data>/logs", restart_required="pool")
declare("pool.claude_config_dir", "EDP_CLAUDE_CONFIG_DIR", "path",
        lambda: _dev_or_data("edp-pool/.claude-pool", "claude-pool"), "Paths",
        "CLAUDE_CONFIG_DIR of pool-spawned claude shells (never the operator's personal store).",
        default_doc="<repo>/edp-pool/.claude-pool in dev mode, else <data>/claude-pool")
declare("pool.claude_home", "EDP_POOL_CLAUDE_HOME", "path",
        lambda: (_repo_root() / "claude") if _repo_root() is not None else agent_home(), "Paths",
        "The v7 `claude` repo (.recipes briefs, neuron_heartbeat.py, recipe_ctl.py) the panel's recipe "
        "features use when EDP_AGENT_HOME is unset.", default_doc="<repo>/claude in dev mode, else the agent home")
declare("pool.spawn_defaults", "EDP_SPAWN_DEFAULTS", "path", Path(".pool-logs/spawn_defaults.json"), "Paths",
        "The panel-saved spawn defaults file (W12).")
declare("pool.pause_tokens", "EDP_POOL_PAUSE_TOKENS", "path", None, "Paths",
        "Dir of the pause watchdog's run tokens; default <state dir>/pause-tokens.")

# ---- backends / seats
declare("pool.claude_bin", "EDP_CLAUDE_BIN", "path", None, "Seats & models",
        "claude executable for pool shells; default `claude` on PATH (npm shim resolved to the exe).",
        restart_required="none")
declare("pool.claude_versions_cache", "EDP_CLAUDE_VERSIONS_CACHE", "path", None, "Seats & models",
        "Dir or file holding the full claude.exe to repair an npm stub from.")
declare("pool.spawn_mode", "EDP_SPAWN_MODE", "str", "monitor", "Seats & models",
        "Default spawn mode when neither the request nor the panel sets one (monitor|headless).")
declare("pool.spawn_env_keep", "EDP_SPAWN_ENV_KEEP", "list", list, "Seats & models",
        "Secret-looking env names still passed through to spawned shells (comma list).")
declare("pool.pi_roles", "EDP_PI_ROLES", "list", list, "Seats & models",
        "Roles always routed to the Pi backend.", restart_required="pool")
declare("pool.pi_seat_python", "EDP_PI_SEAT_PYTHON", "path", None, "Seats & models",
        "Python that runs the Pi/codex seat runner; default the agent home's .venv python.")
declare("pool.codex_roles", "EDP_CODEX_ROLES", "list", list, "Seats & models",
        "Roles always routed to the codex app-server backend.", restart_required="pool")
declare("pool.codex_by_model", "EDP_CODEX_BY_MODEL", "bool", False, "Seats & models",
        "Route spawns whose model is a codex seat (or codex/<id>) to the codex backend.",
        restart_required="pool")
declare("pool.shadow", "EDP_SHADOW", "bool", False, "Seats & models",
        "Diagnostic opt-in: wrap every spawn in a shell shadow (retired, default off).",
        restart_required="pool")

# ---- network / service
declare("pool.access_log", "EDP_POOL_ACCESS_LOG", "bool", False, "Limits/tuning",
        "uvicorn access log for the pool (off: the rx polls flood it).", restart_required="pool")
declare("pool.shutdown_grace_secs", "EDP_POOL_SHUTDOWN_GRACE_SECS", "int", 5, "Limits/tuning",
        "uvicorn graceful-shutdown bound, so an open panel long-poll cannot freeze a stop.",
        restart_required="pool")
declare("pool.phoenix_url", "EDP_PHOENIX_URL", "url", "http://localhost:6006", "Network",
        "Phoenix (tracing) URL the pool doctor probes.")
declare("pool.doctor_timeout_secs", "EDP_DOCTOR_TIMEOUT_S", "float", 3.0, "Limits/tuning",
        "Per-probe timeout of the pool doctor's HTTP checks.")

# ---- capacity (read live)
declare("pool.max_workers", "EDP_MAX_WORKERS", "int", 6, "Limits/tuning", "Cap on concurrent worker shells.")
declare("pool.max_planners", "EDP_MAX_PLANNERS", "int", 4, "Limits/tuning", "Cap on concurrent planner shells.")
declare("pool.max_total_shells", "EDP_MAX_TOTAL_SHELLS", "int", 10, "Limits/tuning",
        "Cap on concurrent throughput shells of every role.")
declare("pool.max_live_shells", "EDP_MAX_LIVE_SHELLS", "int", None, "Limits/tuning",
        "Hard ceiling on live shell processes (active+starting+parked+resuming); default 2x the total cap.")

# ---- timing (read live)
declare("pool.ready_timeout_secs", "EDP_READY_TIMEOUT_SECS", "float", 30.0, "Limits/tuning",
        "How long a spawn waits for the shell to become ready.")
declare("pool.submit_delay_ms", "EDP_SUBMIT_DELAY_MS", "float", 150.0, "Limits/tuning",
        "Delay between typing a prompt into a shell and pressing Enter.")
declare("pool.wake_defer_max_secs", "EDP_WAKE_DEFER_MAX_S", "float", 10.0, "Limits/tuning",
        "Longest a console wake waits for the operator to stop typing before deferring.")
declare("pool.resume_watchdog", "EDP_RESUME_WATCHDOG", "bool", True, "Limits/tuning",
        "Run the parked-handle resume watchdog.", restart_required="pool")
declare("pool.resume_watchdog_secs", "EDP_RESUME_WATCHDOG_SECS", "float", 5.0, "Limits/tuning",
        "Resume watchdog poll cadence.")
declare("pool.turn_timeout_secs", "EDP_TURN_TIMEOUT_SECS", "float", 2400.0, "Limits/tuning",
        "Hard bound on one resumed turn's wall clock; 0 disables.")
declare("pool.parked_heartbeat_secs", "EDP_PARKED_HEARTBEAT_SECS", "float", 1800.0, "Limits/tuning",
        "A parked shell idle this long is resumed for a reconcile tick; 0 disables.")
declare("pool.pause_max_secs", "EDP_PAUSE_MAX_SECS", "float", 1800.0, "Limits/tuning",
        "Auto-resume deadline of a paused (suspended) shell.")
declare("pool.starting_reap_grace_secs", "EDP_STARTING_REAP_GRACE_SECS", "float", 180.0, "Limits/tuning",
        "Age after which a spawn reservation still 'starting' counts as abandoned.")
