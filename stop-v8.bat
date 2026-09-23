@echo off
rem Thin wrapper: stops the whole fleet through edp.ps1 (safe pid-chain stop, no tree kill).
rem -Force because a full stop takes the pool (and so every seat) offline by intent.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0edp.ps1" stop all -Force
