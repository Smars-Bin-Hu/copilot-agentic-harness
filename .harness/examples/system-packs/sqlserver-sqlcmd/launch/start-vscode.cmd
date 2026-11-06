@echo off
rem Start VS Code under the identity the database takes (Windows authentication over the network), as the team starts SSMS.
rem runas /netonly keeps your own identity on this computer and uses the one you type for the network only. It asks for the password itself: nothing is stored.
rem Change EXAMPLE to your domain and the path to your VS Code. Run it from the folder of the harness.
set /p ID=Your account (EXAMPLE\id):
if "%ID%"=="" exit /b 1
runas /user:%ID% /netonly "\"%LocalAppData%\Programs\Microsoft VS Code\Code.exe\" \"%CD%\""
