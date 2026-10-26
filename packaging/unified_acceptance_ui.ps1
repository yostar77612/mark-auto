# Unified lifecycle fixture extension; no functions execute on import.
function Assert-EmptyLocalAcceptanceClose([string]$Stage, [string]$Environment, [string]$Account, [string]$Text) {
  # Exact semantic scope, whitespace-only normalization; never accept real assets.
  $local=[regex]::Unescape('\u672c\u6a5f\u6a21\u64ec')
  if ($Environment -cne $local -or $Account -cne 'local-stock') { throw 'Close fixture requires its empty LOCAL account' }
  $expected=switch -CaseSensitive ($Stage) {
    'shutdown' { [regex]::Unescape('\u76ee\u524d\u6301\u5009 0 \u7b46\uff0c\u59d4\u8a17 0 \u7b46\u3002\n\u95dc\u9589\u5f15\u64ce\u6703\u4e2d\u6b62\u672c\u6a5f\u884c\u60c5\u76e3\u63a7\u8207\u672c\u6a5f\u4fdd\u8b77\uff1b\u4e0d\u4ee3\u8868\u5df2\u5e73\u5009\u3002\n\u61c9\u7528\u670d\u52d9\u5c07\u5148\u6aa2\u67e5\u672a\u5b8c\u6210\u8cac\u4efb\uff0c\u7121\u6cd5\u5b89\u5168\u95dc\u9589\u6642\u6703\u62d2\u7d55\u3002') }
    'interface' { [regex]::Unescape('\u5f15\u64ce\u76ee\u524d\u70ba \u5df2\u95dc\u9589\uff0c\u4ecd\u8a18\u9304\u6301\u5009 0 \u7b46\u3002\n\u95dc\u9589\u4ecb\u9762\u4e0d\u6703\u5e73\u5009\uff1b\u672c\u6a5f\u76e3\u63a7\u53ca\u4fdd\u8b77\u5df2\u96a8\u5f15\u64ce\u505c\u6b62\u3002\u8acb\u4fdd\u7559\u672a\u5b8c\u6210\u4e8b\u9805\u4e26\u5728\u6062\u5fa9\u5f8c\u5c0d\u5e33\u3002') }
    default { throw 'Unknown close fixture stage' }
  }
  if ([regex]::Replace($Text,'\s+',' ').Trim() -cne [regex]::Replace($expected,'\s+',' ').Trim()) {
    throw 'Close fixture scope is not proven empty or already stopped'
  }
}
function Close-OwnedUnifiedAcceptanceWindow($Owned, [Diagnostics.Stopwatch]$Clock) {
  # Fixture-only UI actions, rooted at the creation-proven application HWND.
  # No desktop root, injected keys, PID adoption, modal bypass or force-stop.
  Confirm-AcceptanceWorker $AcceptanceJob
  Assert-OwnedAcceptanceProcess $Owned
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  $Owned.Process.Refresh()
  $ownedPid=$Owned.Process.get_Id()
  $hwnd=$Owned.Process.get_MainWindowHandle()
  if ($hwnd -eq [IntPtr]::Zero) { throw 'Owned platform window missing during close' }
  $pidProperty=[Windows.Automation.AutomationElement]::ProcessIdProperty
  $typeProperty=[Windows.Automation.AutomationElement]::ControlTypeProperty
  $idProperty=[Windows.Automation.AutomationElement]::AutomationIdProperty
  $nameProperty=[Windows.Automation.AutomationElement]::NameProperty
  $enabledProperty=[Windows.Automation.AutomationElement]::IsEnabledProperty
  function Confirm-CloseIdentity {
    if ($Clock.ElapsedMilliseconds -ge 15000) { throw 'Window did not close cleanly' }
    Assert-OwnedAcceptanceProcess $Owned
    if ($Owned.Process.get_HasExited()) { throw 'Platform exited before close scope was confirmed' }
  }
  function Get-OwnedCloseElements($Parent) {
    Confirm-CloseIdentity
    if ($Parent.GetCurrentPropertyValue($pidProperty) -ne $ownedPid) { throw 'Close UI ownership changed' }
    # One provider snapshot avoids a separate cross-process call for every
    # property of every descendant. Ownership and the original cap still apply
    # to the entire snapshot; mutation also rechecks the selected live element.
    $cache=New-Object Windows.Automation.CacheRequest
    foreach ($property in @($pidProperty,$typeProperty,$idProperty,$nameProperty,$enabledProperty)) { $cache.Add($property) }
    $activation=$cache.Activate()
    try { $elements=$Parent.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition) }
    finally { $activation.Dispose() }
    Confirm-CloseIdentity
    if ($elements.Count -gt 512) { throw 'Close UI inventory exceeds bounded scope' }
    foreach ($element in $elements) {
      Confirm-CloseIdentity
      if ($element.GetCachedPropertyValue($pidProperty) -ne $ownedPid) { throw 'Close descendant ownership changed' }
      $element
    }
  }
  function Find-OwnedCloseElement([string]$Suffix, $Control, [string]$Name, [switch]$Enabled) {
    while ($Clock.ElapsedMilliseconds -lt 15000) {
      Confirm-CloseIdentity
      $ui=[Windows.Automation.AutomationElement]::FromHandle($hwnd)
      if (-not $ui.get_Current().get_AutomationId().EndsWith('multi_market_window',[StringComparison]::Ordinal)) {
        throw 'Unified platform identity not proven'
      }
      $closeControls=@(Get-OwnedCloseElements $ui | Where-Object {
        $_.GetCachedPropertyValue($typeProperty) -eq $Control -and
        (-not $Suffix -or $_.GetCachedPropertyValue($idProperty).EndsWith($Suffix,[StringComparison]::Ordinal)) -and
        (-not $Name -or $_.GetCachedPropertyValue($nameProperty) -ceq $Name)
      })
      if ($closeControls.Count -gt 1) { throw 'Ambiguous close fixture control' }
      if ($closeControls.Count -eq 1 -and (-not $Enabled -or $closeControls[0].GetCachedPropertyValue($enabledProperty))) { return $closeControls[0] }
      Start-Sleep -Milliseconds 50
    }
    throw 'Window did not close cleanly'
  }
  function Invoke-OwnedCloseElement($Element) {
    Confirm-CloseIdentity
    if ($Element.GetCurrentPropertyValue($pidProperty) -ne $ownedPid -or -not $Element.get_Current().get_IsEnabled()) {
      throw 'Close control ownership or eligibility changed'
    }
    $Element.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
  }
  function Confirm-EmptyCloseDialog([string]$Stage) {
    $dialogHandle=[IntPtr]::Zero
    while ($dialogHandle -eq [IntPtr]::Zero) {
      Confirm-CloseIdentity
      $dialogHandle=[MarkAutoAcceptanceJob]::OwnedDialog($AcceptanceJob,$Owned.Handle,$hwnd,[regex]::Unescape('\u6838\u5c0d\u64cd\u4f5c\u7bc4\u570d'))
      if ($dialogHandle -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 50 }
    }
    $dialog=[Windows.Automation.AutomationElement]::FromHandle($dialogHandle)
    $items=@(Get-OwnedCloseElements $dialog)
    $text=@($items | Where-Object { $_.GetCachedPropertyValue($typeProperty) -eq [Windows.Automation.ControlType]::Text -and $_.GetCachedPropertyValue($nameProperty) })
    $confirm=@($items | Where-Object { $_.GetCachedPropertyValue($typeProperty) -eq [Windows.Automation.ControlType]::Button -and $_.GetCachedPropertyValue($nameProperty) -ceq [regex]::Unescape('\u78ba\u8a8d\u6b64\u7bc4\u570d') })
    if ($text.Count -ne 1 -or $confirm.Count -ne 1) { throw 'Close dialog scope is incomplete or ambiguous' }
    $environment=Find-OwnedCloseElement '.environment' ([Windows.Automation.ControlType]::ComboBox) ''
    $account=Find-OwnedCloseElement '.account_context' ([Windows.Automation.ControlType]::ComboBox) ''
    $environmentValue=$environment.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).get_Current().get_Value()
    $accountValue=$account.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).get_Current().get_Value()
    Assert-EmptyLocalAcceptanceClose $Stage $environmentValue $accountValue $text[0].GetCachedPropertyValue($nameProperty)
    if ([MarkAutoAcceptanceJob]::OwnedDialog($AcceptanceJob,$Owned.Handle,$hwnd,[regex]::Unescape('\u6838\u5c0d\u64cd\u4f5c\u7bc4\u570d')) -ne $dialogHandle) {
      throw 'Close dialog identity changed before confirmation'
    }
    Invoke-OwnedCloseElement $confirm[0]
    # Qt accessibility presses are asynchronous (animateClick). Do not invoke
    # a background control while the prior confirmation is still visible.
    while ($true) {
      if ($Clock.ElapsedMilliseconds -ge 15000) { throw 'Window did not close cleanly' }
      Assert-OwnedAcceptanceProcess $Owned
      $Owned.Process.Refresh()
      if ($Owned.Process.get_HasExited()) {
        if ($Stage -cne 'interface') { throw 'Platform exited before interface close was confirmed' }
        return
      }
      $currentDialog=[MarkAutoAcceptanceJob]::OwnedDialog($AcceptanceJob,$Owned.Handle,$hwnd,[regex]::Unescape('\u6838\u5c0d\u64cd\u4f5c\u7bc4\u570d'))
      if ($currentDialog -eq [IntPtr]::Zero) { return }
      if ($currentDialog -ne $dialogHandle) { throw 'Unexpected replacement close dialog' }
      Start-Sleep -Milliseconds 25
    }
  }
  $settings=Find-OwnedCloseElement '.trading_navigation' ([Windows.Automation.ControlType]::ListItem) ([regex]::Unescape('\u8a2d\u5b9a')) -Enabled
  Confirm-CloseIdentity
  if ($settings.GetCurrentPropertyValue($pidProperty) -ne $ownedPid -or -not $settings.get_Current().get_IsEnabled()) { throw 'Close navigation ownership or eligibility changed' }
  $settings.GetCurrentPattern([Windows.Automation.SelectionItemPattern]::Pattern).Select()
  $shutdown=Find-OwnedCloseElement '.shutdown_button' ([Windows.Automation.ControlType]::Button) '' -Enabled
  Invoke-OwnedCloseElement $shutdown
  Confirm-EmptyCloseDialog 'shutdown'
  $close=Find-OwnedCloseElement '.close_ui_button' ([Windows.Automation.ControlType]::Button) '' -Enabled
  Invoke-OwnedCloseElement $close
  Confirm-EmptyCloseDialog 'interface'
  return @{status='confirmed'; stages=@('empty-local-engine-shutdown','stopped-engine-interface-close');
    positions=0;orders=0;account='local-stock';total_close_budget_milliseconds=15000;force_stop=$false}
}
