@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Task Scheduler (daily 10:10 / 16:00, was 09:00 until 2026-10-12). No pause. Output -> logs\YYYYMMDD.log
REM 2026-09-28: retry up to 3 times (3 min apart) when run.py fails (e.g. no internet right after wake).
REM 2026-10-06 (task 71): wait for internet before each try (wait_net.py, max 10 min, keeps PC awake),
REM   report result to agent-leader dashboard (report_run.py). Test without a real run: this.bat dryrun
if not exist logs mkdir logs
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PY="%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist %PY% set PY=python
for /f "tokens=1-3 delims=-/. " %%a in ("%date%") do set TODAY=%%a%%b%%c
set DRY=
if /i "%~1"=="dryrun" set DRY=1
set LOG=logs\%TODAY%.log
if defined DRY set LOG=logs\%TODAY%_dryrun.log
set TRY=0
:retry
set /a TRY+=1
%PY% wait_net.py >> "%LOG%" 2>&1
if defined DRY goto dryrun
%PY% run.py >> "%LOG%" 2>&1
if %ERRORLEVEL%==0 goto recheck
echo [retry] attempt %TRY% failed (exit %ERRORLEVEL%) >> "%LOG%"
if %TRY% GEQ 4 goto failed
timeout /t 180 /nobreak >nul
goto retry
:failed
%PY% report_run.py --status fail --tries %TRY% >> "%LOG%" 2>&1
exit /b 1
:recheck
%PY% report_run.py --status ok >> "%LOG%" 2>&1
REM 2026-10-06 16:46 director: no recheck loop for non-exposed combos any more (run once and finish).
REM   Results go to ..\(rank folder)\summary xlsx via rank.py -> summary.py (paths.py XL_DIR).
exit /b 0
:dryrun
echo [dryrun] %date% %time% wait_net exit %ERRORLEVEL% - run.py skipped >> "%LOG%"
%PY% report_run.py --status ok --dry-run >> "%LOG%" 2>&1
%PY% report_run.py --status fail --tries 4 --dry-run >> "%LOG%" 2>&1
exit /b 0
