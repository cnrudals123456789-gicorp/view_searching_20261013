@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 파워링크 순위 대시보드를 시작합니다. 이 창을 닫으면 대시보드가 종료됩니다.
python app.py
pause