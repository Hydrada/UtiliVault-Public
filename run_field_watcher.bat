@echo off
REM UtiliVault — Field Intake Watcher runner (called by Windows Task Scheduler)
REM Checks the Drive "11 - Field Intake" folder once and processes any new
REM curb photos, then exits. Scheduled to run on an interval.
set "PATH=%PATH%;C:\Program Files\Tesseract-OCR"
cd /d "%~dp0"
py field_intake_watcher.py --once >> "field_watcher_log.txt" 2>&1
