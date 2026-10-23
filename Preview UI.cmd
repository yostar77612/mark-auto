@echo off
setlocal
set "TASK_ROOT=%~dp0"
set "TASK_PYTHON=%TASK_ROOT%..\.repo\.venv\Scripts\python.exe"
if not exist "%TASK_PYTHON%" set "TASK_PYTHON=python"
"%TASK_PYTHON%" "%TASK_ROOT%tools\ui_redesign_preview.py" %*
if errorlevel 1 pause
