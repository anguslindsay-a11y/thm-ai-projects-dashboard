@echo off
REM ============================================================
REM  THM Data Hub - Daily MagManager ETL
REM  Schedule: every day at 06:00 AM (before CallRail at 08:30)
REM  Order: Contacts -> Opportunities -> Activities
REM    Contacts must run first so opportunities/activities can
REM    resolve their (mm_database, mm_customer_id) -> client_id
REM    lookup against the freshest client data.
REM
REM  Skip-if-unchanged is built in:
REM    - Contacts skip rows where mm_date_modified matches
REM    - Opportunities skip rows where mm_modified_date matches
REM    - Activities use upsert (immutable rows, no-op on dupe)
REM
REM  Activity sync uses --days 7 to keep incremental cost low.
REM  Anything older has already been backfilled.
REM ============================================================

cd /d "%~dp0.."

echo [%date% %time%] === MagManager Daily ETL ===

echo [%date% %time%] [1/3] Contacts sync...
venv\Scripts\python.exe etl\etl_mm_contacts.py
if errorlevel 1 (
  echo [%date% %time%] CONTACTS FAILED with exit code %errorlevel%
  exit /b %errorlevel%
)

echo [%date% %time%] [2/3] Opportunities sync...
venv\Scripts\python.exe etl\etl_mm_opportunities.py
if errorlevel 1 (
  echo [%date% %time%] OPPORTUNITIES FAILED with exit code %errorlevel%
  exit /b %errorlevel%
)

echo [%date% %time%] [3/3] Activities sync (last 7 days)...
venv\Scripts\python.exe etl\etl_mm_activities.py --days 7
if errorlevel 1 (
  echo [%date% %time%] ACTIVITIES FAILED with exit code %errorlevel%
  exit /b %errorlevel%
)

echo [%date% %time%] === MagManager Daily ETL complete ===
