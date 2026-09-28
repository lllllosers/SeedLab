@echo off
cd /d "%~dp0"
python scripts\run_tests.py %*
if errorlevel 1 pause
