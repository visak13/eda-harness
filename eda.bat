@echo off
rem eda.bat — launch the EDA base session with the personal config, from anywhere.
rem Equivalent to the PowerShell `claude-personal` function, pinned to the agent home
rem so project hooks (.claude\settings.json), MCP config, and skills always load.
rem Usage:
rem   eda                       start a fresh base session
rem   eda --resume <session-id> resume a suspended neuron session (W11)
rem   eda <any claude args>     everything is passed through
set "CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-personal"
rem Tiering adoption (DESIGN-v6 W1): start-stack.bat sets this for spawned shells,
rem but the foreground neuron - where most record_* saves originate - is launched
rem here, outside start-stack. Without it, foreground saves never dehydrate.
set "EDP_TIER_WRITE=1"
rem Context-diet Phase 6 (2026-08-01): the pool stamps this for spawned
rem shells; the foreground neuron launches HERE and ran to 95% of the 1M
rem window before compacting. Same 350k effective window; pre-set wins.
if not defined CLAUDE_CODE_AUTO_COMPACT_WINDOW set "CLAUDE_CODE_AUTO_COMPACT_WINDOW=350000"
rem v7 WS4 (2026-08-06): outcome-lineage write gates ON — the compiled boot
rem docs teach `serves`/`affects`, so empty-serves refusals are now live for
rem NEW steps/actions (legacy objects unaffected). Set to 0 to revert.
if not defined EDP_V7_WRITE_GATES set "EDP_V7_WRITE_GATES=1"
rem WP2 (2026-08-12): token/cost observability for the FOREGROUND seat.
rem Spawned shells get this from pty_launcher.build_env; the foreground
rem neuron launches HERE. console exporter -> metrics land in this window's
rem scrollback and /usage stays authoritative; no collector needed.
if not defined CLAUDE_CODE_ENABLE_TELEMETRY set "CLAUDE_CODE_ENABLE_TELEMETRY=1"
if not defined OTEL_METRICS_EXPORTER set "OTEL_METRICS_EXPORTER=console"
rem F1 (2026-08-17): the base shell is the NEURON seat. Stamp the role so the
rem MCP server registers the neuron toolset (enforce mode), pin the judgment
rem model (models.json binds pool spawns only — the base shell must self-pin),
rem and skip permission prompts (the foreground neuron drives autonomously).
rem A pre-set EDP_ROLE wins (e.g. for a diagnostic role-less shell, set it "").
if not defined EDP_ROLE set "EDP_ROLE=neuron"
rem Override with `set EDA_MODEL=claude-fable-5` (etc.) before launching.
if not defined EDA_MODEL set "EDA_MODEL=claude-opus-4-8"
rem QoL Phase 1 (2026-08-21, operator ruling): spawned-shell env parity.
rem pty_launcher.build_env stamps these on every pool spawn; the foreground
rem neuron launches HERE and used to run without them, so main-vs-spawned
rem behavior silently diverged (harness detection, broker/pool reach, logs).
if not defined EDP_HARNESS set "EDP_HARNESS=claude"
if not defined EDP_AGENT_HOME set "EDP_AGENT_HOME=C:/Projects/Learning/eda-base3/claude"
if not defined EDP_BROKER_URL set "EDP_BROKER_URL=http://127.0.0.1:9300"
if not defined EDP_POOL_URL set "EDP_POOL_URL=http://127.0.0.1:9301"
if not defined EDP_LOG_DIR set "EDP_LOG_DIR=C:/Projects/Learning/eda-base3/claude/.logs"
cd /d "C:\Projects\Learning\eda-base3\claude"
claude --dangerously-skip-permissions --model %EDA_MODEL% %*
