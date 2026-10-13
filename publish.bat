@echo off
chcp 65001 >nul
REM 순위 결과(results_*.csv) -> docs\data.json 변환 후 GitHub 로 푸시 (GitHub Pages 가 자동 반영)
REM 변경이 없으면 아무것도 하지 않음. 실패해도 순위 체크 본체에는 영향 없음.
cd /d "%~dp0"
set PYTHONUTF8=1
set PKG=%~dp0뷰성형외과_순위담당_20261013\뷰성형외과_순위담당\01.뷰성형외과\01.순위담당\순위체크_프로그램
set PY=python
if not exist logs mkdir logs
set LOG=logs\publish.log

echo [%date% %time%] publish start >> "%LOG%"
%PY% -I build_data.py "%PKG%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] build_data failed >> "%LOG%"
  exit /b 1
)
git add docs/data.json >> "%LOG%" 2>&1
git diff --cached --quiet
if %ERRORLEVEL%==0 (
  echo [%date% %time%] no change >> "%LOG%"
  exit /b 0
)
git commit -m "순위 갱신 %date% %time:~0,5%" >> "%LOG%" 2>&1
git push >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] git push failed >> "%LOG%"
  exit /b 1
)
echo [%date% %time%] published >> "%LOG%"
exit /b 0
