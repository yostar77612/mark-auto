@echo off
setlocal DisableDelayedExpansion
if not exist "%~dp0MarkAuto\MarkAuto.exe" (
  echo Cannot find MarkAuto\MarkAuto.exe beside this launcher.
  pause
  exit /b 1
)
start "" /D "%~dp0MarkAuto" "%~dp0MarkAuto\MarkAuto.exe" --platform-v2 --trading-root "%~dp0Data\platform-v2"
