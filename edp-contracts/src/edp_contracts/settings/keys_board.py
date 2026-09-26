"""Settings declared for board (see keys_common for shared ones)."""
from __future__ import annotations

from ._core import config_dir, declare

# ---- board service
declare("board.ui", "EDP8_UI", "str", "folio", "Limits/tuning",
        "Which renderer owns /ui: folio (the SPA; legacy kept at /ui-legacy) or legacy (no SPA).",
        restart_required="board")
declare("board.log_level", "EDP8_LOG", "str", "warning", "Limits/tuning", "The board's uvicorn log level.",
        restart_required="board")
declare("board.upload_sweep", "EDP8_UPLOAD_SWEEP", "bool", True, "Limits/tuning",
        "Hourly sweep of staged uploads nobody finalised (the startup sweep always runs).",
        restart_required="board")
declare("board.pool_watch", "EDP8_POOL_WATCH", "bool", False, "Seats & models",
        "Run the pool session mirror even without EDP_POOL_URL set.", restart_required="board")
declare("board.pool_id", "EDP8_POOL_ID", "str", "local", "Seats & models",
        "The id this board gives the seat pool it spawns through.", restart_required="board")
declare("board.git_rev", "EDP8_GIT_REV", "str", None, "Platform",
        "The running tree's git rev (the launcher injects it); unset = read .git under EDP_HOME.",
        env_only=True)

# ---- tool payload budgets
declare("board.tool_call_cap_s", "EDP8_TOOL_CALL_CAP_S", "float", 30.0, "Limits/tuning",
        "Seconds one MCP tool call may take before it is answered as still running.", restart_required="mcp")
declare("board.context_budget_b", "EDP8_CONTEXT_BUDGET_B", "int", 40_000, "Limits/tuning",
        "Byte cap of the bounded context() snapshot (floor 4000).", restart_required="mcp")
declare("board.delta_budget_b", "EDP8_DELTA_BUDGET_B", "int", 12_000, "Limits/tuning",
        "Byte cap of one context_delta page (floor 4000).", restart_required="board")
declare("board.feed_event_b", "EDP8_FEED_EVENT_B", "int", 2_000, "Limits/tuning",
        "Byte cap of one feed_driver output line (floor 600).")

# ---- MCP proxy
declare("mcp.role", "EDP8_ROLE", "str", None, "Identity",
        "Role of a stdio MCP server when whoami cannot answer at start; falls back to EDP_ROLE.",
        aliases=("EDP_ROLE",), env_only=True)
declare("mcp.transport", "EDP8_MCP_TRANSPORT", "str", "", "Network",
        "stdio runs the MCP server per shell over stdio; anything else serves shared streamable-http.",
        restart_required="mcp")

# ---- embedder / search
declare("search.embed_threads", "EDP8_EMBED_THREADS", "int", 1, "Embedder/search",
        "onnxruntime intra-op threads of the embedding model.", restart_required="board")
declare("search.embed_arena", "EDP8_EMBED_ARENA", "bool", False, "Embedder/search",
        "Keep onnxruntime's CPU memory arena (off: board RSS tracks live use).", restart_required="board")
declare("search.embed_model", "EDP8_EMBED_MODEL", "str", "nomic-ai/nomic-embed-text-v1.5", "Embedder/search",
        "fastembed model used for dense search.", restart_required="board")
declare("search.ollama_url", "EDP8_OLLAMA_URL", "url", "http://127.0.0.1:11434", "Embedder/search",
        "Ollama base URL for the ollama embedder.", restart_required="board")
declare("search.embedder", "EDP8_EMBEDDER", "str", None, "Embedder/search",
        "Force the embedder: fastembed, ollama or none; unset = fastembed, then ollama, then none.",
        restart_required="board")
declare("search.vec_cache", "EDP8_VEC_CACHE", "path", None, "Embedder/search",
        "Embedding cache SQLite file; unset = <board db>.vec.", default_doc="<db>.vec", restart_required="board")

# ---- RSI regression tripwire (S18)
declare("rsi.enabled", "EDP8_RSI", "bool", False, "Limits/tuning",
        "Run the RSI retrieval-regression sweep in the board (re-read every loop).", restart_required="board")
declare("rsi.ram_floor_mb", "EDP8_RSI_RAM_FLOOR_MB", "int", 1500, "Limits/tuning",
        "Free RAM (MB) below which an RSI tick holds instead of running.", restart_required="board")
declare("rsi.interval_s", "EDP8_RSI_INTERVAL_S", "float", 900.0, "Limits/tuning",
        "Seconds between RSI sweep ticks.", restart_required="board")
declare("rsi.warm_s", "EDP8_RSI_WARM_S", "float", 900.0, "Limits/tuning",
        "Seconds the RSI CLI waits for the dense index to warm.")

# ---- integrations
declare("plane.url", "EDP8_PLANE_URL", "url", None, "Integrations",
        "Plane base URL; set turns on the Plane mirror and webhook.", restart_required="board")
declare("plane.api_key", "EDP8_PLANE_API_KEY", "str", "", "Integrations", "Plane API key.",
        secret=True, restart_required="board")
declare("plane.workspace", "EDP8_PLANE_WORKSPACE", "str", "", "Integrations", "Plane workspace slug.",
        restart_required="board")
declare("plane.project", "EDP8_PLANE_PROJECT", "str", "", "Integrations", "Plane project id.",
        restart_required="board")
declare("plane.states", "EDP8_PLANE_STATES", "str", None, "Integrations",
        "JSON map of ticket status to Plane state; unset = identity map.", restart_required="board")
declare("plane.webhook_secret", "EDP8_PLANE_WEBHOOK_SECRET", "str", "", "Integrations",
        "HMAC secret the Plane webhook signature is checked against; empty = unchecked.",
        secret=True, restart_required="board")
declare("slack.map", "EDP8_SLACK_MAP", "path", lambda: config_dir() / "slack_map.json", "Integrations",
        "The Slack bridge's handle→user map and settings file.", default_doc="<config>/slack_map.json",
        restart_required="all")
declare("code_server.port", "EDP_CODE_PORT", "int", 9410, "Integrations",
        "code-server port the board links to (the one edp.ps1 starts it on).", restart_required="board")
