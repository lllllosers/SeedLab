@echo off
cd /d "%~dp0"
python scripts\run_dev.py
if errorlevel 1 pause
