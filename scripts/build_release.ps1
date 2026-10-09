# The only release build (s-4d93970c9f item 6; docs/release.md).
#
#   powershell -NoProfile -File scripts\build_release.ps1 -Version 0.10.3 -Ref <commit> -Out C:\heronry-rc\0.10.3
#
# Builds the MSI, the four wheels and SHA256SUMS from a CLEAN worktree of <commit> (a fresh `git worktree add`, so no
# untracked or modified file reaches the build), refuses unless every package and the board report <Version>, and
# prints the sha256 of every release file. Build only: nothing is installed or started, no service is touched.
#
#   -Version   X.Y.Z, the version every package, the board and the MSI must carry
#   -Ref       the commit (or branch/tag) to build; its resolved sha is printed and logged
#   -Out       an empty or new folder: <Out>\release holds the MSI, the wheels and SHA256SUMS; <Out>\build-release.log
#              the log; <Out>\work the throwaway worktree (removed at the end unless -KeepWorktree)
#   -BuildEnv  an existing venv holding briefcase 0.4.5 + pip (passed to v8\desktop\scripts\build_windows.ps1)
#   -CheckOnly stop after the version check on the clean worktree (no web build, no wheels, no MSI)
param(
  [Parameter(Mandatory = $true)][string]$Version,
  [Parameter(Mandatory = $true)][string]$Ref,
  [Parameter(Mandatory = $true)][string]$Out,
  [string]$BuildEnv = "",
  [switch]$CheckOnly,
  [switch]$KeepWorktree
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Packages = @(
  @{ Name = "edp-contracts"; Dir = "edp-contracts"; Init = "edp-contracts\src\edp_contracts\__init__.py"; Wheel = "edp_contracts" },
  @{ Name = "edp-pool";      Dir = "edp-pool";      Init = "edp-pool\src\edp_pool\__init__.py";           Wheel = "edp_pool" },
  @{ Name = "edp-broker";    Dir = "edp-broker";    Init = "edp-broker\src\edp_broker\__init__.py";       Wheel = "edp_broker" },
  @{ Name = "edp8 (board)";  Dir = "v8";            Init = "v8\src\edp8\__init__.py";                     Wheel = "edp8" }
)

function Say($s) { Write-Host "== $(Get-Date -Format HH:mm:ss) $s" }
function Fail($s) { throw "build_release: $s" }
function Run($what, [scriptblock]$b) { Say $what; & $b; if ($LASTEXITCODE) { Fail "$what failed (exit $LASTEXITCODE)" } }

if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "-Version must be X.Y.Z, got '$Version'" }
$ErrorActionPreference = "Continue"  # 5.1 turns a native command's stderr into a terminating error under Stop
$sha = (& git -C $Root rev-parse --verify "$Ref^{commit}" 2>$null)
$gitRc = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($gitRc -ne 0 -or -not $sha) { Fail "-Ref '$Ref' is not a commit of $Root" }
if ((Test-Path $Out) -and (Get-ChildItem $Out -Force | Select-Object -First 1)) { Fail "-Out '$Out' is not empty" }
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path
$work = Join-Path $Out "work"
$release = Join-Path $Out "release"
Start-Transcript -Path (Join-Path $Out "build-release.log") | Out-Null

# a release is built from what is committed, in the build's own environment: none of the live board's variables
foreach ($v in "EDP8_BOARD_URL", "EDP8_TOKEN", "EDP8_MCP_URL", "EDP8_RUN_DIR", "EDP_HOME") { Remove-Item "Env:$v" -ErrorAction SilentlyContinue }

function Version-Of($file, $pattern) {
  $m = [regex]::Match([IO.File]::ReadAllText($file), $pattern, "Multiline")
  if ($m.Success) { $m.Groups[1].Value } else { "<none>" }
}

function Check-Source($tree) {
  $bad = @()
  foreach ($p in $Packages) {
    $have = Version-Of (Join-Path $tree $p.Init) '^__version__\s*=\s*"([^"]+)"'
    if ($have -ne $Version) { $bad += "$($p.Name) __version__ is $have" }
    $toml = Version-Of (Join-Path $tree "$($p.Dir)\pyproject.toml") '^version\s*=\s*"([^"]+)"'
    if ($toml -ne $Version) { $bad += "$($p.Dir)\pyproject.toml version is $toml" }
  }
  $desk = Version-Of (Join-Path $tree "v8\desktop\pyproject.toml") '^version\s*=\s*"([^"]+)"'
  if ($desk -ne $Version) { $bad += "v8\desktop\pyproject.toml version is $desk" }
  if ($bad) { Fail "the commit $sha does not carry $Version everywhere:`n  - $($bad -join "`n  - ")" }
  Say "source carries $Version in every package, the board and the desktop app"
}

function Wheel-Version($wheel, $initPath) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [IO.Compression.ZipFile]::OpenRead($wheel)
  try {
    $e = $zip.Entries | Where-Object { $_.FullName -eq $initPath } | Select-Object -First 1
    if (-not $e) { return "<no $initPath>" }
    $r = New-Object IO.StreamReader($e.Open())
    try { $text = $r.ReadToEnd() } finally { $r.Dispose() }
    $m = [regex]::Match($text, '^__version__\s*=\s*"([^"]+)"', "Multiline")
    if ($m.Success) { $m.Groups[1].Value } else { "<none>" }
  } finally { $zip.Dispose() }
}

function Msi-Property($msi, $name) {
  $i = New-Object -ComObject WindowsInstaller.Installer
  $db = $i.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $i, @($msi, 0))
  $view = $db.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $db, @("SELECT Value FROM Property WHERE Property='$name'"))
  $view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null) | Out-Null
  $rec = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
  $v = if ($rec) { $rec.GetType().InvokeMember("StringData", "GetProperty", $null, $rec, @(1)) } else { $null }
  $view.GetType().InvokeMember("Close", "InvokeMethod", $null, $view, $null) | Out-Null
  $v
}

$ok = $false
try {
  Say "building $Version from $sha ($Ref) into $Out"
  Run "clean worktree" { git -C $Root worktree add --detach $work $sha }
  Check-Source $work
  if ($CheckOnly) { Say "CHECK-OK (-CheckOnly: nothing was built)"; $ok = $true; return }

  $env:EDP8_WEB_BASE = "/ui/"
  Run "web: npm ci" { npm --prefix (Join-Path $work "v8\web") ci }
  Run "web: build" { npm --prefix (Join-Path $work "v8\web") run build }
  # the edp8 wheel carries EDP Chat (qa report-c09ee01164 #3b: 0.10.4 shipped without it), as release.yml does
  $ext = Join-Path $work "v8\vscode-ext\edp-code"
  Run "EDP Chat: npm ci" { npm --prefix $ext ci }
  Run "EDP Chat: package" { npm --prefix $ext run package }
  $wheels = Join-Path $Out "wheels"
  New-Item -ItemType Directory -Force $wheels | Out-Null
  $env:EDP8_WEB_AUTOBUILD = "0"  # the SPA is built above, once, into the worktree's own dist
  $env:EDP8_REQUIRE_VSIX = "1"   # a wheel without edp-code.vsix is an error, not a warning
  foreach ($p in $Packages) {
    Run "wheel $($p.Dir)" { Push-Location $work; try { uv build --offline --wheel --out-dir $wheels $p.Dir } finally { Pop-Location } }
  }
  Get-ChildItem $wheels -Filter ".gitignore" -Force -ErrorAction SilentlyContinue | Remove-Item -Force

  $msiArgs = @("-NoProfile", "-File", (Join-Path $work "v8\desktop\scripts\build_windows.ps1"), "-Wheels", $wheels, "-Fresh")
  if ($BuildEnv) { $msiArgs += @("-BuildEnv", $BuildEnv) }
  Run "MSI" { powershell @msiArgs }
  $msi = Join-Path $work "v8\desktop\dist\Heronry Desktop-$Version.msi"
  if (-not (Test-Path $msi)) { Fail "the MSI build produced no 'Heronry Desktop-$Version.msi' in v8\desktop\dist" }

  New-Item -ItemType Directory -Force $release | Out-Null
  Copy-Item $msi $release
  Get-ChildItem $wheels -Filter "*.whl" | Copy-Item -Destination $release
  # the by-hand installer beside the MSI (owner m-584d63e760), with the CRLF line ends cmd needs
  $inst = (Get-Content (Join-Path $work "scripts\install-heronry.cmd")) -join "`r`n"
  [IO.File]::WriteAllText((Join-Path $release "install-heronry.cmd"), $inst + "`r`n", [Text.Encoding]::ASCII)

  # every package and the board must report the version: the wheel name AND the __version__ inside the wheel
  $bad = @()
  foreach ($p in $Packages) {
    $w = Get-ChildItem $release -Filter "$($p.Wheel)-*.whl" | Select-Object -First 1
    if (-not $w) { $bad += "no $($p.Wheel) wheel in the release"; continue }
    if ($w.Name -notlike "$($p.Wheel)-$Version-*") { $bad += "$($w.Name) is not version $Version" }
    $inner = Wheel-Version $w.FullName (($p.Init -replace '^[^\\]+\\src\\', '') -replace '\\', '/')
    if ($inner -ne $Version) { $bad += "$($w.Name) reports __version__ $inner" }
  }
  $pv = Msi-Property (Get-ChildItem $release -Filter "*.msi" | Select-Object -First 1).FullName "ProductVersion"
  if ($pv -ne $Version) { $bad += "the MSI ProductVersion is $pv" }
  if ($bad) { Fail "the build does not report $Version everywhere:`n  - $($bad -join "`n  - ")" }
  Say "every package, the board and the MSI report $Version"

  Say "SHA256SUMS"
  $lines = foreach ($f in (Get-ChildItem $release -File | Where-Object Name -ne "SHA256SUMS" | Sort-Object Name)) {
    "$((Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower())  $($f.Name)"
  }
  [IO.File]::WriteAllText((Join-Path $release "SHA256SUMS"), (($lines -join "`n") + "`n"))
  $lines
  Say "BUILD-OK $Version $sha -> $release"
  $ok = $true
} finally {
  if (-not $KeepWorktree -and (Test-Path $work)) { git -C $Root worktree remove --force $work 2>$null | Out-Null }
  Stop-Transcript | Out-Null
  if (-not $ok) { Write-Host "!! build_release FAILED; see $(Join-Path $Out 'build-release.log')" }
}
if (-not $ok) { exit 1 }
