"""Tests for generate_briefing.py."""
import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from generate_briefing import generate_briefing


def _write_csv(path, header, rows):
    """Helper to write a CSV file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_first_run_no_files():
    """When no data files exist, returns first_run indicator."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = generate_briefing(project_root=tmpdir)
        assert result["first_run"] is True
        assert result["total_companies"] == 0
        assert result["active_applications"] == 0


def test_with_target_companies():
    """Counts total and stale companies from target CSV."""
    with tempfile.TemporaryDirectory() as tmpdir:
        header = ["company", "website", "last_checked", "validation_status"]
        today = datetime.now().date().isoformat()
        old = (datetime.now().date() - timedelta(days=10)).isoformat()
        rows = [
            {"company": "Fresh Co", "website": "fresh.com", "last_checked": today, "validation_status": "pass"},
            {"company": "Stale Co", "website": "stale.com", "last_checked": old, "validation_status": "pass"},
            {"company": "No Date", "website": "nodate.com", "last_checked": "", "validation_status": "pass"},
        ]
        _write_csv(os.path.join(tmpdir, "job-search", "data", "target-companies.csv"), header, rows)

        result = generate_briefing(project_root=tmpdir)
        assert result["first_run"] is False
        assert result["total_companies"] == 3
        assert result["stale_companies"] == 2
        assert "Stale Co" in result["stale_company_names"]


def test_with_applications():
    """Counts active apps and follow-ups from applications CSV."""
    with tempfile.TemporaryDirectory() as tmpdir:
        header = ["company", "role", "status", "last_contact", "priority"]
        old = (datetime.now().date() - timedelta(days=10)).isoformat()
        recent = (datetime.now().date() - timedelta(days=2)).isoformat()
        rows = [
            {"company": "Active Recent", "role": "PM", "status": "applied", "last_contact": recent, "priority": "1"},
            {"company": "Active Stale", "role": "Eng", "status": "interviewing", "last_contact": old, "priority": "1"},
            {"company": "Closed", "role": "PM", "status": "rejected", "last_contact": old, "priority": "2"},
        ]
        _write_csv(os.path.join(tmpdir, "job-tracker", "data", "applications.csv"), header, rows)

        result = generate_briefing(project_root=tmpdir)
        assert result["active_applications"] == 2
        assert result["followup_needed"] == 1
        assert "Active Stale" in result["followup_company_names"]


def test_empty_csv_is_first_run():
    """Empty CSV files (0 bytes) are treated as first run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "job-search", "data", "target-companies.csv")
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        Path(csv_path).touch()
        result = generate_briefing(project_root=tmpdir)
        assert result["first_run"] is True
