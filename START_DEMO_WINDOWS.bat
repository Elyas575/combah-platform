@echo off
REM Start the Combah local test environment. No live payments or shipments.
cd /d "%~dp0"
set COMBAH_DEMO=1
python -m uvicorn app:app --reload --port 8000
if errorlevel 1 (
  echo.
  echo Cannot start the platform. Make sure Python is installed and run:
  echo   python -m pip install -r requirements.txt
)
pause
