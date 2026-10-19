@echo off
REM Competitor research: run Claude Code headless (web search), validate docs\competitor.json, push.
REM Failure here never affects the ranking run. ASCII only on purpose.
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist logs mkdir logs
set LOG=logs\research.log
echo [%date% %time%] research start >> "%LOG%"

python -I research\validate.py --backup >> "%LOG%" 2>&1
if /i "%~1"=="dryrun" (
  echo [%date% %time%] dryrun - skip claude >> "%LOG%"
  python -I research\validate.py --check >> "%LOG%" 2>&1
  exit /b 0
)

REM collect raw data with Playwright first (period is read from logs/research_params.json). A failure here is not fatal.
python -I research\collect.py >> "%LOG%" 2>&1
if errorlevel 1 echo [%date% %time%] collect failed - continue with web search only >> "%LOG%"
REM score candidates for 'new marketing method / new overseas market' so the AI reads them first
python -I research\triage.py >> "%LOG%" 2>&1
python -I research\make_prompt.py >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] make_prompt failed >> "%LOG%"
  exit /b 1
)
call "%APPDATA%\npm\claude.cmd" -p --allowedTools "WebSearch,WebFetch,Read,Edit,Write,Bash(python -I research/validate.py:*)" --permission-mode acceptEdits < logs\research_prompt.md >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] claude failed >> "%LOG%"
  python -I research\validate.py --check >> "%LOG%" 2>&1
  exit /b 1
)

python -I research\validate.py --check >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] validate failed - restored backup >> "%LOG%"
  exit /b 1
)

git add docs/competitor.json >> "%LOG%" 2>&1
git diff --cached --quiet
if %ERRORLEVEL%==0 (
  echo [%date% %time%] no change >> "%LOG%"
  exit /b 0
)
git commit -m "competitor update %date% %time:~0,5%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] git commit failed >> "%LOG%"
  exit /b 1
)
git push >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] git push failed >> "%LOG%"
  exit /b 1
)
echo [%date% %time%] published >> "%LOG%"
exit /b 0
