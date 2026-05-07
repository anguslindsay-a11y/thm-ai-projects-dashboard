@echo off
REM ============================================================
REM  THM Data Hub — Weekly Data Refresh
REM
REM  Before running:
REM    1. Export fresh Waterfall from MagManager -> save to data/
REM    2. Export Uniqode scan data -> save to data/
REM    3. Get updated IA spreadsheet -> save to data/
REM    4. Get updated ad placement files from designers -> save to data/
REM
REM  Usage:
REM    weekly_refresh.bat              Run all imports (live)
REM    weekly_refresh.bat --dry-run    Preview only
REM    weekly_refresh.bat --only calls Run only CallRail ETL
REM ============================================================

cd /d "%~dp0.."

echo [%date% %time%] Starting weekly refresh...
venv\Scripts\python.exe scripts/weekly_refresh.py %*
echo [%date% %time%] Done.
