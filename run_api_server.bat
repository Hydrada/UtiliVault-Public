@echo off
REM UtiliVault — Field API server runner (called by Windows Task Scheduler)
REM Runs api_server.py continuously (Drive upload ON) so the UtiliVault
REM Field mobile app always has something to talk to. The loop below
REM restarts the server 15s after any crash/exit — more reliable than
REM Task Scheduler's own restart-on-failure, which misses child crashes.
cd /d "%~dp0"
:loop
echo [%date% %time%] starting api_server.py >> "api_server_log.txt"
py api_server.py --port 8791 >> "api_server_log.txt" 2>&1
echo [%date% %time%] api_server.py exited (code %errorlevel%^) — restarting in 15s >> "api_server_log.txt"
timeout /t 15 /nobreak > nul
goto loop
