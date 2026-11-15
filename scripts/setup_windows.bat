@echo off
REM One-time setup: creates .venv and installs everything.
cd /d "%~dp0\.."
py -3.11 -m venv .venv || python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist backend\.env copy backend\.env.example backend\.env
if not exist .streamlit\secrets.toml copy .streamlit\secrets.toml.example .streamlit\secrets.toml
echo.
echo Setup complete. Next: scripts\start_all.bat
pause
