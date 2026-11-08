# Read-only smoke walk of the INSTALLED MarkAuto window: click each navigation page, screenshot it, and fail if an
# error dialog appears or the process dies. It never types, never presses action buttons, never changes settings.
# Usage: powershell -File tools/ui_smoke_installed.ps1 -OutDir C:\path\to\shots
param([Parameter(Mandatory = $true)][string]$OutDir)

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class SmokeWin { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r); public struct RECT { public int L, T, R, B; } }
"@
New-Item -ItemType Directory -Force $OutDir | Out-Null
$process = Get-Process MarkAuto -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle } | Select-Object -First 1
if (-not $process) { Write-Error 'MarkAuto is not running'; exit 2 }
$AE = [System.Windows.Automation.AutomationElement]
$root = $AE::FromHandle($process.MainWindowHandle)
$listItem = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem)
# Pages are selected by position (overview, strategy, market, trading, performance, settings): no locale-dependent text.
$pages = @('overview', 'strategy', 'market', 'trading', 'performance', 'settings')
$failures = @()
function Save-Shot($name) {
    [SmokeWin]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 600
    $r = New-Object SmokeWin+RECT
    [SmokeWin]::GetWindowRect($process.MainWindowHandle, [ref]$r) | Out-Null
    $bitmap = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
    [System.Drawing.Graphics]::FromImage($bitmap).CopyFromScreen($r.L, $r.T, 0, 0, $bitmap.Size)
    $bitmap.Save((Join-Path $OutDir "$name.png"))
}
for ($index = 0; $index -lt $pages.Count; $index++) {
    $page = $pages[$index]
    $item = @($root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $listItem))[$index]
    if (-not $item) { $failures += "navigation item missing: $page"; continue }
    ($item.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)).Select()
    Start-Sleep -Seconds 2
    if ($process.HasExited) { $failures += "process exited on page $page"; break }
    $dialogs = $root.FindAll([System.Windows.Automation.TreeScope]::Children, (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)))
    if ($dialogs.Count -gt 0) { $failures += "dialog opened on page $page : $($dialogs[0].Current.Name)" }
    Save-Shot $page
    "page ok: $page"
}
if ($failures.Count) { $failures | ForEach-Object { Write-Error $_ }; exit 1 }
'smoke walk passed'
