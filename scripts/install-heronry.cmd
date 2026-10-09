@echo off
rem Install the Heronry Desktop .msi that sits beside this script, by hand (owner m-584d63e760): the one tested way when
rem `heronry update` cannot do a hop (the installed version's own updater runs it). Shipped in every release folder.
rem
rem   install-heronry.cmd            verify, stop Heronry, install, start, and show the version
rem   install-heronry.cmd --check    only verify the installer and list what would block it; changes nothing
rem
rem It shows each step and ends with the result; the window stays open until a key is pressed. Nothing is hidden:
rem the Windows Installer shows its own progress bar, and its log is named at the end.
setlocal EnableExtensions
set "HERE=%~dp0"
set "DIR=%LOCALAPPDATA%\Programs\Heronry contributors\Heronry Desktop"
set "EXE=%DIR%\heronry.exe"
set "LOG=%TEMP%\heronry-install-msi.log"
set "MODE=%~1"
set "MSI="
for %%F in ("%HERE%Heronry Desktop-*.msi") do set "MSI=%%~fF"
echo Heronry install: this window ends with the result.
echo   installer: "%MSI%"
echo   folder:    "%DIR%"
echo.

echo [1/6] Checking the installer against SHA256SUMS
if not defined MSI (echo   No "Heronry Desktop-*.msi" beside this script. & goto :fail)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$n = Split-Path -Leaf $env:MSI; $s = (Get-FileHash -Algorithm SHA256 -LiteralPath $env:MSI).Hash.ToLower(); $l = @(Get-Content -LiteralPath (Join-Path $env:HERE 'SHA256SUMS') -ErrorAction SilentlyContinue | Where-Object { $_.EndsWith('  ' + $n) }); if (-not $l) { '  ' + $n + ' is not listed in SHA256SUMS'; exit 1 }; if ($l[0].Split(' ')[0] -ne $s) { '  checksum mismatch for ' + $n; exit 1 }; '  OK ' + $s"
if errorlevel 1 goto :fail

set "CODE_WAS_RUNNING="
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine + '') -like '*--heronry-service code-guard*' }) { exit 1 }"
if errorlevel 1 set "CODE_WAS_RUNNING=1"

if /i "%MODE%"=="--check" (
  echo [2/6] --check: Heronry is not stopped
  call :holders
  echo.
  echo Check done: nothing was changed.
  goto :end
)

echo [2/6] Stopping the code server and the Heronry services (seats go offline; they resume from the board)
if exist "%EXE%" (
  "%EXE%" stop code
  "%EXE%" stop --force
) else (
  echo   Heronry is not installed in that folder: nothing to stop
)

echo [3/6] Checking that nothing still runs from the install folder
call :holders
if errorlevel 1 (
  echo   These hold files the installer must replace. A seat's feed monitor is safe to stop: the seat resumes later.
  choice /c YN /m "  Stop them now"
  if errorlevel 2 (echo   Not stopped; nothing was installed. & goto :fail)
  powershell -NoProfile -Command "$d = $env:DIR.TrimEnd('\') + '\'; Get-CimInstance Win32_Process | Where-Object { (($_.ExecutablePath + '').StartsWith($d, 'OrdinalIgnoreCase')) -or (($_.CommandLine + '').IndexOf($d, [StringComparison]::OrdinalIgnoreCase) -ge 0) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; '  stopped ' + $_.ProcessId }"
  call :holders
  if errorlevel 1 (echo   Still running; nothing was installed. & goto :fail)
)

echo [4/6] Installing (the Windows Installer shows its progress bar; log "%LOG%")
start "" /wait msiexec /i "%MSI%" MSIINSTALLPERUSER=1 ALLUSERS=2 INSTALLFOLDER="%DIR%" /passive /norestart /l*v "%LOG%"
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (echo   installed) else if "%RC%"=="3010" (echo   installed; Windows wants a restart later) else (
  echo   msiexec exit %RC%: not installed. Windows Installer rolled its changes back; see "%LOG%"
  echo   Heronry is started again as it was.
  "%EXE%" start
  goto :fail
)

rem keep this installer as the next `heronry update`'s way back: the updater looks for the installed version's MSI in
rem <data>\updates\<version>\ (updater.cached_msi) and refuses to update without one (owner m-4b4e1dac4f)
for %%F in ("%MSI%") do set "MSINAME=%%~nF"
set "VER=%MSINAME:Heronry Desktop-=%"
set "CACHE=%LOCALAPPDATA%\heronry\data\updates\%VER%"
if not exist "%CACHE%" mkdir "%CACHE%"
copy /y "%MSI%" "%CACHE%\" >nul && copy /y "%HERE%SHA256SUMS" "%CACHE%\SHA256SUMS" >nul && (echo   kept the installer for the next update's rollback: "%CACHE%") || (echo   could not keep the installer in "%CACHE%": the next `heronry update` will need --previous-url)

echo [5/6] Starting Heronry
"%EXE%" start
if defined CODE_WAS_RUNNING "%EXE%" start code

echo [6/6] Status
"%EXE%" status
echo.
"%EXE%" version
echo.
echo Done. Resume each seat from the board; a Claude Code session that was open may need /mcp, Reconnect edp8.
goto :end

:holders
rem every process whose exe lies in the install folder, or whose command line names it (an exe an earlier installer
rem moved to C:\Config.Msi still runs with its old command line); exit 1 when there is any
powershell -NoProfile -Command "$d = $env:DIR.TrimEnd('\') + '\'; $p = @(Get-CimInstance Win32_Process | Where-Object { (($_.ExecutablePath + '').StartsWith($d, 'OrdinalIgnoreCase')) -or (($_.CommandLine + '').IndexOf($d, [StringComparison]::OrdinalIgnoreCase) -ge 0) }); foreach ($x in $p) { $c = (($x.CommandLine + '').Replace('\"' + $d, '').Replace($d, '') -replace '\s+', ' ');'  pid {0,-6} {1}  {2}' -f $x.ProcessId, $x.Name, $c.Substring(0, [Math]::Min(100, $c.Length)) }; if ($p.Count) { exit 1 } else { '  none' }"
exit /b %ERRORLEVEL%

:fail
echo.
echo The install did not complete. Nothing above was hidden; the installer's log is "%LOG%".
pause
exit /b 1

:end
pause
exit /b 0
