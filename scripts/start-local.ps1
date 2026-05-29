#requires -Version 5.1
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$BackendPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$FrontendNodeModules = Join-Path $FrontendDir "node_modules"
$BackendRunner = Join-Path $PSScriptRoot "run-backend.ps1"
$FrontendRunner = Join-Path $PSScriptRoot "run-frontend.ps1"

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-PortInUse {
    param([int]$Port)

    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return $null -ne $connections
    }
    catch {
        # 某些精简环境可能没有 Get-NetTCPConnection；端口检查失败不影响启动。
        return $false
    }
}

function Start-DevWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$ScriptPath,
        [string]$ExtraArgs
    )

    # 使用 EncodedCommand 避免 Windows PowerShell 5.1 在路径、引号、空格上误解析启动命令。
    $command = "& '$ScriptPath' $ExtraArgs"
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $processArgs = "-NoExit -ExecutionPolicy Bypass -EncodedCommand $encodedCommand"

    if ([string]::IsNullOrWhiteSpace($processArgs)) {
        throw "PowerShell startup arguments are empty for $Title."
    }

    Start-Process `
        -FilePath "powershell.exe" `
        -WorkingDirectory $WorkingDirectory `
        -ArgumentList $processArgs `
        -WindowStyle Normal
}

if (-not (Test-Path -LiteralPath $BackendPython)) {
    throw "Backend virtual environment not found: $BackendPython. Run .\install-local.bat first."
}

if (-not (Test-Path -LiteralPath $FrontendNodeModules)) {
    throw "Frontend node_modules not found: $FrontendNodeModules. Run .\install-local.bat first."
}

if (Test-PortInUse -Port $BackendPort) {
    Write-Warning "Port $BackendPort is already in use. The backend window may fail to start. Use -BackendPort to choose another port."
}

if (Test-PortInUse -Port $FrontendPort) {
    Write-Warning "Port $FrontendPort is already in use. The frontend window may fail to start. Use -FrontendPort to choose another port."
}

Write-Step "Start backend FastAPI"
Start-DevWindow `
    -Title "StudyAgent Backend" `
    -WorkingDirectory $BackendDir `
    -ScriptPath $BackendRunner `
    -ExtraArgs "-BackendPort $BackendPort"

Write-Step "Start frontend Next.js"
Start-DevWindow `
    -Title "StudyAgent Frontend" `
    -WorkingDirectory $FrontendDir `
    -ScriptPath $FrontendRunner `
    -ExtraArgs "-BackendPort $BackendPort -FrontendPort $FrontendPort"

Write-Step "Local dev servers have been launched"
Write-Host "Backend health: http://127.0.0.1:$BackendPort/api/v1/health"
Write-Host "Frontend page: http://127.0.0.1:$FrontendPort"
Write-Host "Tip: this script opens two PowerShell windows. Close the corresponding window to stop a service."

if (-not $NoBrowser) {
    Write-Host "Opening browser..."
    Start-Sleep -Seconds 3
    Start-Process "http://127.0.0.1:$FrontendPort"
}
