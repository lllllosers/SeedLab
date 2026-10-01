@echo off
cd /d "%~dp0"
python scripts\run_control_center.py %*
if errorlevel 1 pause
