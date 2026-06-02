@echo off
setlocal

set "ROOT=%~dp0"
set "START_SCRIPT=%ROOT%scripts\start-local.ps1"

if not exist "%START_SCRIPT%" (
  echo Cannot find start script:
  echo %START_SCRIPT%
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%" %*

endlocal
