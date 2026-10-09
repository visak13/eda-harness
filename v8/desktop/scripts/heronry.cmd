@echo off
rem The `heronry` command: bin is the only folder on PATH (the install root holds python312.dll & co).
rem After `heronry update` hands the install over, heronry.exe writes the follow script named below; calling it runs
rem the progress viewer from the runtime copy outside the install folder, so this shell waits for the result
rem (owner m-584d63e760). The last line is one command line: cmd reads it whole before heronry.exe runs, so it never
rem reads this file again while the installer replaces it. `call ... %%HERONRY_RC%%` reads the exit code when it
rem runs (heronry.exe's, or the follow script's): a plain `exit /b` after the parenthesised `if` returned 0.
setlocal
rem The shim deletes the follow script after it ran: a script deleting itself made cmd report "The batch file cannot be found".
set "HERONRY_FOLLOW=%TEMP%\heronry-follow-%RANDOM%%RANDOM%.cmd"
"%~dp0..\heronry.exe" %* & call set "HERONRY_RC=%%ERRORLEVEL%%" & (if exist "%HERONRY_FOLLOW%" (call "%HERONRY_FOLLOW%" & call set "HERONRY_RC=%%ERRORLEVEL%%" & del "%HERONRY_FOLLOW%" 2>nul)) & call exit /b %%HERONRY_RC%%
