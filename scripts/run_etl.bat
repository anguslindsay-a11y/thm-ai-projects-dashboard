@echo off
REM ============================================================
REM  THM Data Hub — Run CallRail ETL (daily)
REM  Schedule this via Windows Task Scheduler
REM ============================================================

cd /d "%~dp0.."

echo [%date% %time%] Running CallRail ETL...
venv\Scripts\python.exe scripts/weekly_refresh.py --only calls
echo [%date% %time%] ETL complete.
