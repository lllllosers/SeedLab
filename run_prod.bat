@echo off
cd /d "%~dp0"
python scripts\run_prod.py %*
if errorlevel 1 pause
