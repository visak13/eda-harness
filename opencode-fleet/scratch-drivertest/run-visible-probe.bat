@echo off
title edp-drivertest (visible probe)
cd /d C:\Projects\Learning\eda-base3\opencode-fleet
set XDG_DATA_HOME=C:\Projects\Learning\eda-base3\opencode-fleet\.fleet-data
"C:\Users\aksou\AppData\Local\nvm\v25.1.0\node_modules\opencode-ai\node_modules\opencode-windows-x64-baseline\bin\opencode.exe" run "Call edp_driver_status, then arm a test cron with edp_cron_create name=visible-probe interval_seconds=600 prompt='visible probe tick', then edp_cron_list, then edp_cron_delete name=visible-probe to clean up. Report each result. This is a visibility drill." --model openai/gpt-5.6-terra --auto --print-logs --log-level WARN
echo.
echo ---- probe finished (exit %errorlevel%) ----
pause
