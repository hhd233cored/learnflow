#requires -Version 5.1
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendDir = Join-Path $RootDir "frontend"

$NpmCommand = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
if ($null -eq $NpmCommand) {
    $NpmCommand = Get-Command "npm" -ErrorAction SilentlyContinue
}

if ($null -eq $NpmCommand) {
    throw "npm not found. Run .\install-local.bat first, or make sure Node.js is available in PATH."
}

Set-Location -LiteralPath $FrontendDir

# 直接在启动窗口注入前端环境变量，即使 frontend\.env.local 写入失败也能正常连接后端。
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:$BackendPort/api/v1"
$env:NEXT_PUBLIC_USE_ASYNC_JOBS = "false"

Write-Host "Starting LearnFlow frontend on http://127.0.0.1:$FrontendPort" -ForegroundColor Cyan
& $NpmCommand.Source run dev -- --hostname 127.0.0.1 --port $FrontendPort
