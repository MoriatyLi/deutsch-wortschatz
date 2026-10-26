@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "app_exit=%errorlevel%"
popd
if not "%app_exit%"=="0" pause
exit /b %app_exit%
