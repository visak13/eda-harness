# Install the pinned code-server build for the `code` service (s-3c8c2512d6, strategyhl-e69dbbae06).
#
#   scripts\install-code-server.ps1                  install what vscode-ext\code-server.lock.json pins
#   scripts\install-code-server.ps1 -Archive <tgz>   use a local copy of the release tarball (still hash-checked)
#
# Reads the committed lock and never looks up "latest". The sha256 is checked BEFORE extraction; a
# mismatch exits 2 and leaves no install dir behind. The tarball is extracted into <ver>.tmp and
# renamed to <ver>, so <ver> either exists complete (with a .verified marker holding the hash) or not
# at all. Idempotent: a verified <ver> is a no-op. Never touches PATH or any global state; other
# <ver> dirs (the N-1 rollback) are left alone.
param(
  [string]$Lock = "",
  [string]$Archive = "",
  [string]$ToolsDir = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest's progress bar makes a 200 MB download crawl
$v8 = Split-Path -Parent $PSScriptRoot
if (-not $Lock) { $Lock = Join-Path $v8 "vscode-ext\code-server.lock.json" }
if (-not $ToolsDir) { $ToolsDir = Join-Path $v8 ".tools\code-server" }

function Fail($code, $msg) { [Console]::Error.WriteLine("install-code-server: $msg"); exit $code }

$l = Get-Content $Lock -Raw | ConvertFrom-Json
$sha = ("" + $l.sha256).ToLower()
if ($sha -notmatch '^[0-9a-f]{64}$') { Fail 2 "lock $Lock has no valid sha256" }
if (("" + $l.version) -notmatch '^\d+\.\d+\.\d+$') { Fail 2 "lock $Lock has no valid version" }
$dest = Join-Path $ToolsDir $l.version
$marker = Join-Path $dest ".verified"
$node = Join-Path (Join-Path $dest $l.server_dir) $l.node

if ((Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $sha) -and (Test-Path $node)) {
  Write-Host "code-server $($l.version) already installed and verified at $dest (no-op)"
  exit 0
}

# -- the archive: -Archive, else the download cache, else download ------------------------------
$downloaded = $false
if (-not $Archive) {
  $cache = Join-Path $ToolsDir "_download"
  New-Item -ItemType Directory -Force $cache | Out-Null
  $Archive = Join-Path $cache $l.asset
  if (-not (Test-Path $Archive)) {
    Write-Host "downloading $($l.url)"
    $part = "$Archive.part"
    Invoke-WebRequest -Uri $l.url -OutFile $part -UseBasicParsing
    Move-Item -Force $part $Archive
    $downloaded = $true
  }
}
if (-not (Test-Path $Archive)) { Fail 2 "archive $Archive not found" }

$got = (Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLower()
if ($got -ne $sha) {
  if ($downloaded) { Remove-Item -Force $Archive }
  Fail 2 "sha256 mismatch for $Archive`n  lock: $sha`n  file: $got`nnothing was extracted"
}
Write-Host "sha256 verified: $got"

# -- refuse to replace an install that is running -----------------------------------------------
if (Test-Path $dest) {
  $root = ([IO.Path]::GetFullPath($dest)).TrimEnd("\") + "\"
  $users = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) })
  if ($users.Count -gt 0) { Fail 3 "$dest is unverified but in use by pid $(($users | ForEach-Object { $_.ProcessId }) -join ','); stop the code service first" }
}

# -- extract into <ver>.tmp, then rename -----------------------------------------------------------
$tmp = "$dest.tmp"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Force $tmp | Out-Null
# the Windows bsdtar by full path: a Git-for-Windows GNU tar earlier on PATH reads "C:" as a remote host
& (Join-Path $env:SystemRoot "System32\tar.exe") -xzf $Archive -C $tmp
if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force $tmp; Fail 4 "tar failed ($LASTEXITCODE) extracting $Archive" }
if (-not (Test-Path (Join-Path (Join-Path $tmp $l.server_dir) $l.node))) {
  Remove-Item -Recurse -Force $tmp; Fail 4 "the archive has no $($l.server_dir)\$($l.node)"
}
Set-Content -Path (Join-Path $tmp ".verified") -Value $sha -Encoding ascii
if (Test-Path $dest) {
  # same version present but not verified (e.g. a hand-extracted spike copy): replace it
  Write-Host "replacing unverified $dest"
  Remove-Item -Recurse -Force $dest
}
Move-Item $tmp $dest
Write-Host "code-server $($l.version) installed at $dest"
exit 0
