@echo off
setlocal EnableDelayedExpansion

set "ARGS="

:parse_args
if "%~1"=="" goto run_installer
set "ARG=%~1"

if /I "!ARG!"=="--install-system-deps" set "ARG=-InstallSystemDeps"
if /I "!ARG!"=="--force-env" set "ARG=-ForceEnv"
if /I "!ARG!"=="--skip-backend" set "ARG=-SkipBackend"
if /I "!ARG!"=="--skip-frontend" set "ARG=-SkipFrontend"

set "ARGS=!ARGS! "!ARG!""
shift
goto parse_args

:run_installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-local.ps1" %ARGS%
endlocal
