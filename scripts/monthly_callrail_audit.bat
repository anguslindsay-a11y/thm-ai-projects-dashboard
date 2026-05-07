@echo off
REM ============================================================
REM  THM Data Hub — Monthly CallRail Hygiene Audit
REM  Schedule: 1st of each month at 8:00 AM
REM  Action: runs audit, emails Excel to NOTIFY_EMAILS
REM ============================================================

cd /d "%~dp0.."

echo [%date% %time%] Running monthly CallRail hygiene audit...
venv\Scripts\python.exe scripts\monthly_callrail_audit.py
echo [%date% %time%] Audit complete.
