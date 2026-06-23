@echo off
setlocal
set "ROOT=%~dp0.."
set "FRONTEND_DIR=%ROOT%\frontend"

where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo npm.cmd not found. Please install Node.js or run install-local.bat first.
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
  echo frontend node_modules not found:
  echo %FRONTEND_DIR%\node_modules
  echo.
  echo Please run install-local.bat first.
  pause
  exit /b 1
)

cd /d "%FRONTEND_DIR%"
set "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api/v1"
set "NEXT_PUBLIC_USE_ASYNC_JOBS=false"

echo Starting LearnFlow frontend on http://127.0.0.1:3000
npm.cmd run dev -- --hostname 127.0.0.1 --port 3000

echo.
echo Frontend process exited.
pause
endlocal
