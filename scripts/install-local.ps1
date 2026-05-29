#requires -Version 5.1
param(
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

Write-Step "Create local runtime directories"
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir "storage\materials") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir "storage\chroma") | Out-Null

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
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

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
    $PythonPath = Get-RequiredCommandPath `
        -Names @("python.exe", "python", "py.exe", "py") `
        -InstallHint "Install Python 3.11+ and enable Add Python to PATH."

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
    $NodePath = Get-RequiredCommandPath `
        -Names @("node.exe", "node") `
        -InstallHint "Install Node.js 20 LTS or newer."
    $NpmPath = Get-RequiredCommandPath `
        -Names @("npm.cmd", "npm") `
        -InstallHint "Make sure Node.js is available in PATH."

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
Write-Host "Regenerate env files with: powershell -ExecutionPolicy Bypass -File .\scripts\install-local.ps1 -ForceEnv"
