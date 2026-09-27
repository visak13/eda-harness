# Heronry installer for Windows (S3 s-870e401942, design-e963c656f5 4.4 / 4.10).
#
#   irm https://github.com/visak13/eda-harness/releases/latest/download/install.ps1 | iex
#   .\install.ps1 [-Version v0.9.0] [-ReleaseUrl <folder or https base>] [-Force] [-NoModifyPath] [-Yes] [-NoEmbed]
#
# 1. uv: uses the uv on PATH when it is at least $UvVersion, else installs exactly $UvVersion into
#    ~\.local\bin after checking the archive against uv's published SHA-256.
# 2. the release: SHA256SUMS plus the four wheels (edp8, edp_contracts, edp_pool, edp_broker), each
#    verified against SHA256SUMS before anything is installed.
# 3. `uv tool install --force "edp8[embed] @ <edp8 wheel>" --with <the other three>` (never `uv tool upgrade`, a
#    no-op for wheel installs; -NoEmbed drops the embed extra); skipped when that version is already installed,
#    unless -Force. Safe to re-run.
# 4. puts uv's tool bin dir on your user PATH (uv tool update-shell; -NoModifyPath skips it) and prints
#    `heronry version`.
# 5. `heronry prereqs install`: checks git, node, a harness (claude/codex), the embedder and its model against
#    the one prerequisites manifest, asks once, and installs the missing required ones with winget (-Yes: no
#    question). Optional tools (pi, Tailscale) are listed with what each turns on.
# Nothing here needs admin rights; your data lives outside the install and survives a reinstall.
param(
  [string]$Version = "",
  [string]$ReleaseUrl = "",
  [string]$Repo = "visak13/eda-harness",
  [switch]$Force,
  [switch]$NoModifyPath,
  [switch]$Yes,
  [switch]$NoEmbed
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$UvVersion = "0.9.11"
$Wheels = @("edp8", "edp_contracts", "edp_pool", "edp_broker")
$Python = "3.12"

function Say($s) { Write-Host "heronry-install: $s" }
function Die($s) { [Console]::Error.WriteLine("heronry-install: $s"); exit 1 }
function VersionOf($text) { if ("$text" -match '(\d+)\.(\d+)\.(\d+)') { [version]"$($Matches[1]).$($Matches[2]).$($Matches[3])" } else { $null } }
function Sha256($path) {  # .NET, not Get-FileHash: 5.1 started from pwsh 7 inherits its PSModulePath and
  # cannot autoload Microsoft.PowerShell.Utility ("Get-FileHash is not recognized", CI 36326185339)
  $s = [IO.File]::OpenRead($path)
  try { $h = [Security.Cryptography.SHA256]::Create(); -join ($h.ComputeHash($s) | ForEach-Object { $_.ToString("x2") }) }
  finally { $s.Dispose() }
}
function Fetch($src, $dest) {
  if ($src -match '^https?://') { Invoke-WebRequest -Uri $src -OutFile $dest -UseBasicParsing }
  else { Copy-Item -LiteralPath ($src -replace '^file://', '') -Destination $dest }
}

$work = Join-Path ([IO.Path]::GetTempPath()) ("heronry-install-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $work | Out-Null
try {
  # -- 1. uv ------------------------------------------------------------------------------------------
  $env:NO_COLOR = "1"   # uv prints plain paths
  $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
  $mine = Join-Path $env:USERPROFILE ".local\bin\uv.exe"   # where an earlier run of this script put it
  if (-not $uv -and (Test-Path $mine)) { $uv = $mine }
  $have = $null; if ($uv) { $have = VersionOf (& $uv --version) }
  if (-not $uv -or -not $have -or $have -lt [version]$UvVersion) {
    $arch = if ([Environment]::Is64BitOperatingSystem) { "x86_64" } else { "i686" }
    if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { $arch = "aarch64" }
    $asset = "uv-$arch-pc-windows-msvc.zip"
    $base = "https://github.com/astral-sh/uv/releases/download/$UvVersion"
    Say "installing uv $UvVersion ($asset)"
    Fetch "$base/$asset" (Join-Path $work $asset)
    Fetch "$base/$asset.sha256" (Join-Path $work "$asset.sha256")
    $want = ((Get-Content (Join-Path $work "$asset.sha256") -Raw).Trim() -split '\s+')[0].ToLower()
    if ((Sha256 (Join-Path $work $asset)) -ne $want) { Die "uv archive SHA-256 mismatch; nothing installed" }
    $bin = Join-Path $env:USERPROFILE ".local\bin"
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    # .NET, not Expand-Archive: the same PSModulePath leak hides Microsoft.PowerShell.Archive
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $work $asset), (Join-Path $work "uv"))
    Get-ChildItem (Join-Path $work "uv") -Recurse -Include "uv.exe", "uvx.exe", "uvw.exe" | Copy-Item -Destination $bin -Force
    $env:PATH = "$bin;$env:PATH"
    $uv = Join-Path $bin "uv.exe"
  }
  $uvDir = Split-Path -Parent $uv   # `heronry prereqs` and `heronry update` look uv up on PATH
  if (-not (($env:PATH -split ";") -contains $uvDir)) { $env:PATH = "$uvDir;$env:PATH" }
  Say "uv: $(& $uv --version)"

  # -- 2. the release, verified -------------------------------------------------------------------------
  $files = @{}
  if ($ReleaseUrl) {
    $base = $ReleaseUrl.TrimEnd("/", "\")
    Fetch "$base/SHA256SUMS" (Join-Path $work "SHA256SUMS")
    foreach ($line in Get-Content (Join-Path $work "SHA256SUMS")) {
      $p = $line.Trim() -split '\s+'; if ($p.Count -eq 2) { $files[$p[1].TrimStart("*")] = "$base/$($p[1].TrimStart('*'))" }
    }
  } else {
    $api = if ($Version) { "https://api.github.com/repos/$Repo/releases/tags/$Version" } else { "https://api.github.com/repos/$Repo/releases/latest" }
    $rel = Invoke-RestMethod -Uri $api -Headers @{ Accept = "application/vnd.github+json" }
    foreach ($a in $rel.assets) { $files[$a.name] = $a.browser_download_url }
    if (-not $files.ContainsKey("SHA256SUMS")) { Die "release $($rel.tag_name) has no SHA256SUMS; refusing an unverifiable install" }
    Fetch $files["SHA256SUMS"] (Join-Path $work "SHA256SUMS")
  }
  $sums = @{}
  foreach ($line in Get-Content (Join-Path $work "SHA256SUMS")) {
    $p = $line.Trim() -split '\s+'; if ($p.Count -eq 2 -and $p[0].Length -eq 64) { $sums[$p[1].TrimStart("*")] = $p[0].ToLower() }
  }
  $local = @{}
  foreach ($w in $Wheels) {
    $name = @($files.Keys | Where-Object { $_ -like "$w-*.whl" } | Sort-Object | Select-Object -Last 1)
    if (-not $name) { Die "the release has no $w wheel" }
    $name = $name[0]
    if (-not $sums.ContainsKey($name)) { Die "$name is not listed in SHA256SUMS; refusing it" }
    $dest = Join-Path $work $name
    Fetch $files[$name] $dest
    if ((Sha256 $dest) -ne $sums[$name]) { Die "SHA-256 mismatch for $name; nothing installed" }
    $local[$w] = $dest
  }
  $target = (Split-Path -Leaf $local["edp8"]) -split "-" | Select-Object -Index 1
  Say "verified $($Wheels.Count) wheels of heronry $target against SHA256SUMS"

  # -- 3. install (idempotent) ------------------------------------------------------------------------
  $binDir = ((& $uv tool dir --bin --color never) -replace "\x1b\[[0-9;]*m", "").Trim()
  $env:PATH = "$binDir;$env:PATH"
  $installed = $null
  $exe = Join-Path $binDir "heronry.exe"
  if (Test-Path $exe) { $ErrorActionPreference = "Continue"; $installed = VersionOf (& $exe version 2>$null); $ErrorActionPreference = "Stop" }
  if ($installed -and $installed -eq (VersionOf $target) -and -not $Force) {
    Say "heronry $target is already installed; nothing to do (-Force reinstalls)"
  } else {
    $spec = $local["edp8"]
    if (-not $NoEmbed) { $spec = "edp8[embed] @ $(([Uri](Resolve-Path -LiteralPath $spec).Path).AbsoluteUri)" }
    $ia = @("tool", "install", "--force", "--python", $Python, $spec)
    foreach ($w in @($Wheels | Where-Object { $_ -ne "edp8" })) { $ia += @("--with", $local[$w]) }
    Say "uv $($ia -join ' ')"
    & $uv @ia
    if ($LASTEXITCODE -ne 0) { Die "uv tool install failed (exit $LASTEXITCODE). If heronry is running, stop it first: heronry stop" }
  }

  # -- 4. PATH and the proof ------------------------------------------------------------------------------
  if (-not $NoModifyPath) { $ErrorActionPreference = "Continue"; & $uv tool update-shell 2>$null | Out-Null; $ErrorActionPreference = "Stop" }
  & $exe version
  if ($LASTEXITCODE -ne 0) { Die "heronry version failed after the install" }

  # -- 5. prerequisites (the one manifest: edp_contracts.prereqs) ----------------------------------------
  $pa = @("prereqs", "install")
  if ($Yes) { $pa += "--yes" }
  if ($NoEmbed) { $pa += "--no-embed" }
  Say "heronry $($pa -join ' ')"
  $ErrorActionPreference = "Continue"; & $exe @pa; $pre = $LASTEXITCODE; $ErrorActionPreference = "Stop"
  if ($pre -ne 0) { Say "some prerequisites are still missing (above); Heronry is installed: run 'heronry prereqs install' again after fixing them" }
  Say "next: heronry init   (then heronry start; open a new terminal if 'heronry' is not found)"
} finally {
  Remove-Item -Recurse -Force -LiteralPath $work -ErrorAction SilentlyContinue
}
