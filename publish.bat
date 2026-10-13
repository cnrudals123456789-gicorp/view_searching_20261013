@echo off
REM Build docs\data.json from results_*.csv and push to GitHub (GitHub Pages updates automatically).
REM No change -> nothing happens. Failure here never affects the ranking run itself.
REM ASCII only on purpose: UTF-8 Korean text in .bat files can break cmd parsing.
cd /d "%~dp0"
set PYTHONUTF8=1
set PY=python
set PKG=
for /r "%~dp0" %%F in (rank.p*) do set PKG=%%~dpF
if not defined PKG (
  echo [%date% %time%] rank.py not found >> logs\publish.log
  exit /b 1
)
if not exist logs mkdir logs
set LOG=logs\publish.log

echo [%date% %time%] publish start >> "%LOG%"
%PY% -I build_data.py "%PKG%." >> "%LOG%" 2>&1
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
git commit -m "rank update %date% %time:~0,5%" >> "%LOG%" 2>&1
git push >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] git push failed >> "%LOG%"
  exit /b 1
)
echo [%date% %time%] published >> "%LOG%"
exit /b 0
