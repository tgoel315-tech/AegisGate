@echo off
title AegisGate SOC Dashboard & Sentry Server
echo ============================================================
echo   AEGISGATE - AI-Powered Smart Entry ^& Tailgating Monitor
echo ============================================================
echo.
echo [1/2] Starting AegisGate FastAPI Backend on http://localhost:8000 ...
start "" http://localhost:8000
cd /d "%~dp0backend"
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
pause
