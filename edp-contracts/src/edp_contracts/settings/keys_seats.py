"""Settings declared for seats (see keys_common for shared ones): the inference lane, uploads, per-person
UI files, knowledge ranking, records and the code-server guard handoff."""
from __future__ import annotations

from ._core import agent_home, data_dir, declare, home

# ---- the cross-process inference lane (edp8.admission; read at import by seats and the pool)
declare("lanes.ttl_s", "EDP8_LANE_TTL_S", "int", 900, "Limits/tuning",
        "Seconds a lane holder may go without touching its lock before it is treated as dead.",
        restart_required="pool",
        tier="advanced", label='Model queue lock timeout',
        help='An agent holding its turn in the model queue this long without activity is treated as gone.')
declare("lanes.queue_stale_s", "EDP8_LANE_QUEUE_STALE_S", "float", 10.0, "Limits/tuning",
        "Seconds an untouched lane queue ticket lives before a waiter removes it as dead.",
        restart_required="pool",
        tier="advanced", label='Model queue cleanup',
        help='A waiting spot in the model queue untouched this long is removed.')
declare("lanes.aging_s", "EDP8_LANE_AGING_S", "float", 120.0, "Limits/tuning",
        "Seconds a lane ticket waits before it sorts as top priority (anti-starvation).",
        restart_required="pool",
        tier="advanced", label='Model queue fairness',
        help='An agent waiting this long in the model queue goes to the front, so nobody waits forever.')

# ---- uploads (edp8.http_upload, read by the MCP proxy at startup)
declare("uploads.http_mode", "EDP8_HTTP_UPLOAD_MODE", "str", None, "Integrations",
        "'single-host' enables MCP uploads over HTTP from local seats; anything else disables them.",
        restart_required="mcp",
        tier="advanced", label='Agent file uploads',
        help='single-host lets agents on this computer attach files to the board; off turns uploads off.', choices=("single-host", "off"))
declare("uploads.http_policy", "EDP8_HTTP_UPLOAD_POLICY", "path", None, "Integrations",
        "Absolute path of the HTTP upload policy JSON (workspace root and per-seat roots).",
        restart_required="mcp",
        tier="advanced", label='Upload rules file',
        help='A JSON file that says which folders agents may upload from.')

# ---- per-person UI files and integrations (board)
declare("ui.settings_file", "EDP8_UI_SETTINGS", "path", lambda: agent_home() / "ui-settings.json", "Paths",
        "Per-person UI settings file (profile, notifications, Slack).",
        default_doc="<agent home>/ui-settings.json", restart_required="none",
        tier="internal")
declare("slack.webhook_hosts", "EDP8_SLACK_WEBHOOK_HOSTS", "list", [], "Integrations",
        "Extra allowed Slack webhook hosts (comma-separated) besides hooks.slack.com.",
        tier="advanced", label='Extra Slack webhook hosts',
        help='Other hosts besides hooks.slack.com that Slack notifications may be sent to.')
declare("usage.config", "EDP8_USAGE_CONFIG", "path", None, "Integrations",
        "Operator ACL JSON mapping participants to the provider usage they may see; unset = none.",
        tier="advanced", label='Usage access rules',
        help="A JSON file that says who may see which provider's usage and quota.")

# ---- knowledge and records (board)
declare("search.ranked_floor", "EDP8_RANKED_FLOOR", "float", 0.35, "Embedder/search",
        "Drop ranked records scoring below this fraction of the top hit (0 disables).",
        restart_required="board",
        tier="advanced", label='Search relevance cut-off',
        help='Results scoring below this share of the best match are dropped. 0 keeps everything.')
declare("records.auto_cap", "EDP8_AUTO_RECORD_CAP", "int", 60, "Limits/tuning",
        "Auto-recorded decisions allowed per epic.",
        tier="advanced", label='Automatic decisions per epic',
        help='How many decisions the board may record on its own for one epic.', unit="decisions")
declare("records.pain_file", "EDP8_PAIN_FILE", "path",
        lambda: (home() or data_dir()) / ".pain" / "pain-points.jsonl", "Paths",
        "The pain-point log (JSONL) the pain skill appends to and the board reads.",
        default_doc="<EDP_HOME>/.pain/pain-points.jsonl, else <data>/.pain/pain-points.jsonl",
        tier="internal")

# ---- code-server guard: one-shot secrets the board hands the guard by env, popped at start
declare("code_guard.session", "CODE_GUARD_SESSION", "str", None, "Integrations",
        "code-server session secret handed to the code guard (removed from its env at start).",
        env_only=True, secret=True,
        tier="internal")
declare("code_guard.mint_key", "CODE_GUARD_MINT_KEY", "str", None, "Integrations",
        "Key the board signs code-guard sign-in tokens with (removed from the guard's env at start).",
        env_only=True, secret=True,
        tier="internal")
