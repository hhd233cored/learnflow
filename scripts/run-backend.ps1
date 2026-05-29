#requires -Version 5.1
param(
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $RootDir "backend"
$BackendPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $BackendPython)) {
    throw "Backend virtual environment not found: $BackendPython. Run .\install-local.bat first."
}

Set-Location -LiteralPath $BackendDir

# 用 python -m uvicorn 可以确保调用的是当前虚拟环境里的 uvicorn。
Write-Host "Starting StudyAgent backend on http://127.0.0.1:$BackendPort" -ForegroundColor Cyan
& $BackendPython -m uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort
