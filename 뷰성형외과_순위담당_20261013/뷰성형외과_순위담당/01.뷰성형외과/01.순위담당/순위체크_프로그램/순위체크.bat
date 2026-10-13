@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM 대시보드에 저장된 설정(settings.json)으로 순위 체크 1회 실행. 세션 만료 시 자동 로그인.
python run.py
echo.
pause
