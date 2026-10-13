@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM 최신 실행분 파워컨텐츠 순위를 settings.json 순서로 클립보드에 복사 (PC / MO 두 열)
set PYTHONUTF8=1
python paste.py %*
echo.
pause
