@echo off
rem Double-click on Windows: starts the task board of this copy. Keep this window open while you work.
cd /d "%~dp0"
where python >nul 2>nul || where python3 >nul 2>nul || where py >nul 2>nul
if errorlevel 1 (
  echo Harness needs Python 3.9 or newer. Install it, then double-click Start Harness again.
  pause
  exit /b 1
)
call .harness\bin\harness.cmd task board
if errorlevel 1 pause
