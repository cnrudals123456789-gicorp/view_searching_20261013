@echo off
REM Task Scheduler entry: run the ranking check (with its retries), then publish to the web if it succeeded.
REM "run_and_publish.bat dryrun" tests the flow without a real search.
REM ASCII only on purpose: UTF-8 Korean text in .bat files can break cmd parsing.
set PKG=
for /r "%~dp0" %%F in (rank.p*) do set PKG=%%~dpF
if not defined PKG exit /b 9
set AUTO=
for %%B in ("%PKG%*.bat") do findstr /c:"wait_net.py" "%%~B" >nul && set AUTO=%%~B
if not defined AUTO exit /b 9
call "%AUTO%" %*
set RC=%ERRORLEVEL%
if /i "%~1"=="dryrun" exit /b %RC%
if not "%RC%"=="0" exit /b %RC%
call "%~dp0publish.bat"
exit /b %ERRORLEVEL%
