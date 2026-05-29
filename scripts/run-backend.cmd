@echo off
setlocal
set "ROOT=%~dp0.."
set "BACKEND_DIR=%ROOT%\backend"
set "BACKEND_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"

if not exist "%BACKEND_PYTHON%" (
  echo Backend virtual environment not found:
  echo %BACKEND_PYTHON%
  echo.
  echo Please run install-local.bat first.
  pause
  exit /b 1
)

cd /d "%BACKEND_DIR%"
echo Starting StudyAgent backend on http://127.0.0.1:8000
"%BACKEND_PYTHON%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

echo.
echo Backend process exited.
pause
endlocal
