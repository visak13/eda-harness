@echo off
rem ============================================================================
rem  panel-window.bat ? the EDP control panel as a FLOATING, ALWAYS-ON-TOP
rem  window (picture-in-picture style): pause/play recipe trees, approve tool
rem  calls, answer gates ? one click away over any app.
rem
rem  Needs the stack up (start-stack.bat). pywebview is supplied ephemerally
rem  by uv (--with), so the project's locked dependencies are untouched.
rem ============================================================================
setlocal
cd /d "%~dp0claude"
uv run --with pywebview python scripts\panel_window.py %*
endlocal
