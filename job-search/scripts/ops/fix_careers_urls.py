#!/usr/bin/env python3
"""
Replace specific job listing URLs with stable company careers page URLs.

Fixes: LinkedIn job view links, Indeed viewjob links, Greenhouse job IDs,
Workday job IDs, and other ephemeral job posting URLs.
"""

import csv
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / 'data'
TARGET_CSV = DATA / 'target-companies.csv'

# Map: company name (lowercase) -> stable careers page URL
# Populated from your target-companies.csv as you build your pipeline.
# Add entries here for companies whose careers pages use ephemeral/session URLs.
STABLE_URLS = {}


def is_ephemeral(url: str) -> bool:
    """Check if a URL points to a specific job listing that will expire."""
    patterns = [
        'linkedin.com/jobs/view/',
        'indeed.com/viewjob',
        '/jobs/',  # Greenhouse/Lever specific job IDs (e.g. /jobs/7522587)
        'builtin.com/job/',
    ]
    # Only flag /jobs/NUMBERS patterns, not /jobs/ as a general careers listing
    if '/jobs/' in url:
        import re
        if re.search(r'/jobs/\d+', url) or re.search(r'/jobs/[a-f0-9-]{20,}', url):
            return True
    for p in ['linkedin.com/jobs/view/', 'indeed.com/viewjob', 'builtin.com/job/']:
        if p in url:
            return True
    return False


def main():
    with open(TARGET_CSV, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    fixed = 0
    for row in rows:
        url = row.get('careers_url', '')
        company = row.get('company', '').strip().lower()

        # Check if we have a stable URL mapping
        stable = STABLE_URLS.get(company)
        if stable and is_ephemeral(url):
            print(f"  FIX: {row['company']:<25} {url[:60]}... -> {stable}")
            row['careers_url'] = stable
            fixed += 1
        elif is_ephemeral(url) and not stable:
            print(f"  WARN: {row['company']:<25} ephemeral URL but no stable mapping: {url[:70]}")

    if fixed:
        with open(TARGET_CSV, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
        print(f"\nFixed {fixed} URLs in {TARGET_CSV.name}")
    else:
        print("No URLs needed fixing")


if __name__ == '__main__':
    main()
