@echo off
REM ============================================================
REM  THM Data Hub - Scheduled Task Watchdog
REM  Schedule: daily at 11:00 AM (after morning tasks complete)
REM  Action: emails an alert if any THM/CallRail task failed in last 36h
REM ============================================================

cd /d "%~dp0.."

echo [%date% %time%] Running task watchdog...
venv\Scripts\python.exe scripts\task_watchdog.py
echo [%date% %time%] Watchdog complete.
