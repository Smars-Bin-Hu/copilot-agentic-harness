@echo off
rem harness-watch.cmd: the harness load monitor, in this window, one screen every 15 s (Ctrl+C stops it).
rem   harness-watch.cmd                 the harness folder: the one remembered, else the one this file is in, else the current folder, else it asks (and remembers it)
rem   harness-watch.cmd D:\harness      that folder
rem   harness-watch.cmd D:\harness --detail H1    one screen about one code of the screen (H1, R3, B2, ...)
rem Each start fetches the newest harness-watch.py from the pc-tests branch (through the proxy, then without it); when that fails the copy fetched before is used.
setlocal
chcp 65001 >nul
title harness-watch

set "HERE=%USERPROFILE%\harness-watch"
if not exist "%HERE%\" mkdir "%HERE%"
set "ROOT=%~1"
if not "%ROOT%"=="" goto have_root
if exist "%HERE%\folder.txt" set /p ROOT=<"%HERE%\folder.txt"
if not "%ROOT%"=="" if exist "%ROOT%\.harness\" goto have_root
set "ROOT="
if exist "%~dp0.harness\" set "ROOT=%~dp0"
if not "%ROOT%"=="" goto have_root
if exist "%CD%\.harness\" set "ROOT=%CD%"
if not "%ROOT%"=="" goto have_root
set /p "ROOT=Harness folder (the one with .harness in it): "
:have_root
set "ROOT=%ROOT:"=%"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
if not exist "%ROOT%\.harness\" (
  echo Not a harness folder: "%ROOT%"
  if exist "%HERE%\folder.txt" del "%HERE%\folder.txt"
  pause
  exit /b 1
)
> "%HERE%\folder.txt" echo %ROOT%

set "URL=https://raw.githubusercontent.com/Smars-Bin-Hu/copilot-agentic-harness/pc-tests/harness-watch/harness-watch.py"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $out='%HERE%\harness-watch.new'; foreach ($proxy in @('http://127.0.0.1:9000', '')) { try { if ($proxy) { Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -Proxy $proxy -OutFile $out '%URL%' } else { Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -OutFile $out '%URL%' }; Move-Item -Force $out '%HERE%\harness-watch.py'; Write-Host 'harness-watch.py is up to date.'; exit 0 } catch { } }; Write-Host 'Could not fetch the newest harness-watch.py; using the copy fetched before.'"
if not exist "%HERE%\harness-watch.py" (
  echo harness-watch.py is not there and could not be fetched: check the network, then run this again.
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found: it is the one the harness uses; open the window the harness runs in and try there.
  pause
  exit /b 1
)

mode con: cols=110 lines=45 >nul 2>nul
python "%HERE%\harness-watch.py" "%ROOT%" %2 %3 %4 %5
echo.
pause
