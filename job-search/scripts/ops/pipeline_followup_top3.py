#!/usr/bin/env python3
from __future__ import annotations
import csv
from datetime import datetime
from pathlib import Path

# applications.csv moved to sibling job-tracker skill
apps = Path(__file__).resolve().parents[2].parent / 'job-tracker' / 'data' / 'applications.csv'
rows=[]
if apps.exists():
    with apps.open() as f:
        rows=list(csv.DictReader(f))

cands=[r for r in rows if (r.get('status','').lower() in {'applied','interviewing'})]
def days(s):
    try: return (datetime.now()-datetime.strptime(s,'%Y-%m-%d')).days
    except: return -1
cands.sort(key=lambda r: days(r.get('last_contact') or r.get('date_added') or '1970-01-01'), reverse=True)
print('PIPELINE_FOLLOWUP_TOP3')
for r in cands[:3]:
    print(f"- {r.get('company')} | {r.get('role')} | last_contact={r.get('last_contact')}")
