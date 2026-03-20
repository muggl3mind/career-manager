#!/usr/bin/env python3
"""One-time migration: add date_applied column to applications.csv."""
import csv
from pathlib import Path

TRACKER_FILE = Path(__file__).resolve().parent.parent / 'data' / 'applications.csv'

APPLIED_STATUSES = {'applied', 'interviewing', 'offer', 'rejected', 'declined', 'closed'}

# Special cases: company -> date_applied override (from notes)
OVERRIDES = {
    'formulary': '2026-03-19',  # Notes: "3/19: Emailed HR with resume"
}

def migrate():
    with open(TRACKER_FILE, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    new_headers = [
        'company', 'role', 'job_url', 'status', 'date_added', 'date_applied',
        'last_contact', 'contact_name', 'contact_email', 'priority', 'notes'
    ]

    migrated = []
    for row in rows:
        company_key = row['company'].strip().lower()
        status = row.get('status', '').strip().lower()

        if company_key in OVERRIDES:
            date_applied = OVERRIDES[company_key]
        elif status in APPLIED_STATUSES:
            date_applied = row.get('date_added', '')
        else:
            date_applied = ''

        new_row = {
            'company': row.get('company', ''),
            'role': row.get('role', ''),
            'job_url': row.get('job_url', ''),
            'status': row.get('status', ''),
            'date_added': row.get('date_added', ''),
            'date_applied': date_applied,
            'last_contact': row.get('last_contact', ''),
            'contact_name': row.get('contact_name', ''),
            'contact_email': row.get('contact_email', ''),
            'priority': row.get('priority', ''),
            'notes': row.get('notes', ''),
        }
        migrated.append(new_row)

    # Print diff
    for old, new in zip(rows, migrated):
        company = new['company']
        da = new['date_applied']
        if da:
            src = 'OVERRIDE' if company.strip().lower() in OVERRIDES else 'copied'
            print(f"  {company}: date_applied={da} ({src})")
        else:
            print(f"  {company}: date_applied=(empty) — status={new['status']}")

    with open(TRACKER_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_headers)
        writer.writeheader()
        writer.writerows(migrated)

    print(f"\nMigrated {len(migrated)} rows. New column: date_applied")

if __name__ == '__main__':
    migrate()
