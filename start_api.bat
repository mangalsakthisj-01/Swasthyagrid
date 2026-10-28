@echo off
cd /d "%~dp0"
python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000
pause
