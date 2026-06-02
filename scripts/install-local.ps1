#requires -Version 5.1
param(
    [switch]$InstallSystemDeps,
    [switch]$ForceEnv,
    [switch]$SkipBackend,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$BackendVenvDir = Join-Path $BackendDir ".venv"
$BackendVenvPython = Join-Path $BackendVenvDir "Scripts\python.exe"
$MinPythonVersion = [Version]"3.11.0"
$MinNodeVersion = [Version]"20.0.0"
$ResolvedPythonPath = $null
$ResolvedNodePath = $null
$ResolvedNpmPath = $null

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-RequiredCommandPath {
    param(
        [string[]]$Names,
        [string]$InstallHint
    )

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return $command.Source
        }
    }

    throw "Command not found: $($Names -join ', '). $InstallHint"
}

function Find-CommandPath {
    param([string[]]$Names)

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return $command.Source
        }
    }

    return $null
}

function ConvertTo-VersionOrNull {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    $cleanValue = $Value.Trim().TrimStart("v")
    try {
        return [Version]$cleanValue
    }
    catch {
        return $null
    }
}

function Get-PythonVersion {
    param([string]$PythonPath)

    try {
        $leafName = Split-Path -Leaf $PythonPath
        if ($leafName -like "py*") {
            $output = & $PythonPath -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        }
        else {
            $output = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        }

        return ConvertTo-VersionOrNull ($output | Select-Object -First 1)
    }
    catch {
        return $null
    }
}

function Get-NodeVersion {
    param([string]$NodePath)

    try {
        $output = & $NodePath --version 2>$null
        return ConvertTo-VersionOrNull ($output | Select-Object -First 1)
    }
    catch {
        return $null
    }
}

function Resolve-PythonPath {
    $candidates = @("python.exe", "python", "py.exe", "py")
    foreach ($name in $candidates) {
        $path = Find-CommandPath -Names @($name)
        if ([string]::IsNullOrWhiteSpace($path)) {
            continue
        }

        $version = Get-PythonVersion -PythonPath $path
        if ($null -ne $version -and $version -ge $MinPythonVersion) {
            Write-Host "Python found: $path ($version)" -ForegroundColor Green
            return $path
        }

        if ($null -ne $version) {
            Write-Host "Python too old: $path ($version), need $MinPythonVersion+" -ForegroundColor Yellow
        }
    }

    return $null
}

function Resolve-NodePath {
    $path = Find-CommandPath -Names @("node.exe", "node")
    if ([string]::IsNullOrWhiteSpace($path)) {
        return $null
    }

    $version = Get-NodeVersion -NodePath $path
    if ($null -ne $version -and $version -ge $MinNodeVersion) {
        Write-Host "Node.js found: $path ($version)" -ForegroundColor Green
        return $path
    }

    if ($null -ne $version) {
        Write-Host "Node.js too old: $path ($version), need $MinNodeVersion+" -ForegroundColor Yellow
    }

    return $null
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Install-WingetPackage {
    param(
        [string]$PackageId,
        [string]$DisplayName
    )

    $wingetPath = Find-CommandPath -Names @("winget.exe", "winget")
    if ([string]::IsNullOrWhiteSpace($wingetPath)) {
        throw "winget not found. Please install App Installer from Microsoft Store, or install $DisplayName manually."
    }

    Write-Host "Installing $DisplayName with winget..." -ForegroundColor Cyan
    & $wingetPath install --id $PackageId -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed to install $DisplayName. Exit code: $LASTEXITCODE"
    }

    Refresh-ProcessPath
}

function Ensure-Python {
    $pythonPath = Resolve-PythonPath
    if (-not [string]::IsNullOrWhiteSpace($pythonPath)) {
        return $pythonPath
    }

    if (-not $InstallSystemDeps) {
        throw "Python $MinPythonVersion+ not found. Install it manually, or run: .\install-local.bat --install-system-deps"
    }

    Install-WingetPackage -PackageId "Python.Python.3.11" -DisplayName "Python 3.11"
    $pythonPath = Resolve-PythonPath
    if ([string]::IsNullOrWhiteSpace($pythonPath)) {
        throw "Python was installed but is not available in this terminal yet. Restart PowerShell and run .\install-local.bat again."
    }

    return $pythonPath
}

function Ensure-NodeAndNpm {
    $nodePath = Resolve-NodePath
    $npmPath = Find-CommandPath -Names @("npm.cmd", "npm")

    if (-not [string]::IsNullOrWhiteSpace($nodePath) -and -not [string]::IsNullOrWhiteSpace($npmPath)) {
        Write-Host "npm found: $npmPath" -ForegroundColor Green
        return @{
            Node = $nodePath
            Npm = $npmPath
        }
    }

    if (-not $InstallSystemDeps) {
        throw "Node.js $MinNodeVersion+ or npm not found. Install Node.js LTS manually, or run: .\install-local.bat --install-system-deps"
    }

    Install-WingetPackage -PackageId "OpenJS.NodeJS.LTS" -DisplayName "Node.js LTS"
    $nodePath = Resolve-NodePath
    $npmPath = Find-CommandPath -Names @("npm.cmd", "npm")
    if ([string]::IsNullOrWhiteSpace($nodePath) -or [string]::IsNullOrWhiteSpace($npmPath)) {
        throw "Node.js was installed but node/npm is not available in this terminal yet. Restart PowerShell and run .\install-local.bat again."
    }

    Write-Host "npm found: $npmPath" -ForegroundColor Green
    return @{
        Node = $nodePath
        Npm = $npmPath
    }
}

function Write-Utf8File {
    param(
        [string]$FilePath,
        [string]$DirectoryPath,
        [string]$Content
    )

    if ([string]::IsNullOrWhiteSpace($FilePath)) {
        throw "File path is empty when writing environment file."
    }

    if ([string]::IsNullOrWhiteSpace($DirectoryPath)) {
        throw "Directory path is empty when writing file: $FilePath"
    }

    if (-not (Test-Path -LiteralPath $DirectoryPath)) {
        New-Item -ItemType Directory -Force -Path $DirectoryPath | Out-Null
    }

    $utf8Encoding = New-Object System.Text.UTF8Encoding -ArgumentList $false
    [System.IO.File]::WriteAllText($FilePath, $Content, $utf8Encoding)
    if (-not (Test-Path -LiteralPath $FilePath)) {
        throw "Failed to write file: $FilePath"
    }
}

function Write-EnvFileIfNeeded {
    param(
        [string]$FilePath,
        [string]$DirectoryPath,
        [string]$Content,
        [switch]$Force,
        [switch]$Optional
    )

    if ([string]::IsNullOrWhiteSpace($FilePath)) {
        throw "Environment file path is empty."
    }

    if ((Test-Path -LiteralPath $FilePath) -and -not $Force) {
        Write-Host "Already exists, skip: $FilePath" -ForegroundColor Yellow
        return
    }

    try {
        Write-Utf8File -FilePath $FilePath -DirectoryPath $DirectoryPath -Content $Content
        Write-Host "Written: $FilePath" -ForegroundColor Green
    }
    catch {
        if ($Optional) {
            Write-Warning "Could not write optional env file: $FilePath"
            Write-Warning "Reason: $($_.Exception.Message)"
            Write-Warning "The start script will inject frontend env vars at runtime, so installation can continue."
            return
        }

        throw
    }
}

if (-not (Test-Path -LiteralPath $BackendDir)) {
    throw "Backend directory not found: $BackendDir"
}

if (-not (Test-Path -LiteralPath $FrontendDir)) {
    throw "Frontend directory not found: $FrontendDir"
}

Write-Step "Check system dependencies"
if (-not $SkipBackend) {
    $ResolvedPythonPath = Ensure-Python
}
else {
    Write-Host "Python check skipped with -SkipBackend."
}

if (-not $SkipFrontend) {
    $nodeTools = Ensure-NodeAndNpm
    $ResolvedNodePath = $nodeTools.Node
    $ResolvedNpmPath = $nodeTools.Npm
}
else {
    Write-Host "Node.js/npm check skipped with -SkipFrontend."
}

Write-Step "Create local runtime directories"
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir "storage\materials") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir "storage\chroma") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir "storage\ocr") | Out-Null

Write-Step "Prepare local environment files"
$BackendEnvPath = Join-Path $BackendDir ".env"
$BackendEnvContent = @'
# StudyAgent backend local development config.
# SQLite keeps local startup independent from Docker/PostgreSQL.
DATABASE_URL=sqlite:///./studyagent.db

# Redis is only required when async jobs are enabled.
REDIS_URL=redis://localhost:6379/0

# Fill this key to use DeepSeek. Leave it empty to use local fallback rules.
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# Optional: enable PaddleOCR-VL for PDF OCR before RAG indexing and reading.
# Keep the token only in backend/.env; do not commit it to GitHub.
OCR_PROVIDER=none
PADDLE_OCR_TOKEN=
PADDLE_OCR_JOB_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
PADDLE_OCR_MODEL=PaddleOCR-VL-1.6
OCR_STORAGE_DIR=./storage/ocr

# Allow the local Next.js dev server to access FastAPI.
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Local persistence for uploaded materials and Chroma.
MATERIAL_UPLOAD_DIR=./storage/materials
CHROMA_PERSIST_DIR=./storage/chroma
CHUNK_SIZE=800
CHUNK_OVERLAP=120
RAG_ENRICH_MAX_CHUNKS=12
'@
Write-EnvFileIfNeeded -FilePath $BackendEnvPath -DirectoryPath $BackendDir -Content $BackendEnvContent -Force:$ForceEnv

$FrontendEnvPath = Join-Path -Path $FrontendDir -ChildPath ".env.local"
$FrontendEnvContent = @'
# StudyAgent frontend local development config.
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api/v1

# false means local sync mode, so Redis/Celery is not required.
NEXT_PUBLIC_USE_ASYNC_JOBS=false
'@
Write-EnvFileIfNeeded -FilePath $FrontendEnvPath -DirectoryPath $FrontendDir -Content $FrontendEnvContent -Force:$ForceEnv -Optional

if (-not $SkipBackend) {
    Write-Step "Install backend Python dependencies"
    $PythonPath = $ResolvedPythonPath

    if (-not (Test-Path -LiteralPath $BackendVenvPython)) {
        Write-Host "Create virtual environment: $BackendVenvDir"
        if ((Split-Path -Leaf $PythonPath) -like "py*") {
            & $PythonPath -3 -m venv $BackendVenvDir
        }
        else {
            & $PythonPath -m venv $BackendVenvDir
        }
    }
    else {
        Write-Host "Virtual environment already exists, skip: $BackendVenvDir" -ForegroundColor Yellow
    }

    & $BackendVenvPython -m pip install --upgrade pip
    & $BackendVenvPython -m pip install -r (Join-Path $BackendDir "requirements.txt")
}
else {
    Write-Host "Backend dependency installation skipped."
}

if (-not $SkipFrontend) {
    Write-Step "Install frontend Node dependencies"
    $NodePath = $ResolvedNodePath
    $NpmPath = $ResolvedNpmPath

    & $NodePath --version
    Push-Location $FrontendDir
    try {
        & $NpmPath install
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "Frontend dependency installation skipped."
}

Write-Step "Install finished"
Write-Host "Start the project with: .\start-local.bat"
Write-Host "Install missing Python/Node with: .\install-local.bat --install-system-deps"
Write-Host "Regenerate env files with: powershell -ExecutionPolicy Bypass -File .\scripts\install-local.ps1 -ForceEnv"
