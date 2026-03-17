#!/usr/bin/env python3
"""
Job Tracker Commands
Implementation of job-tracker skill commands
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

# Todoist sync — best-effort, never blocks tracker writes
def _sync_todoist(description: str):
    try:
        from todoist_sync import sync_completed_work
        return sync_completed_work(description)
    except Exception:
        return {"action": "sync_failed", "task_content": description}

# Paths
SKILL_DIR = Path(__file__).resolve().parent.parent  # job-tracker/
DATA_DIR = SKILL_DIR / 'data'
TRACKER_FILE = DATA_DIR / 'applications.csv'
# target-companies.csv stays in sibling job-search skill
JOB_SEARCH_DIR = SKILL_DIR.parent / 'job-search'
TARGET_COMPANIES_FILE = JOB_SEARCH_DIR / 'data' / 'target-companies.csv'

# CSV headers
CSV_HEADERS = [
    'company', 'role', 'job_url', 'status', 'date_added', 'last_contact',
    'contact_name', 'contact_email', 'priority', 'notes'
]


def read_tracker():
    """Read applications.csv and return list of dicts."""
    applications = []
    if TRACKER_FILE.exists():
        with open(TRACKER_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Filter out None keys (extra columns from malformed CSV)
                cleaned_row = {k: v for k, v in row.items() if k is not None and k in CSV_HEADERS}
                # Ensure all expected fields exist
                for header in CSV_HEADERS:
                    if header not in cleaned_row:
                        cleaned_row[header] = ''
                applications.append(cleaned_row)
    return applications


def write_tracker(applications):
    """Write applications list back to CSV."""
    # Clean applications to only include valid fields
    cleaned = []
    for app in applications:
        cleaned_app = {key: app.get(key, '') for key in CSV_HEADERS}
        cleaned.append(cleaned_app)
    
    with open(TRACKER_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(cleaned)


def find_company(applications, company_name):
    """Find company in applications (case-insensitive)."""
    company_lower = company_name.lower().strip()
    for i, app in enumerate(applications):
        if app['company'].lower().strip() == company_lower:
            return i, app
    return None, None


def get_company_data_from_research(company_name):
    """Get additional data about company from target-companies.csv."""
    if not TARGET_COMPANIES_FILE.exists():
        return {}
    
    company_lower = company_name.lower().strip()
    with open(TARGET_COMPANIES_FILE, 'r') as f:
        for row in csv.DictReader(f):
            if row['company'].lower().strip() == company_lower:
                return {
                    'job_url': row.get('careers_url', ''),
                    'fit_score': row.get('fit_score', ''),
                    'tech_signals': row.get('tech_signals', ''),
                    'stage': row.get('stage', ''),
                    'notes_from_research': row.get('notes', '')
                }
    return {}


def add_application(company, role, priority=2, job_url=''):
    """Add a new application to the tracker."""
    applications = read_tracker()
    
    # Check if already exists
    idx, existing = find_company(applications, company)
    if existing:
        return {
            'success': False,
            'message': f"❌ {company} is already in your tracker (status: {existing['status']})"
        }
    
    # Get additional data from research if available
    research_data = get_company_data_from_research(company)
    
    # Build new application
    today = datetime.now().strftime('%Y-%m-%d')
    new_app = {
        'company': company,
        'role': role,
        'job_url': job_url or research_data.get('job_url', ''),
        'status': 'researching',
        'date_added': today,
        'last_contact': '',
        'contact_name': '',
        'contact_email': '',
        'priority': str(priority),
        'notes': research_data.get('notes_from_research', '')[:100] if research_data.get('notes_from_research') else ''
    }
    
    applications.append(new_app)
    write_tracker(applications)
    
    # Sync to Todoist
    todoist_result = _sync_todoist(f"Added {company} - {role} to job tracker")

    # Build response
    response = {
        'success': True,
        'message': f"✓ Added {company} - {role} to tracker",
        'company': company,
        'role': role,
        'priority': priority,
        'research_data': research_data,
        'todoist': todoist_result,
    }

    return response


def update_status(company, new_status):
    """Update the status of an existing application."""
    valid_statuses = ['researching', 'applied', 'interviewing', 'offer', 'rejected', 'declined']
    
    if new_status.lower() not in valid_statuses:
        return {
            'success': False,
            'message': f"❌ Invalid status: {new_status}. Valid: {', '.join(valid_statuses)}"
        }
    
    applications = read_tracker()
    idx, app = find_company(applications, company)
    
    if app is None:
        return {
            'success': False,
            'message': f"❌ {company} not found in tracker"
        }
    
    old_status = app['status']
    app['status'] = new_status.lower()
    app['last_contact'] = datetime.now().strftime('%Y-%m-%d')
    
    applications[idx] = app
    write_tracker(applications)

    # Sync to Todoist
    todoist_result = _sync_todoist(f"Updated {company}: {old_status} → {new_status}")

    return {
        'success': True,
        'message': f"✓ Updated {company}: {old_status} → {new_status}",
        'company': company,
        'old_status': old_status,
        'new_status': new_status,
        'todoist': todoist_result,
    }


def add_contact(company, contact_name, contact_email=''):
    """Add or update contact information."""
    applications = read_tracker()
    idx, app = find_company(applications, company)
    
    if app is None:
        return {
            'success': False,
            'message': f"❌ {company} not found in tracker"
        }
    
    app['contact_name'] = contact_name
    if contact_email:
        app['contact_email'] = contact_email
    app['last_contact'] = datetime.now().strftime('%Y-%m-%d')
    
    applications[idx] = app
    write_tracker(applications)
    
    return {
        'success': True,
        'message': f"✓ Added contact for {company}: {contact_name}",
        'company': company,
        'contact_name': contact_name
    }


def add_note(company, note_text):
    """Add a note to an application."""
    applications = read_tracker()
    idx, app = find_company(applications, company)
    
    if app is None:
        return {
            'success': False,
            'message': f"❌ {company} not found in tracker"
        }
    
    today = datetime.now().strftime('%m/%d')
    existing_notes = app.get('notes', '')
    new_note = f"[{today}] {note_text}"
    
    if existing_notes:
        app['notes'] = f"{existing_notes}; {new_note}"
    else:
        app['notes'] = new_note
    
    applications[idx] = app
    write_tracker(applications)
    
    return {
        'success': True,
        'message': f"✓ Added note to {company}",
        'company': company
    }


def list_applications(include_closed=False):
    """List all applications."""
    applications = read_tracker()
    
    if not include_closed:
        applications = [app for app in applications 
                       if app['status'] not in ['offer', 'rejected', 'declined']]
    
    # Group by priority
    by_priority = {1: [], 2: [], 3: []}
    for app in applications:
        priority_str = app.get('priority', '2').strip()
        # Handle legacy text priorities gracefully
        text_map = {'high': 1, 'medium': 2, 'low': 3, 'p1': 1, 'p2': 2, 'p3': 3}
        if not priority_str:
            priority = 2
        elif priority_str.isdigit():
            priority = int(priority_str)
        else:
            priority = text_map.get(priority_str.lower(), 2)
        if priority not in by_priority:
            priority = 2  # Default if invalid
        by_priority[priority].append(app)
    
    return {
        'success': True,
        'applications': applications,
        'by_priority': by_priority,
        'total': len(applications)
    }


def find_stale_applications(days_threshold=7):
    """Find applications needing follow-up."""
    applications = read_tracker()
    today = datetime.now()
    stale = []
    
    for app in applications:
        # Skip closed applications
        if app['status'] in ['offer', 'rejected', 'declined']:
            continue
        
        # Get last activity date
        last_contact = app.get('last_contact', '')
        date_added = app.get('date_added', '')
        
        activity_date = last_contact if last_contact else date_added
        if not activity_date:
            continue
        
        try:
            activity_dt = datetime.strptime(activity_date, '%Y-%m-%d')
            days_since = (today - activity_dt).days
            
            if days_since >= days_threshold:
                stale.append({
                    'company': app['company'],
                    'role': app['role'],
                    'status': app['status'],
                    'days_since': days_since,
                    'last_contact': last_contact or date_added,
                    'contact_name': app.get('contact_name', ''),
                    'contact_email': app.get('contact_email', '')
                })
        except:
            pass
    
    # Sort by days since (most stale first)
    stale.sort(key=lambda x: x['days_since'], reverse=True)
    
    return {
        'success': True,
        'stale_applications': stale,
        'count': len(stale)
    }


if __name__ == '__main__':
    # CLI interface for testing
    if len(sys.argv) < 2:
        print("Usage: tracker_commands.py <command> [args]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'add' and len(sys.argv) >= 4:
        company = sys.argv[2]
        role = sys.argv[3]
        priority = int(sys.argv[4]) if len(sys.argv) > 4 else 2
        result = add_application(company, role, priority)
        print(result['message'])
    
    elif command == 'update' and len(sys.argv) >= 4:
        company = sys.argv[2]
        status = sys.argv[3]
        result = update_status(company, status)
        print(result['message'])
    
    elif command == 'list':
        result = list_applications()
        print(f"Total: {result['total']} active applications")
        for priority in [1, 2, 3]:
            apps = result['by_priority'][priority]
            if apps:
                print(f"\nPriority {priority}:")
                for app in apps:
                    print(f"  - {app['company']} - {app['role']} [{app['status']}]")
    
    elif command == 'followup':
        result = find_stale_applications()
        print(f"Found {result['count']} applications needing follow-up:")
        for app in result['stale_applications']:
            print(f"  ⚠️  {app['company']} - {app['days_since']} days since last contact")
    
    else:
        print(f"Unknown command: {command}")
