@echo off
REM ============================================================
REM  THM Data Hub — Weekly Category Maintenance
REM  Schedule: every Monday at 10:00 AM
REM  Action: re-runs seed (idempotent) + classifies any new
REM          unclassified clients via Haiku
REM ============================================================

cd /d "%~dp0.."

echo [%date% %time%] Running category maintenance...
venv\Scripts\python.exe scripts\maintain_categories.py
echo [%date% %time%] Maintenance complete.
