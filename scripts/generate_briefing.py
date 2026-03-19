#!/usr/bin/env python3
"""
Generate a status briefing snapshot for the career-manager router.

Usage:
    python3 scripts/generate_briefing.py          # JSON to stdout
    python3 scripts/generate_briefing.py --pretty  # human-readable

Reads target-companies.csv, applications.csv, and run-log.jsonl.
Handles missing files gracefully (returns first_run indicator).
"""

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def generate_briefing(project_root=None):
    """Generate a status snapshot from pipeline data files.

    Args:
        project_root: Path to project root. Defaults to script's parent's parent.

    Returns:
        dict with keys: first_run, total_companies, stale_companies,
        active_applications, followup_needed, days_since_last_run,
        days_since_last_prospecting, stale_company_names, followup_company_names
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    root = Path(project_root)

    target_csv = root / "job-search" / "data" / "target-companies.csv"
    apps_csv = root / "job-tracker" / "data" / "applications.csv"
    run_log = root / "job-search" / "data" / "run-log.jsonl"

    has_targets = target_csv.exists() and target_csv.stat().st_size > 0
    has_apps = apps_csv.exists() and apps_csv.stat().st_size > 0

    if not has_targets and not has_apps:
        return {
            "first_run": True,
            "total_companies": 0,
            "stale_companies": 0,
            "active_applications": 0,
            "followup_needed": 0,
            "days_since_last_run": None,
            "days_since_last_prospecting": None,
            "stale_company_names": [],
            "followup_company_names": [],
        }

    today = datetime.now().date()
    stale_threshold = today - timedelta(days=7)
    followup_threshold = today - timedelta(days=7)

    total_companies = 0
    stale_companies = 0
    stale_names = []
    if has_targets:
        with open(target_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_companies += 1
                last_checked = row.get("last_checked", "")
                if last_checked:
                    try:
                        checked_date = datetime.fromisoformat(last_checked).date()
                        if checked_date < stale_threshold:
                            stale_companies += 1
                            stale_names.append(row.get("company", "Unknown"))
                    except (ValueError, TypeError):
                        stale_companies += 1
                        stale_names.append(row.get("company", "Unknown"))
                else:
                    stale_companies += 1
                    stale_names.append(row.get("company", "Unknown"))

    active_applications = 0
    followup_needed = 0
    followup_names = []
    active_statuses = {"researching", "applied", "interviewing"}
    if has_apps:
        with open(apps_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("status", "").strip().lower()
                if status in active_statuses:
                    active_applications += 1
                    last_contact = row.get("last_contact", "")
                    if last_contact:
                        try:
                            contact_date = datetime.fromisoformat(last_contact).date()
                            if contact_date < followup_threshold:
                                followup_needed += 1
                                followup_names.append(row.get("company", "Unknown"))
                        except (ValueError, TypeError):
                            pass

    days_since_last_run = None
    days_since_last_prospecting = None
    if run_log.exists():
        last_run_date = None
        last_prospecting_date = None
        with open(run_log, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_date = datetime.fromisoformat(entry.get("timestamp", "")).date()
                    last_run_date = entry_date
                    if entry.get("phase") == "prospecting" or entry.get("type") == "prospecting":
                        last_prospecting_date = entry_date
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
        if last_run_date:
            days_since_last_run = (today - last_run_date).days
        if last_prospecting_date:
            days_since_last_prospecting = (today - last_prospecting_date).days

    return {
        "first_run": False,
        "total_companies": total_companies,
        "stale_companies": stale_companies,
        "active_applications": active_applications,
        "followup_needed": followup_needed,
        "days_since_last_run": days_since_last_run,
        "days_since_last_prospecting": days_since_last_prospecting,
        "stale_company_names": stale_names[:10],
        "followup_company_names": followup_names[:10],
    }


def main():
    pretty = "--pretty" in sys.argv
    result = generate_briefing()

    if pretty:
        if result["first_run"]:
            print("This is your first run. No data yet.")
        else:
            print(f"Companies tracked: {result['total_companies']}")
            print(f"Stale (>7 days): {result['stale_companies']}")
            print(f"Active applications: {result['active_applications']}")
            print(f"Need follow-up: {result['followup_needed']}")
            if result["days_since_last_run"] is not None:
                print(f"Days since last run: {result['days_since_last_run']}")
            if result["days_since_last_prospecting"] is not None:
                print(f"Days since last prospecting: {result['days_since_last_prospecting']}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
