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
cd /d "C:\Projects\Learning\eda-base3\claude"
claude %*
