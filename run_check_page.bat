@echo off
REM Double-click: opens the ranking page with a "check now" button (this PC only).
cd /d "%~dp0"
set PYTHONUTF8=1
python serve.py
pause
