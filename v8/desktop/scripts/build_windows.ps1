# S8 (s-6dcf78f803): build the Heronry Desktop MSI with Briefcase (design-e963c656f5 §4.9).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\desktop\scripts\build_windows.ps1 [-Wheels <dir>] [-NoPackage]
#
# <dir> (default v8\desktop\wheels) holds the four wheels of ONE release (edp8, edp_contracts, edp_pool, edp_broker;
# the SPA is prebuilt into edp8's). Steps:
#   1. a pure-python wheel of proxy_tools (pywebview's dependency ships only an sdist; Briefcase installs binaries only)
#   2. briefcase create (first run) or update -r, then build: the GUI stub "Heronry Desktop.exe"
#   3. the console CLI: Briefcase's Console stub (pinned by SHA-256) stamped with the app module (InternalName, the
#      field the stub reads) as heronry.exe beside the GUI stub. A GUI-subsystem exe has no console, so the CLI and
#      every service/helper the launcher starts use heronry.exe (launcher.bundle_exe)
#   4. bin\heronry.cmd (the only folder put on PATH: the install root holds python312.dll & co, which must not
#      shadow another program's DLL search)
#   5. heronry.wxs: a component that appends [INSTALLFOLDER]bin to the user PATH (removed at uninstall); idempotent.
#      The template's Scope="perUserOrMachine" (ALLUSERS=2 + MSIINSTALLPERUSER=1) already installs per-user by
#      default, into %LOCALAPPDATA%\Programs, with no admin prompt; Scope="perUser" would NOT (ProgramFiles64Folder
#      then stays per-machine: error 1303, measured)
#   6. scope pin (S2 s-725ef36c03): an update is a MajorUpgrade, which only finds the old product in the SAME scope
#      (FindRelatedProducts reads ALLUSERS). A launch condition refuses ALLUSERS=1, so no command line can put a
#      second, per-machine copy beside the per-user one; the MajorUpgrade element is asserted present
#   7. briefcase package windows --adhoc-sign (unsigned, R10) -> dist\Heronry Desktop-<ver>.msi
# -Fresh drops build\ first (a stale tree, e.g. 0.8.0's, is never reused); -NoCliPath leaves step 5 out (the S2
# spike's side-by-side identity must not share the PATH component's fixed GUID and HKCU key with an installed app).
# -BuildEnv reuses an existing venv holding briefcase 0.4.5 + pip (S2: uv.exe's sockets are refused on the fleet
# host, os error 10013, while pip's are not).
param([string]$Wheels = "", [switch]$NoPackage, [switch]$Fresh, [switch]$NoCliPath, [string]$BuildEnv = "")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $PSScriptRoot
Set-Location $here
if (-not $Wheels) { $Wheels = Join-Path $here "wheels" }
$Wheels = (Resolve-Path $Wheels).Path
if (-not $BuildEnv) { $BuildEnv = Join-Path $here ".buildenv" }
$bc = Join-Path $BuildEnv "Scripts\briefcase.exe"
$bpy = Join-Path $BuildEnv "Scripts\python.exe"
if (-not (Test-Path $bc)) {
  uv venv $BuildEnv --python 3.12 -q
  uv pip install --python $bpy "briefcase==0.4.5" pip -q
}
function Run($what, [scriptblock]$b) { "== $what"; & $b; if ($LASTEXITCODE) { throw "$what failed (exit $LASTEXITCODE)" } }

# 1. proxy_tools
if (-not (Get-ChildItem $Wheels -Filter "proxy_tools-*.whl" -ErrorAction SilentlyContinue)) {
  Run "proxy_tools wheel" { & $bpy -m pip wheel --no-deps -q -w $Wheels "proxy_tools==0.1.0" }
}
# the bundle installs from ./wheels (pyproject requirement_installer_args)
$local = Join-Path $here "wheels"
if ($Wheels -ne $local) {
  New-Item -ItemType Directory -Force $local | Out-Null
  Copy-Item (Join-Path $Wheels "*.whl") $local -Force
}

# 2. the app
if ($Fresh -and (Test-Path (Join-Path $here "build"))) { Remove-Item -Recurse -Force (Join-Path $here "build") }
$app = Join-Path $here "build\heronry\windows\app"
if (Test-Path (Join-Path $app "briefcase.toml")) {
  Run "briefcase update" { & $bc update windows -r --no-input }
} else {
  Run "briefcase create" { & $bc create windows --no-input }
}
Run "briefcase build" { & $bc build windows --no-input }
$src = Join-Path $app "src"

# 3. console stub
$toml = Get-Content (Join-Path $app "briefcase.toml") -Raw
$pyTag = [regex]::Match($toml, "Generated using Python (\d+\.\d+)").Groups[1].Value
$rev = [regex]::Match($toml, 'stub_binary_revision = "(\d+)"').Groups[1].Value
$pins = @{ "3.12-13" = "bd6d50b5624cad0b2c3b6ea57d15b0262e24bdbbc7153f1576ce2cc6143c3c0f" }
$key = "$pyTag-$rev"
if (-not $pins.ContainsKey($key)) { throw "no pinned Console stub for Python ${pyTag} revision ${rev}: add its SHA-256 to `$pins" }
$stubs = Join-Path $here ".stubs"; New-Item -ItemType Directory -Force $stubs | Out-Null
$zip = Join-Path $stubs "Console-Stub-$pyTag-amd64-b$rev.zip"
if (-not (Test-Path $zip)) {
  Invoke-WebRequest "https://briefcase-support.s3.amazonaws.com/python/$pyTag/windows/Console-Stub-$pyTag-amd64-b$rev.zip" -OutFile $zip -UseBasicParsing
}
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($sha -ne $pins[$key]) { Remove-Item $zip; throw "Console stub SHA-256 mismatch: $sha" }
Expand-Archive $zip -DestinationPath (Join-Path $stubs "console-$key") -Force
Copy-Item (Join-Path $stubs "console-$key\Stub.exe") (Join-Path $src "heronry.exe") -Force
$rcedit = Join-Path $env:LOCALAPPDATA "BeeWare\briefcase\Cache\tools\rcedit-x64.exe"
$ver = [regex]::Match((Get-Content (Join-Path $here "pyproject.toml") -Raw), '(?m)^version = "([^"]+)"').Groups[1].Value
Run "stamp heronry.exe" { & $rcedit (Join-Path $src "heronry.exe") --set-version-string InternalName heronry `
    --set-version-string OriginalFilename heronry.exe --set-version-string FileDescription "Heronry CLI" `
    --set-version-string ProductName "Heronry Desktop" --set-version-string CompanyName "Heronry contributors" `
    --set-version-string FileVersion $ver --set-version-string ProductVersion $ver --set-icon (Join-Path $app "icon.ico") }

# 4. bin\heronry.cmd
$bin = Join-Path $src "bin"; New-Item -ItemType Directory -Force $bin | Out-Null
# the checked-in shim (scripts\heronry.cmd, tested by test_heronry_cmd_shim.py), written with CRLF line ends for cmd
$shim = (Get-Content (Join-Path $PSScriptRoot "heronry.cmd")) -join "`r`n"
Set-Content -Path (Join-Path $bin "heronry.cmd") -Encoding ascii -NoNewline -Value ($shim + "`r`n")

# 5 + 6. heronry.wxs: the CLI on PATH, the scope pin and the MajorUpgrade assert (patch_wxs.ps1, tested on a template)
Run "patch heronry.wxs" { & (Join-Path $PSScriptRoot "patch_wxs.ps1") -Wxs (Join-Path $app "heronry.wxs") -NoCliPath:$NoCliPath }

# 7. package
if (-not $NoPackage) {
  Run "briefcase package" { & $bc package windows --adhoc-sign --no-input }
  Get-ChildItem (Join-Path $here "dist") -Filter "*.msi" | ForEach-Object { "MSI $($_.FullName) $([math]::Round($_.Length/1MB,1)) MB sha256 $((Get-FileHash $_.FullName).Hash.ToLower())" }
}
"app dir: $src"
