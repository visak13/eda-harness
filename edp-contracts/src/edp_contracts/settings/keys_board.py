"""Settings declared for board (see keys_common for shared ones)."""
from __future__ import annotations

from ._core import config_dir, data_dir, declare

# ---- board service
declare("board.ui", "EDP8_UI", "str", "folio", "Limits/tuning",
        "Which renderer owns /ui: folio (the SPA; legacy kept at /ui-legacy) or legacy (no SPA).",
        restart_required="board",
        tier="advanced", label='Web app style',
        help='Which web app the board serves: folio is the current app, legacy the old one.', choices=("folio", "legacy"))
declare("board.web_dist", "EDP8_WEB_DIST", "str", None, "Platform",
        "Directory of the SPA bundle the board serves at /ui; unset = the packaged src/edp8/webapp/dist. An e2e "
        "board points it at its private build (t-b2f8859d30), so a seat's build never ships to the fleet.",
        env_only=True, restart_required="board",
        tier="internal")
declare("board.log_level", "EDP8_LOG", "str", "warning", "Limits/tuning", "The board's uvicorn log level.",
        restart_required="board",
        tier="advanced", label='Board log detail',
        help="How much the board's web server writes to its log. Use debug only while chasing a problem.", choices=("debug", "info", "warning", "error", "critical"))
declare("board.timing", "EDP8_TIMING", "bool", False, "Limits/tuning",
        "Log every request's route template, status, ms and bytes to <logs>/timing.jsonl (S22 profiling).",
        restart_required="board",
        tier="advanced", label='Log request timings',
        help='Write how long every board request takes to a log file, to find what makes the app slow.')
declare("board.upload_sweep", "EDP8_UPLOAD_SWEEP", "bool", True, "Limits/tuning",
        "Hourly sweep of staged uploads nobody finalised (the startup sweep always runs).",
        restart_required="board",
        tier="advanced", label='Clean up abandoned uploads',
        help='Every hour, delete files that were uploaded but never attached to anything.')
declare("board.pool_watch", "EDP8_POOL_WATCH", "bool", False, "Seats & models",
        "Run the pool session mirror even without EDP_POOL_URL set.", restart_required="board",
        tier="internal")
declare("board.pool_id", "EDP8_POOL_ID", "str", "local", "Seats & models",
        "The id this board gives the seat pool it spawns through.", restart_required="board",
        tier="internal")
declare("board.git_rev", "EDP8_GIT_REV", "str", None, "Platform",
        "The running tree's git rev (the launcher injects it); unset = read .git under EDP_HOME.",
        env_only=True,
        tier="internal")

# ---- tool payload budgets
declare("board.tool_call_cap_s", "EDP8_TOOL_CALL_CAP_S", "float", 30.0, "Limits/tuning",
        "Seconds one MCP tool call may take before it is answered as still running.", restart_required="mcp",
        tier="advanced", label='Agent tool time limit',
        help='How long one agent request to the board may run before the agent is told it is still running.')
declare("board.context_budget_b", "EDP8_CONTEXT_BUDGET_B", "int", 8_000, "Limits/tuning",
        "Byte cap of the bounded context() snapshot (floor 4000).", restart_required="mcp",
        tier="advanced", label='Agent briefing size',
        help="The most an agent's starting briefing may hold. Larger gives agents more detail but uses more of their context.")
declare("board.tool_page_b", "EDP8_TOOL_PAGE_B", "int", 8_000, "Limits/tuning",
        "Byte cap of one list/query tool page (ticket_query, doc_query, participants, ...; floor 2000).",
        restart_required="mcp", tier="advanced", label='Agent list page size',
        help='The most one list an agent asks for may hold before it is split into pages.')
declare("board.delta_budget_b", "EDP8_DELTA_BUDGET_B", "int", 12_000, "Limits/tuning",
        "Byte cap of one context_delta page (floor 4000).", restart_required="board",
        tier="advanced", label='Agent update size',
        help='The most one batch of updates to an agent may hold.')
declare("board.feed_event_b", "EDP8_FEED_EVENT_B", "int", 2_000, "Limits/tuning",
        "Byte cap of one feed_driver output line (floor 600).",
        tier="advanced", label='Agent wake line size',
        help='The most one wake-up line sent to an agent may hold.')

# ---- MCP proxy
declare("mcp.role", "EDP8_ROLE", "str", None, "Identity",
        "Role of a stdio MCP server when whoami cannot answer at start; falls back to EDP_ROLE.",
        aliases=("EDP_ROLE",), env_only=True,
        tier="internal")
declare("mcp.transport", "EDP8_MCP_TRANSPORT", "str", "", "Network",
        "stdio runs the MCP server per shell over stdio; anything else serves shared streamable-http.",
        restart_required="mcp",
        tier="advanced", label='Agent tools connection',
        help='How agents connect to the board: shared (one service for all agents) or stdio (one per agent, for troubleshooting).', choices=("", "stdio"))

# ---- embedder / search
declare("search.embed_threads", "EDP8_EMBED_THREADS", "int", 1, "Embedder/search",
        "onnxruntime intra-op threads of the embedding model.", restart_required="board",
        tier="advanced", label='Search indexing threads',
        help='CPU threads used to index text for search. More is faster but takes CPU from everything else.')
declare("search.embed_arena", "EDP8_EMBED_ARENA", "bool", False, "Embedder/search",
        "Keep onnxruntime's CPU memory arena (off: board RSS tracks live use).", restart_required="board",
        tier="advanced", label='Search memory reuse',
        help="Keep memory the search model used, for a little more speed. Off keeps the board's memory use lower.")
declare("search.embed_model", "EDP8_EMBED_MODEL", "str", "nomic-ai/nomic-embed-text-v1.5", "Embedder/search",
        "fastembed model used for dense search.", restart_required="board",
        tier="advanced", label='Search model',
        help='The model that turns text into search vectors. Changing it rebuilds the search index.')
declare("search.embed_cache", "EDP8_EMBED_CACHE", "path", None, "Embedder/search",
        "Folder the embedding model is downloaded to; unset = <data>/models when installed, fastembed's own "
        "default (FASTEMBED_CACHE_PATH, else a temp folder) in dev mode.", default_doc="<data>/models",
        restart_required="board", tier="internal")
declare("search.ollama_url", "EDP8_OLLAMA_URL", "url", "http://127.0.0.1:11434", "Embedder/search",
        "Ollama base URL for the ollama embedder.", restart_required="board",
        tier="advanced", label='Ollama address',
        help='Where Ollama runs, when search uses Ollama.')
declare("search.embedder", "EDP8_EMBEDDER", "str", None, "Embedder/search",
        "Force the embedder: fastembed, ollama or none; unset = fastembed, then ollama, then none.",
        restart_required="board",
        tier="basic", label='Search engine',
        help='How the board finds related records: fastembed (built in), ollama (a local Ollama server) or none (words only). Leave empty to pick automatically.', choices=("fastembed", "ollama", "none"))
declare("search.vec_cache", "EDP8_VEC_CACHE", "path", None, "Embedder/search",
        "Embedding cache SQLite file; unset = <board db>.vec.", default_doc="<db>.vec", restart_required="board",
        tier="internal")

# ---- RSI regression tripwire (S18)
declare("rsi.enabled", "EDP8_RSI", "bool", False, "Limits/tuning",
        "Run the RSI retrieval-regression sweep in the board (re-read every loop).", restart_required="board",
        tier="advanced", label='Search quality check',
        help='Run a background check that warns when search results get worse.')
declare("rsi.ram_floor_mb", "EDP8_RSI_RAM_FLOOR_MB", "int", 1500, "Limits/tuning",
        "Free RAM (MB) below which an RSI tick holds instead of running.", restart_required="board",
        tier="advanced", label='Search check memory floor',
        help='The search quality check waits while free memory is below this.')
declare("rsi.interval_s", "EDP8_RSI_INTERVAL_S", "float", 900.0, "Limits/tuning",
        "Seconds between RSI sweep ticks.", restart_required="board",
        tier="advanced", label='Search check interval',
        help='Time between search quality checks.')
declare("rsi.warm_s", "EDP8_RSI_WARM_S", "float", 900.0, "Limits/tuning",
        "Seconds the RSI CLI waits for the dense index to warm.",
        tier="advanced", label='Search check warm-up',
        help='How long the search check waits for the search index to load.')

# ---- integrations
declare("plane.url", "EDP8_PLANE_URL", "url", None, "Integrations",
        "Plane base URL; set turns on the Plane mirror and webhook.", restart_required="board",
        tier="advanced", label='Plane address',
        help='Your Plane server. Setting it turns on the Plane mirror; Admin → Integrations sets this for you.')
declare("plane.api_key", "EDP8_PLANE_API_KEY", "str", "", "Integrations", "Plane API key.",
        secret=True, restart_required="board",
        tier="advanced", label='Plane API key',
        help='The key the board uses to write to Plane. Kept private, never shown again.')
declare("plane.workspace", "EDP8_PLANE_WORKSPACE", "str", "", "Integrations", "Plane workspace slug.",
        restart_required="board",
        tier="advanced", label='Plane workspace',
        help='The Plane workspace tickets are mirrored into.')
declare("plane.project", "EDP8_PLANE_PROJECT", "str", "", "Integrations", "Plane project id.",
        restart_required="board",
        tier="advanced", label='Plane project',
        help='The Plane project tickets are mirrored into.')
declare("plane.states", "EDP8_PLANE_STATES", "str", None, "Integrations",
        "JSON map of ticket status to Plane state; unset = identity map.", restart_required="board",
        tier="advanced", label='Plane status map',
        help='Which Plane state each ticket status becomes, as JSON. Leave empty to use the same names.')
declare("plane.webhook_secret", "EDP8_PLANE_WEBHOOK_SECRET", "str", "", "Integrations",
        "HMAC secret the Plane webhook signature is checked against; empty = unchecked.",
        secret=True, restart_required="board",
        tier="advanced", label='Plane webhook secret',
        help='The secret Plane signs its webhook calls with, so the board can trust them.')
declare("slack.map", "EDP8_SLACK_MAP", "path", lambda: config_dir() / "slack_map.json", "Integrations",
        "The Slack bridge's handle→user map and settings file.", default_doc="<config>/slack_map.json",
        restart_required="all",
        tier="internal")
declare("code_server.port", "EDP_CODE_PORT", "int", 9410, "Integrations",
        "code-server port: the loopback guard `heronry start code` puts in front of code-server holds it.",
        restart_required="board",
        tier="advanced", label='VS Code in the browser port',
        help='The port of the browser VS Code the board links to. Match it to where you run code-server.')
# S21 (s-0cfebd3862): the code server is an optional managed service (edp8.code_service)
declare("code_server.path", "EDP_CODE_SERVER_PATH", "path", None, "Integrations",
        "code-server executable (or its entry .js); default `code-server` on PATH.", restart_required="none",
        tier="advanced", label='code-server program',
        help='Where code-server is installed, if it is not on your PATH. Leave empty to find it on the PATH.')
declare("code_server.autostart", "EDP_CODE_AUTOSTART", "bool", False, "Integrations",
        "`heronry start` also starts the code server (it is opt-in: `heronry start code`).", restart_required="none",
        tier="basic", label='Start VS Code in the browser with Heronry',
        help='Start the code server whenever Heronry starts. Off: start it yourself from Admin → Services or the tray.')
declare("code_server.host", "EDP_CODE_HOST", "str", "127.0.0.1", "Integrations",
        "code-server bind host; loopback only (anyone who reaches it owns the host through its terminal), so any "
        "other value is refused.", restart_required="none",
        tier="internal")
declare("code_server.data", "EDP_CODE_DATA", "path", lambda: data_dir() / "code", "Integrations",
        "code-server's user-data and extensions dirs.", default_doc="<data>/code", restart_required="none",
        tier="internal")

# ---- Admin console (S5, design-e963c656f5 §4.8): Tailscale auth keys for teammates' machines (R7b)
declare("tailscale.oauth_client_id", "EDP_TAILSCALE_OAUTH_CLIENT_ID", "str", "", "Network",
        "Tailscale OAuth client id (scope auth_keys) that mints teammates' auth keys; empty = feature off.",
        restart_required="none",
        tier="basic", label='Tailscale OAuth client id',
        help="Lets you mint Tailscale keys so a colleague's machine can join your tailnet. Create the client in Tailscale with the auth_keys scope.")
declare("tailscale.oauth_client_secret", "EDP_TAILSCALE_OAUTH_CLIENT_SECRET", "str", "", "Network",
        "Tailscale OAuth client secret for the client above.", secret=True, restart_required="none",
        tier="basic", label='Tailscale OAuth client secret',
        help='The secret of the Tailscale OAuth client above. Kept private, never shown again.')
declare("tailscale.tailnet", "EDP_TAILSCALE_TAILNET", "str", "-", "Network",
        "Tailnet the auth keys are minted in; '-' = the OAuth client's own tailnet.", restart_required="none",
        tier="advanced", label='Tailnet',
        help="The tailnet new keys are made in. Leave '-' for the OAuth client's own tailnet.")
declare("tailscale.key_tags", "EDP_TAILSCALE_KEY_TAGS", "list", ["tag:heronry"], "Network",
        "Tags a minted auth key applies to the new device (an OAuth-minted key must carry tags).",
        restart_required="none",
        tier="advanced", label='Tailscale key tags',
        help="Tags a colleague's machine gets when it joins with a minted key.")
declare("tailscale.api_url", "EDP_TAILSCALE_API_URL", "url", "https://api.tailscale.com", "Network",
        "Tailscale API base URL (tests point it at a mock).", restart_required="none",
        tier="internal")
