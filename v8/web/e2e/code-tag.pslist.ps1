# code-tag.spec.ts helper: every powershell.exe as "pid<TAB>parent pid<TAB>parent image<TAB>command line".
$all = @{}
Get-CimInstance Win32_Process | ForEach-Object { $all[[int]$_.ProcessId] = $_ }
$all.Values | Where-Object { $_.Name -eq 'powershell.exe' } | ForEach-Object {
  $p = $all[[int]$_.ParentProcessId]
  $pn = if ($p) { $p.Name } else { '' }
  "$($_.ProcessId)`t$($_.ParentProcessId)`t$pn`t$($_.CommandLine)"
}
