@echo off
rem Short command for people and agents (Windows): harness <command> ...
rem Like git, it works on the harness repository the current folder is in: it looks upward from the current folder for
rem .harness\engine\cli.py. Outside every harness repository it uses the repository this script sits in; a copy of this script
rem (in a fixed folder in PATH) has none, so it uses the repository named by HARNESS_HOME, or stops with a message.
setlocal
set "HARNESS_DIR=%CD%"
:harness_up
if exist "%HARNESS_DIR%\.harness\engine\cli.py" goto harness_found
for %%I in ("%HARNESS_DIR%\..") do set "HARNESS_PARENT=%%~fI"
if /i "%HARNESS_PARENT%"=="%HARNESS_DIR%" goto harness_own
set "HARNESS_DIR=%HARNESS_PARENT%"
goto harness_up
:harness_found
set "HARNESS_CLI=%HARNESS_DIR%\.harness\engine\cli.py"
goto harness_run
:harness_own
set "HARNESS_CLI=%~dp0..\engine\cli.py"
if exist "%HARNESS_CLI%" goto harness_run
if not defined HARNESS_HOME goto harness_none
if not exist "%HARNESS_HOME%\.harness\engine\cli.py" goto harness_none
set "HARNESS_CLI=%HARNESS_HOME%\.harness\engine\cli.py"
goto harness_run
:harness_none
echo harness: not inside a harness repository. cd into one, or set HARNESS_HOME to one. 1>&2
exit /b 1
:harness_run
rem Find python.exe in PATH with cmd itself, not with `where`: that is one more program to start, and where security software checks
rem every start (a work computer) one start costs a second or more. Without python.exe, the py launcher.
for %%P in (python.exe) do set "HARNESS_PY=%%~$PATH:P"
if not defined HARNESS_PY goto run_py
"%HARNESS_PY%" "%HARNESS_CLI%" %*
exit /b %errorlevel%
:run_py
py "%HARNESS_CLI%" %*
exit /b %errorlevel%
