#requires -Version 5.1
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$NoBrowser,
    [switch]$SkipPortCleanup
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

    return (Get-ListeningPortPids -Port $Port).Count -gt 0
}

function Get-ListeningPortPids {
    param([int]$Port)

    $processIds = @()
    $pattern = ":$Port\s+.*LISTENING\s+(\d+)"
    try {
        $netstatOutput = & netstat.exe -ano
    }
    catch {
        return @()
    }

    foreach ($line in $netstatOutput) {
        $match = [regex]::Match($line, $pattern)
        if ($match.Success) {
            $processIds += [int]$match.Groups[1].Value
        }
    }

    $uniqueProcessIds = @()
    foreach ($item in $processIds) {
        $id = [int]$item
        if ($id -gt 0 -and $uniqueProcessIds -notcontains $id) {
            $uniqueProcessIds += $id
        }
    }
    return $uniqueProcessIds
}

function Stop-PortListeners {
    param(
        [int]$Port,
        [string]$Label
    )

    $listenerProcessIds = Get-ListeningPortPids -Port $Port
    if ($listenerProcessIds.Count -eq 0) {
        Write-Host "$Label port $Port is free."
        return
    }

    Write-Warning "$Label port $Port is already in use. Stopping old listener process(es): $($listenerProcessIds -join ', ')"
    foreach ($processId in $listenerProcessIds) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "Stopped PID $processId on port $Port."
        }
        catch {
            # 有时 Uvicorn reloader 子进程需要 taskkill 才能干净退出。
            & taskkill.exe /PID $processId /F | Out-Host
        }
    }

    Start-Sleep -Seconds 1
    $remaining = Get-ListeningPortPids -Port $Port
    if ($remaining.Count -gt 0) {
        throw "$Label port $Port is still occupied by PID(s): $($remaining -join ', '). Close them manually or rerun as Administrator."
    }
}

function Start-DevWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$ScriptPath,
        [string]$ExtraArgs
    )

    $processArgs = @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath)
    if (-not [string]::IsNullOrWhiteSpace($ExtraArgs)) {
        $processArgs += $ExtraArgs.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
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

if (-not $SkipPortCleanup) {
    Write-Step "Clean old local dev processes"
    Stop-PortListeners -Port $BackendPort -Label "Backend"
    Stop-PortListeners -Port $FrontendPort -Label "Frontend"
}
else {
    if (Test-PortInUse -Port $BackendPort) {
        Write-Warning "Port $BackendPort is already in use. The backend window may fail to start. Use -BackendPort to choose another port."
    }

    if (Test-PortInUse -Port $FrontendPort) {
        Write-Warning "Port $FrontendPort is already in use. The frontend window may fail to start. Use -FrontendPort to choose another port."
    }
}

Write-Step "Start backend FastAPI"
Start-DevWindow `
    -Title "LearnFlow Backend" `
    -WorkingDirectory $BackendDir `
    -ScriptPath $BackendRunner `
    -ExtraArgs "-BackendPort $BackendPort"

Write-Step "Start frontend Next.js"
Start-DevWindow `
    -Title "LearnFlow Frontend" `
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
