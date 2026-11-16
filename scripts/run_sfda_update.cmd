@echo off
rem Daily SFDA refresh for Windows Task Scheduler. Usage: run_sfda_update.cmd [recheck]
rem Optional: set PHARMAVIQUE_EXE to the full path of pharmavique.exe if the venv is elsewhere.
setlocal
cd /d "%~dp0.."
if not exist data\sfda mkdir data\sfda

set "EXE=%PHARMAVIQUE_EXE%"
if not defined EXE set "EXE=%USERPROFILE%\.venvs\pharmavique\Scripts\pharmavique.exe"
set "RECHECK=%~1"
if "%RECHECK%"=="" set "RECHECK=300"

echo ==== %DATE% %TIME% sfda-update (recheck %RECHECK%) >> data\sfda\update.log
"%EXE%" sfda-update --recheck %RECHECK% >> data\sfda\update.log 2>&1
echo ==== finished with exit code %ERRORLEVEL% >> data\sfda\update.log
exit /b %ERRORLEVEL%
