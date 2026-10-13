@echo off
chcp 65001 >nul
REM 작업 스케줄러용: 순위 체크(자동순위체크.bat, 재시도 포함) -> 성공하면 웹 게시(publish.bat)
set PKG=%~dp0뷰성형외과_순위담당_20261013\뷰성형외과_순위담당\01.뷰성형외과\01.순위담당\순위체크_프로그램
call "%PKG%\자동순위체크.bat" %*
set RC=%ERRORLEVEL%
if /i "%~1"=="dryrun" exit /b %RC%
if not "%RC%"=="0" exit /b %RC%
call "%~dp0publish.bat"
exit /b %ERRORLEVEL%
