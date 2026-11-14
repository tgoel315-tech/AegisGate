@echo off
REM Starts backend, RAG agent, vision and dashboard in four windows.
cd /d "%~dp0\.."
start "AegisGate backend"   cmd /k ".venv\Scripts\activate.bat && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"
timeout /t 3 >nul
start "AegisGate RAG agent" cmd /k ".venv\Scripts\activate.bat && python -m rag.start"
start "AegisGate vision"    cmd /k ".venv\Scripts\activate.bat && python -m vision.main --camera 0"
start "AegisGate dashboard" cmd /k ".venv\Scripts\activate.bat && streamlit run dashboard/app.py"
