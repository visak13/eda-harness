# S10 (s-b431082892): patch Briefcase's generated heronry.wxs for the release MSI, in place and idempotent. Split out of
# build_windows.ps1 (steps 5 and 6 there) so a test can run it on a template without a Briefcase build.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\desktop\scripts\patch_wxs.ps1 -Wxs <heronry.wxs> [-NoCliPath]
#
# 5. a component that appends [INSTALLFOLDER]bin to the user PATH (removed at uninstall); -NoCliPath leaves it out
# 6. the scope pin: an update is a MajorUpgrade, which only finds the old product in the SAME scope (FindRelatedProducts
#    reads ALLUSERS). A launch condition refuses ALLUSERS=1 (and an installed per-machine copy is never upgraded by it),
#    so no command line can put a second, per-machine copy beside the per-user one. Package Scope=perUserOrMachine and
#    the MajorUpgrade element are asserted present, else this throws and the build stops.
param([Parameter(Mandatory)][string]$Wxs, [switch]$NoCliPath)
$ErrorActionPreference = "Stop"
$wxsPath = (Resolve-Path $Wxs).Path
$wxs = Get-Content $wxsPath -Raw
if (-not $NoCliPath -and $wxs -notmatch 'Id="HeronryCliOnPath"') {
  $component = @'
        <!-- S8: the CLI on the user PATH (bin\heronry.cmd only), removed at uninstall -->
        <Component Id="HeronryCliOnPath" Guid="4f3b5a52-9f55-4a5e-a1d1-6c1d2f8e0b17" Directory="INSTALLFOLDER">
            <Environment Id="HeronryPathEntry" Name="PATH" Value="[INSTALLFOLDER]bin" Part="last" Action="set" System="no" Permanent="no" />
            <RegistryValue Root="HKCU" Key="Software\Heronry contributors\Heronry Desktop" Name="cli_on_path" Type="integer" Value="1" KeyPath="yes" />
        </Component>

        <StandardDirectory Id="ProgramMenuFolder">
'@
  $wxs = $wxs.Replace("        <StandardDirectory Id=`"ProgramMenuFolder`">", $component.TrimEnd())
  $wxs = $wxs.Replace("            <ComponentRef Id=`"ApplicationShortcuts`" />", "            <ComponentRef Id=`"ApplicationShortcuts`" />`r`n            <ComponentRef Id=`"HeronryCliOnPath`" />")
}
if (-not $NoCliPath -and $wxs -notmatch 'ComponentRef Id="HeronryCliOnPath"') { throw "heronry.wxs patch did not apply" }

# 6. scope pin + MajorUpgrade
if ($wxs -notmatch 'Scope="perUserOrMachine"') { throw "heronry.wxs: expected Package Scope=perUserOrMachine (Briefcase system_installer=false)" }
if ($wxs -notmatch '<MajorUpgrade') { throw "heronry.wxs: no MajorUpgrade element; an update would install side by side" }
if ($wxs -notmatch 'Id="HeronryScopePin"') {
  $pin = @'
        <!-- S2: per-user only. A MajorUpgrade finds the installed product only in the same scope, so ALLUSERS=1 is refused -->
        <Launch Condition="Installed OR NOT (ALLUSERS = 1)" Message="[ProductName] installs per user only; run it without ALLUSERS=1." />
        <Property Id="HeronryScopePin" Value="perUser" />

        <Icon Id="ProductIcon"
'@
  $wxs = $wxs.Replace("        <Icon Id=`"ProductIcon`"", $pin.TrimEnd())
}
if ($wxs -notmatch 'Id="HeronryScopePin"') { throw "heronry.wxs scope pin did not apply" }
[IO.File]::WriteAllText($wxsPath, $wxs, (New-Object Text.UTF8Encoding($false)))  # no BOM, no trailing newline growth

