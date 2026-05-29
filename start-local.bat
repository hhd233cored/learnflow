@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND_RUNNER=%ROOT%scripts\run-backend.cmd"
set "FRONTEND_RUNNER=%ROOT%scripts\run-frontend.cmd"

echo.
echo ^>^=^> Start backend FastAPI
start "StudyAgent Backend" cmd /k ""%BACKEND_RUNNER%""

echo.
echo ^>^=^> Start frontend Next.js
start "StudyAgent Frontend" cmd /k ""%FRONTEND_RUNNER%""

echo.
echo ^>^=^> Local dev servers have been launched
echo Backend health: http://127.0.0.1:8000/api/v1/health
echo Frontend page: http://127.0.0.1:3000
echo Tip: this script opens two cmd windows. Close the corresponding window to stop a service.

echo.
echo Opening browser in 3 seconds...
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:3000"

endlocal
