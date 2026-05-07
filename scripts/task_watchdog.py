"""
Daily watchdog: checks Windows Task Scheduler for any failed/missed runs
of THM-related tasks in the last 24h. Emails a summary only if something
needs attention.

Runs at 11:00 AM after all morning tasks have completed.

Result codes interpreted:
  0          = success, nothing to report
  267011     = 0x41303 = SCHED_S_TASK_HAS_NOT_RUN (scheduled but never run)
  3221225786 = 0xC000013A = STATUS_CONTROL_C_EXIT (process killed)
  others     = failure of some kind

Usage:
  python scripts/task_watchdog.py             # run + email if issues
  python scripts/task_watchdog.py --no-email  # report only
  python scripts/task_watchdog.py --always    # email even if all healthy
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.import_report import send_email  # reuse existing email plumbing


# Tasks to monitor — match by substring
WATCHED_PATTERNS = [
    "THM Data Hub",
    "CallRail",
]


def _ps_get_tasks() -> list[dict]:
    """Use PowerShell to grab all matching scheduled tasks + their last result."""
    ps = r"""
    $tasks = Get-ScheduledTask | Where-Object {
        $_.TaskName -match 'THM|CallRail'
    }
    $output = @()
    foreach ($t in $tasks) {
        $info = Get-ScheduledTaskInfo -TaskName $t.TaskName
        $output += @{
            TaskName = $t.TaskName
            State = "$($t.State)"
            LastRunTime = if ($info.LastRunTime) { $info.LastRunTime.ToString('o') } else { $null }
            LastTaskResult = $info.LastTaskResult
            NextRunTime = if ($info.NextRunTime) { $info.NextRunTime.ToString('o') } else { $null }
            NumberOfMissedRuns = $info.NumberOfMissedRuns
        }
    }
    $output | ConvertTo-Json -Compress
    """
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell error: {result.stderr}")
    if not result.stdout.strip():
        return []
    data = json.loads(result.stdout)
    return data if isinstance(data, list) else [data]


def _interpret_result(code: int) -> tuple[str, str]:
    """Return (status, description) for a Windows scheduled-task result code."""
    if code == 0:
        return ("OK", "Completed successfully")
    if code == 267011:  # 0x41303
        return ("WAITING", "Task has not run yet")
    if code == 267009:  # 0x41301
        return ("RUNNING", "Currently running")
    if code == 267010:  # 0x41302
        return ("DISABLED", "Task is disabled")
    if code == 3221225786:  # 0xC000013A
        return ("KILLED", "Process killed (Ctrl+C / forced shutdown / sleep mode)")
    if code == 1:
        return ("FAILED", "Unspecified error / non-zero exit")
    if code == 2147750671:  # 0x800710CF
        return ("OFFLINE", "Task ran while user not logged in (Interactive mode)")
    if code == 2147942401:  # 0x80070001
        return ("BAD_FUNCTION", "Incorrect function (script error)")
    return ("UNKNOWN", f"Unknown code {code} (hex 0x{code:08X})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--always", action="store_true", help="Email even if everything is healthy")
    args = parser.parse_args()

    print("Fetching scheduled task statuses...")
    tasks = _ps_get_tasks()
    print(f"  {len(tasks)} matching tasks")

    now = datetime.now(timezone.utc)
    issues = []
    healthy = []

    for t in tasks:
        # Skip self — when this script runs, its own scheduled task is in
        # RUNNING state, which would trigger a false "Currently running" alert.
        if "Watchdog" in t["TaskName"]:
            continue
        code = t.get("LastTaskResult")
        status, desc = _interpret_result(code)
        last_run_str = t.get("LastRunTime")
        last_run = None
        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str.replace("Z", "+00:00"))
            except Exception:
                last_run = None

        record = {
            "name": t["TaskName"],
            "status": status,
            "description": desc,
            "last_run": last_run,
            "next_run": t.get("NextRunTime"),
            "code": code,
        }

        # Bucket: success if code=0 AND ran in last 36h; warning otherwise (for daily tasks)
        is_daily = "Daily" in t["TaskName"] or "AutoTag" in t["TaskName"]
        if code == 0 and last_run and (now - last_run) < timedelta(hours=36):
            healthy.append(record)
        elif status == "WAITING":
            # Brand-new task, never run yet — skip silently
            healthy.append(record)
        elif is_daily and (not last_run or (now - last_run) > timedelta(hours=36)):
            record["issue"] = f"Daily task hasn't run in {((now - last_run).total_seconds() / 3600):.1f}h" if last_run else "Daily task has never run"
            issues.append(record)
        elif code != 0:
            record["issue"] = f"Last run failed: {desc}"
            issues.append(record)
        else:
            healthy.append(record)

    print(f"\n  Issues: {len(issues)}")
    print(f"  Healthy: {len(healthy)}")
    for r in issues:
        print(f"    [ISSUE] {r['name']}: {r['issue']}")

    if not issues and not args.always:
        print("\nAll tasks healthy. No email needed.")
        return

    if args.no_email:
        print("\n--no-email: skipping send")
        return

    # Build email
    rows = ""
    for r in issues + healthy:
        is_issue = "issue" in r
        color = "#C0392B" if is_issue else "#27AE60"
        last_run_disp = r["last_run"].astimezone().strftime("%Y-%m-%d %H:%M") if r["last_run"] else "—"
        next_run_disp = r["next_run"][:16].replace("T", " ") if r["next_run"] else "—"
        msg = r.get("issue", r["description"])
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:{color};font-weight:bold;'>{r['status']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;'>{r['name']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:#5C6370;font-size:13px;'>{msg}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:#5C6370;font-size:13px;'>{last_run_disp}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:#5C6370;font-size:13px;'>{next_run_disp}</td>"
            f"</tr>"
        )

    subject_prefix = "ALERT" if issues else "OK"
    today_str = date.today().strftime("%Y-%m-%d")
    subject = f"[{subject_prefix}] THM Scheduled Tasks — {today_str}"

    headline_color = "#C0392B" if issues else "#27AE60"
    headline = f"{len(issues)} issue(s) needs attention" if issues else "All scheduled tasks healthy"

    html = f"""
    <html>
    <body style='font-family:Arial,sans-serif;color:#2C3E50;max-width:880px;'>
      <h2 style='color:{headline_color};margin-bottom:4px;'>Scheduled Task Watchdog — {today_str}</h2>
      <p style='color:#5C6370;'>{headline}</p>
      <table style='border-collapse:collapse;border:1px solid #ddd;margin:12px 0;'>
        <thead>
          <tr style='background:#1F4E78;color:white;'>
            <th style='padding:8px 12px;text-align:left;'>Status</th>
            <th style='padding:8px 12px;text-align:left;'>Task</th>
            <th style='padding:8px 12px;text-align:left;'>Notes</th>
            <th style='padding:8px 12px;text-align:left;'>Last Run</th>
            <th style='padding:8px 12px;text-align:left;'>Next Run</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style='color:#5C6370;font-size:12px;'>
        Generated by <code>scripts/task_watchdog.py</code> — runs daily at 11:00 AM via Windows Task Scheduler.
      </p>
    </body>
    </html>
    """

    send_email(subject, html)


if __name__ == "__main__":
    main()
