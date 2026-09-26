# S8 evidence helper (Windows): open the Heronry tray icon's menu through UI Automation and list its items;
# with -Click "<item>" it picks that item (keyboard: the popup exposes no items to UIA). -Shot <png> captures only the menu's own rectangle.
#   powershell -NoProfile -File tray_menu.ps1 [-Click "Status"] [-Shot out.png]
param([string]$Click = "", [string]$Shot = "", [string]$Name = "Heronry Desktop")
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class M { [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, IntPtr e); }
"@
$A = [System.Windows.Automation.AutomationElement]; $S = [System.Windows.Automation.TreeScope]; $root = $A::RootElement
function ByName($scope, $el, $n) { $el.FindFirst($scope, (New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $n))) }
function RightClick($r) { $x = [int]($r.X + $r.Width / 2); $y = [int]($r.Y + $r.Height / 2); [M]::SetCursorPos($x, $y) | Out-Null
  [M]::mouse_event(0x0008, 0, 0, 0, [IntPtr]::Zero); [M]::mouse_event(0x0010, 0, 0, 0, [IntPtr]::Zero) }
$icon = $null
foreach ($try in 1..2) {
  $icons = $root.FindAll($S::Descendants, (New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $Name)))
  $icon = @($icons | Where-Object { $_.Current.AutomationId -eq "NotifyItemIcon" })[0]
  if ($icon) { break }
  $tray = $root.FindFirst($S::Children, (New-Object System.Windows.Automation.PropertyCondition($A::ClassNameProperty, "Shell_TrayWnd")))
  (ByName $S::Descendants $tray "Show Hidden Icons").GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  Start-Sleep -Milliseconds 1200
}
if (-not $icon) { "no tray icon named '$Name'"; exit 1 }
"tray icon: $($icon.Current.Name) at $($icon.Current.BoundingRectangle)"
RightClick $icon.Current.BoundingRectangle
Start-Sleep -Milliseconds 900
$menu = $root.FindFirst($S::Children, (New-Object System.Windows.Automation.PropertyCondition($A::ClassNameProperty, "#32768")))
if (-not $menu) { "no popup menu appeared"; exit 1 }
# the popup's items are not exposed to UIA: they are driven by keyboard in menu order
$order = @("Open board", "Status", "Start services", "Stop services", "Restart services", "Check for update",
           "Stop services on quit", "Quit")
if ($Shot) {
  $r = $menu.Current.BoundingRectangle
  $bmp = New-Object System.Drawing.Bitmap ([int]$r.Width), ([int]$r.Height)
  $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen([int]$r.X, [int]$r.Y, 0, 0, $bmp.Size); $bmp.Save($Shot); $g.Dispose(); $bmp.Dispose()
  "menu shot: $Shot"
}
Add-Type -AssemblyName System.Windows.Forms
if ($Click) {
  $k = [array]::IndexOf($order, $Click)
  if ($k -lt 0) { "no item '$Click'"; [System.Windows.Forms.SendKeys]::SendWait("{ESC}"); exit 1 }
  [System.Windows.Forms.SendKeys]::SendWait(("{DOWN}" * ($k + 1)) + "{ENTER}")
  "clicked: $Click"
} else {
  [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
}
