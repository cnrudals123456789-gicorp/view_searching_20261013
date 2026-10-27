@echo off
REM Task Scheduler entry: run the ranking check (with its retries), then publish to the web if it succeeded.
REM "run_and_publish.bat dryrun" tests the flow without a real search.
REM ASCII only on purpose: UTF-8 Korean text in .bat files can break cmd parsing.
REM 2026-10-20: naver_guard.py checks the login first (one auto login at most; captcha or 7 days -> login window).
set PKG=
for /r "%~dp0" %%F in (rank.p*) do set PKG=%%~dpF
if not defined PKG exit /b 9
set AUTO=
for %%B in ("%PKG%*.bat") do findstr /c:"wait_net.py" "%%~B" >nul && set AUTO=%%~B
if not defined AUTO exit /b 9
set PYTHONUTF8=1
if not exist "%~dp0logs" mkdir "%~dp0logs"
set GLOG="%~dp0logs\guard.log"
if /i "%~1"=="dryrun" goto run
python "%~dp0naver_guard.py" check >> %GLOG% 2>&1
if errorlevel 10 goto run
if errorlevel 1 exit /b 8
:run
call "%AUTO%" %*
set RC=%ERRORLEVEL%
if /i "%~1"=="dryrun" exit /b %RC%
if "%RC%"=="0" goto publish
REM The session may have expired during the run: re-check once, and try again only if a new login happened.
python "%~dp0naver_guard.py" check >> %GLOG% 2>&1
if not "%ERRORLEVEL%"=="10" exit /b %RC%
call "%AUTO%" %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" exit /b %RC%
:publish
call "%~dp0publish.bat"
exit /b %ERRORLEVEL%
