"""Settings shared by every package: roots and dirs, identity, service URLs, logging, OS values."""
from __future__ import annotations

from pathlib import Path

from ._core import agent_home, data_dir, declare, secrets_dir

# ---- roots and directories (read by _core's dir functions; env-only: they locate config.toml)
declare("paths.home", "EDP_HOME", "path", None, "Paths",
        "One root for config, data, run dir and agent home; a source checkout's v8/ is dev mode.",
        aliases=("EDP8_HOME",), env_only=True, restart_required="all")
declare("paths.dev", "EDP_DEV", "bool", False, "Paths",
        "Force dev mode (allows the 'dev' admin token) without EDP_HOME being a source checkout.",
        env_only=True, restart_required="all")
declare("paths.config_dir", "EDP_CONFIG_DIR", "path", None, "Paths",
        "Config dir (config.toml; installed also secrets/); default EDP_HOME, else <OS config dir>/config.",
        env_only=True, restart_required="all")
declare("paths.data_dir", "EDP8_DATA", "path", None, "Paths",
        "Data dir (db, uploads, agent home, backups); default EDP_HOME/.data, else <OS data dir>/data.",
        env_only=True, restart_required="all")
declare("paths.run_dir", "EDP8_RUN_DIR", "path", None, "Paths",
        "Run dir (service pid/state files); default EDP_HOME/.run, else <OS state dir>/run.",
        env_only=True, restart_required="all")
declare("paths.agent_home", "EDP_AGENT_HOME", "path", None, "Paths",
        "Seat home (role cards, skills, guides, .mcp.json, models.json); default EDP_HOME in dev mode, "
        "else <data>/agent-home.", env_only=True, restart_required="pool")
declare("paths.db", "EDP8_DB", "path", lambda: data_dir() / "edp8.db", "Paths",
        "The board's SQLite database.", default_doc="<data>/edp8.db", restart_required="board")
declare("paths.tokens", "EDP8_TOKENS", "path", lambda: secrets_dir() / "tokens.json", "Identity",
        "The participant token file (never inside a package or repo path when installed).",
        default_doc="<EDP_HOME>/tokens.json, installed <config>/secrets/tokens.json", restart_required="board")

# ---- identity
declare("identity.owner", "EDP8_OWNER", "str", "owner", "Identity",
        "Handle of the first human (the owner) that `heronry init` creates and `start` registers.",
        restart_required="board")
declare("edp8.admin_token", "EDP8_ADMIN_TOKEN", "str", None, "Identity",
        "Board admin token (X-Admin). Required outside dev mode; 'dev' is refused there.",
        secret=True, restart_required="board")
declare("seat.handle", "EDP_HANDLE", "str", None, "Identity",
        "This seat's handle (set by the pool on a spawned shell).", env_only=True)
declare("seat.participant", "EDP8_PARTICIPANT", "str", None, "Identity",
        "This process's participant id; falls back to EDP_HANDLE.", env_only=True, aliases=("EDP_HANDLE",))
declare("seat.token", "EDP8_TOKEN", "str", None, "Identity",
        "This seat's board token (set by the pool on a spawned shell).", env_only=True, secret=True)
declare("seat.role", "EDP_ROLE", "str", None, "Identity",
        "This seat's role (set by the pool on a spawned shell).", env_only=True)
declare("seat.spawn_session", "EDP_SPAWN_SESSION_ID", "str", None, "Identity",
        "The pool spawn session this shell belongs to.", env_only=True)

# ---- service URLs
declare("network.board_url", "EDP8_BOARD_URL", "url", "http://127.0.0.1:9400", "Network",
        "Board base URL clients and services call.", restart_required="all")
declare("network.mcp_url", "EDP8_MCP_URL", "url", "http://127.0.0.1:9402", "Network",
        "MCP proxy base URL seats connect to.", restart_required="pool")
declare("network.broker_url", "EDP_BROKER_URL", "url", "http://127.0.0.1:9300", "Network",
        "Message broker base URL.", restart_required="all")
declare("network.pool_url", "EDP_POOL_URL", "url", "http://127.0.0.1:9301", "Network",
        "Seat pool base URL.", restart_required="board")
declare("network.public_url", "EDP8_PUBLIC_URL", "url", None, "Network",
        "Public (tailnet) URL of the board; set turns on public mode's fail-closed token rules.",
        restart_required="board")

# ---- logging (edp_contracts.logging)
declare("logging.suffix", "EDP_LOG_SUFFIX", "str", None, "Limits/tuning",
        "Log file name suffix; falls back to EDP_HANDLE.", env_only=True)
declare("logging.dir", "EDP_LOG_DIR", "path", Path(".logs"), "Limits/tuning",
        "Structured log directory (relative to the process cwd).")
declare("logging.retention_days", "EDP_LOG_RETENTION_DAYS", "int", 14, "Limits/tuning",
        "Days of structured logs kept.")
declare("logging.level", "EDP_LOG_LEVEL", "str", "info", "Limits/tuning", "Structured log level.")

# ---- OS values (read, never configured)
for _name, _doc in (
    ("USERNAME", "OS user name (Windows)."),
    ("LOCALAPPDATA", "Windows local app-data dir."),
    ("ProgramFiles", "Windows Program Files dir."),
    ("ProgramFiles(x86)", "Windows Program Files (x86) dir."),
    ("ProgramW6432", "Windows 64-bit Program Files dir."),
    ("CLAUDE_CONFIG_DIR", "Claude Code config dir of this process."),
    ("COMSPEC", "Windows command interpreter; runs .cmd/.bat shims without a shell string (edp_contracts.toolpath)."),
    ("SystemRoot", "Windows system dir; a bash under it is WSL's relay, never Git bash."),
):
    declare(f"os.{_name.lower()}", _name, "str", None, "Platform", _doc, env_only=True)

# ---- brand (R8a, design §4.12; S7 interface m-4936b8a83d: edp8/brand.py re-exports these)
declare("brand.product_name", "EDP_PRODUCT_NAME", "str", "Heronry", "brand", "The product name shown to users.")
declare("brand.cli_name", "EDP_CLI_NAME", "str", "heronry", "brand", "The command-line tool's name.")
declare("brand.desktop_app_name", "EDP_DESKTOP_APP_NAME", "str", "Heronry Desktop", "brand",
        "The desktop app's name.")
declare("brand.tagline", "EDP_TAGLINE", "str",
        "your agent team, built on decisions, checked before delivery", "brand", "The product tagline.")

# ---- ports and hosts (one place for 9400/9402/9301/9300, design §4.2)
declare("board.port", "EDP8_PORT", "int", 9400, "Network", "Board HTTP port.", restart_required="board")
declare("board.host", "EDP8_HOST", "str", None, "Network",
        "Board bind host; unset = loopback, or the public-mode default.", restart_required="board")
declare("mcp.host", "EDP8_MCP_HOST", "str", "127.0.0.1", "Network", "MCP proxy bind host.",
        restart_required="mcp")
declare("mcp.port", "EDP8_MCP_PORT", "int", 9402, "Network", "MCP proxy port.", restart_required="mcp")
declare("pool.host", "EDP_POOL_HOST", "str", "127.0.0.1", "Network", "Seat pool bind host.",
        restart_required="pool")
declare("pool.port", "EDP_POOL_PORT", "int", 9301, "Network", "Seat pool port.", restart_required="pool")
declare("broker.host", "EDP_BROKER_HOST", "str", "127.0.0.1", "Network", "Broker bind host.",
        restart_required="broker")
declare("broker.port", "EDP_BROKER_PORT", "int", 9300, "Network", "Broker port.", restart_required="broker")

declare("supervisor.control_port", "EDP_CONTROL_PORT", "int", 0, "Network",
        "The supervisor's loopback control port (S5 service control); 0 = a free port, recorded in the run dir.",
        restart_required="supervisor")

# ---- shared between board-side seat runners and the pool that launches them
declare("pool.agent_home", "EDP_POOL_AGENT_HOME", "path", lambda: agent_home(), "Seats & models",
        "The agent home the pool serves (spawned shells' cwd, skills); exported to every seat.",
        default_doc="the agent home", restart_required="pool")
declare("lanes.dir", "EDP8_LANE_DIR", "path", None, "Limits/tuning",
        "Override dir for the host-wide admission lane files.")
declare("mcp.upload_root", "EDP8_UPLOAD_ROOT", "path", None, "Limits/tuning",
        "Workspace root local uploads are resolved against (MCP artifact_upload).", restart_required="mcp")
declare("seats.skip_permissions", "EDP_SKIP_PERMISSIONS", "bool", False, "Seats & models",
        "Seats run without permission prompts (claude --dangerously-skip-permissions, codex "
        "danger-full-access).", restart_required="pool")
# ---- the supervisor relaunches a dead service as `<python> -m <module>`, never through a shell (S2)
for _svc, _dflt in (("board", "the supervisor's own python"), ("broker", "<repo>/edp-broker/.venv python"),
                    ("pool", "<pool dir>/.venv python"), ("mcp", "the supervisor's own python"),
                    ("bridge", "the supervisor's own python")):
    declare(f"services.{_svc}.python", f"EDP_{_svc.upper()}_PYTHON", "path", None, "Paths",
            f"Python the supervisor restarts the {_svc} service with.", default_doc=_dflt)

# ---- external tools (edp_contracts.toolpath: the setting, else PATH; S2 s-b7ec13d748)
declare("tools.node", "EDP_NODE_BIN", "path", None, "Seats & models",
        "node executable (Pi's cli.js, the codex seat's WebSocket monitor); default `node` on PATH.")
declare("tools.git", "EDP_GIT_BIN", "path", None, "Seats & models",
        "git executable; default `git` on PATH. On Windows it also locates Git's bash.")
declare("tools.bash", "EDP_BASH_BIN", "path", None, "Seats & models",
        "bash for scripts and the codex Monitor tool; default Git's bash next to git (Windows) or `bash` "
        "on PATH.")
declare("seats.monitor_shell", "EDP_MONITOR_SHELL", "str", None, "Seats & models",
        "Shell the codex seat's Monitor tool runs under; default bash (Git Bash on Windows).")
declare("seats.monitor_variant", "EDP_MONITOR_VARIANT", "str", "persistent", "Seats & models",
        "codex seat Monitor tool variant.")
declare("codex.bin", "EDP_CODEX_BIN", "path", None, "Seats & models",
        "codex executable; default `codex` on PATH.", restart_required="pool")
declare("codex.model", "EDP_CODEX_MODEL", "str", "gpt-6-astra", "Seats & models",
        "Default model of a codex seat.", restart_required="pool")
declare("codex.effort", "EDP_CODEX_EFFORT", "str", None, "Seats & models",
        "Reasoning effort of a codex seat (low|medium|high).", restart_required="pool")
declare("codex.sandbox", "EDP_CODEX_SANDBOX", "str", None, "Seats & models",
        "Overrides the per-role codex sandbox.", restart_required="pool")
declare("pi.bin", "EDP_PI_BIN", "path", None, "Seats & models",
        "Pi executable or <pi-coding-agent>/dist/cli.js; default `pi` on PATH.", restart_required="pool")
declare("pi.harness", "EDP_PI_HARNESS", "path", None, "Seats & models",
        "Dir of the npm-installed Pi harness (node_modules inside).", restart_required="pool")
declare("pi.model", "EDP_PI_MODEL", "str", "openai-codex/gpt-6-astra", "Seats & models",
        "Default provider/model of a Pi seat.", restart_required="pool")
declare("pi.thinking", "EDP_PI_THINKING", "str", None, "Seats & models", "Thinking level of a Pi seat.",
        restart_required="pool")
# set by the pool per spawn, read by the seat runner (never configured)
for _name, _doc in (
    ("EDP_ACTIVATION", "Explicit first prompt of a spawned seat (park/resume path)."),
    ("EDP_CARD", "Per-flow role card a spawned seat boots (e.g. engineer-quick)."),
    ("EDP_CODEX_RESUME", "1: the codex seat resumes its recorded thread."),
    ("EDP_CODEX_CONSOLE", "1: the codex seat is visible (native TUI joins its thread)."),
    ("EDP_PI_RESUME", "1: the Pi seat resumes its session file."),
):
    declare(f"spawn.{_name.lower()}", _name, "str", None, "Seats & models", _doc, env_only=True)

declare("seats.harnesses", "EDP_HARNESSES", "list", None, "Seats & models",
        "Selected seat harnesses (claude, codex, pi; at least one of claude/codex), set by `heronry init`; "
        "models.json `harnesses` wins when present.", restart_required="board")

# ---- models catalog (edp_contracts.seats)
declare("models.config", "EDP_MODELS_CONFIG", "path", None, "Seats & models",
        "Path of the models catalog; default <agent home>/models.json.", restart_required="none")
