# t-08612be1b0 evidence drill: install.ps1 with a REQUIRED tool deliberately missing, in a clean temp profile.
# Nothing touches the real profile, the fleet's tools or PATH:
#   * USERPROFILE / HOME / LOCALAPPDATA / APPDATA and every uv dir point into a temp folder; uv is taken off
#     PATH (install.ps1 installs its pinned uv); EDP*/HERONRY* variables are scrubbed; cwd is outside the repo;
#   * git is taken off THIS process's PATH (every entry holding git.exe), so `heronry prereqs` finds it missing;
#   * winget is a STUB (a .cmd first on PATH) that logs its arguments and "installs" git as a shim printing
#     `git version 2.47.1.windows.1` in the temp folder. The real winget is never called;
#   * the embedding model is the small BAAI/bge-small-en-v1.5 (~67 MB), downloaded into the temp profile.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\scripts\drill_prereqs_windows.ps1 -ReleaseDir <dir>
# <dir> holds the four wheels and SHA256SUMS (uv build --wheel of edp-contracts, edp-broker, edp-pool, v8).
param([Parameter(Mandatory = $true)][string]$ReleaseDir, [switch]$Keep)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$T = Join-Path ([IO.Path]::GetTempPath()) ("heronry-prereqs-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $T | Out-Null
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function Show($text) { $text -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { "   $($_.TrimEnd())" } }

Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -like "UV_*" -or
  @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME", "FASTEMBED_CACHE_PATH") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
foreach ($d in "profile", "profile\AppData\Local", "profile\AppData\Roaming", "stubbin") { New-Item -ItemType Directory -Force -Path (Join-Path $T $d) | Out-Null }
$env:USERPROFILE = "$T\profile"; $env:HOME = "$T\profile"
$env:LOCALAPPDATA = "$T\profile\AppData\Local"; $env:APPDATA = "$T\profile\AppData\Roaming"
$env:UV_TOOL_DIR = "$T\uv-tools"; $env:UV_TOOL_BIN_DIR = "$T\bin"; $env:UV_PYTHON_INSTALL_DIR = "$T\uv-python"
$env:UV_CACHE_DIR = "$T\uv-cache"; $env:UV_NO_MODIFY_PATH = "1"
$env:HERONRY_NO_UPDATE_CHECK = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:EDP8_EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# the stub winget: logs, and turns `install --id Git.Git` into a git shim next to itself
$stub = "$T\stubbin"
Set-Content -Encoding ascii "$stub\winget.cmd" @"
@echo off
echo %* >> "%~dp0winget.log"
echo %* | findstr /c:"--id Git.Git" >nul || (echo stub winget: no such package & exit /b 1)
echo Found Git [Git.Git] Version 2.47.1 (stub winget, nothing downloaded)
> "%~dp0git.cmd" echo @echo git version 2.47.1.windows.1
echo Successfully installed
exit /b 0
"@
$kept = ($env:PATH -split ";") | Where-Object { $_ -and -not (Test-Path (Join-Path $_ "uv.exe")) -and -not (Test-Path (Join-Path $_ "heronry.exe")) -and
  -not (Test-Path (Join-Path $_ "git.exe")) }
$env:PATH = (@($stub) + $kept) -join ";"
Set-Location $T
"temp profile $T"
"git on PATH before install: $([bool](Get-Command git -ErrorAction SilentlyContinue)) · winget resolves to: $((Get-Command winget).Source)"
$ps = Join-Path $PSHOME "powershell.exe"
$args0 = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "$root\install.ps1", "-ReleaseUrl", $ReleaseDir, "-NoModifyPath")

"== 1. install.ps1, answer n: the question is asked, nothing installed"
$o = "n" | & $ps @args0 2>&1 | Out-String; Show $o
Check ($o -match "heronry prereqs will install:" -and $o -match "git\s+required: winget install --id Git.Git --exact") "the plan names git and its winget command"
Check ($o -match "Install these \d+ now\? \[Y/n\]|Install this now\? \[Y/n\]") "one yes/no question is asked"
Check ($o -match "nothing installed" -and -not (Test-Path "$stub\git.cmd")) "answering n installs nothing"
Check (Test-Path "$T\bin\heronry.exe") "heronry itself is installed (uv tool, embed extra)"

"== 2. install.ps1 again, answer y: git installed through the package manager, embedding model downloaded"
$o = "y" | & $ps @args0 2>&1 | Out-String; Show $o
Check ($o -match "installing git: .*winget(\.cmd)? install --id Git.Git --exact") "git goes through winget"
Check ($o -match "installed git: git version 2.47.1") "git is found after the install"
Check ($o -match "downloading the embedding model BAAI/bge-small-en-v1.5") "the model download prints its progress line"
Check ($o -match "installed embedding model: BAAI") "the embedding model is ready"

"== 3. git missing again, install.ps1 -Yes: no question, installs"
Remove-Item "$stub\git.cmd" -ErrorAction SilentlyContinue
$o = & $ps @args0 -Yes 2>&1 | Out-String; Show $o
Check ($o -notmatch "\[Y/n\]" -and $o -match "installed git: git version 2.47.1") "-Yes installs without asking"
Check ($o -match "optional \(heronry prereqs install --only <name>\):") "optional tools are listed with what they turn on"

"== 4. the result, from the same manifest"
$h = "$T\bin\heronry.exe"
$j = & $h prereqs --json | Out-String | ConvertFrom-Json
$by = @{}; foreach ($r in $j.rows) { $by[$r.name] = $r }
Check ($by["git"].state -eq "ok" -and $by["git"].path -like "$stub*") "git: ok ($($by['git'].version)) from the stub install"
Check ($by["embedder"].state -eq "ok" -and $by["embedder"].path -like "$T*") "embedder: fastembed $($by['embedder'].version) inside the installed Heronry"
Check ($by["embedding model"].state -eq "ok" -and $by["embedding model"].path -like "$T\profile*") "embedding model cached in the profile: $($by['embedding model'].path)"
Check (@($j.not_needed | Where-Object { $_.name -eq "docker" }).Count -eq 1) "docker is listed as not needed"
"== heronry doctor (prerequisites)"
Show ((& $h doctor 2>&1 | Out-String) -split "`nharnesses")[0]
$log = Get-Content "$stub\winget.log" -ErrorAction SilentlyContinue
"winget stub log:"; $log | ForEach-Object { "   $_" }
Check (@($log | Where-Object { $_ -match "install --id Git.Git --exact" }).Count -eq 2) "the stub winget ran exactly twice (answer y, then -Yes)"

$left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($T, [StringComparison]::OrdinalIgnoreCase) })
Check ($left.Count -eq 0) "no process left running from the temp install ($($left.Count) found)"
if (-not $Keep) { Set-Location $env:TEMP; Remove-Item -Recurse -Force $T -ErrorAction SilentlyContinue }
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
