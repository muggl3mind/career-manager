---
name: job-tracker
description: "Track job applications, manage follow-ups, and generate progress reports. Use when adding applications, updating status, checking pipeline, or finding stale applications needing follow-up."
---

# Job Application Tracker

Manage the job hunt pipeline. All data in `data/applications.csv`.

## Commands

Parse user input to determine which command to run:

### `add [company] [role]`
Add new application. Default: status=researching, priority=2. Override with `-p 1|2|3`.

### `update [company] [status]`
Change status. Valid: `researching` → `applied` → `interviewing` → `offer` | `rejected` | `declined`
Auto-updates `last_contact` to today.

### `list`
Show active applications grouped by priority (excludes offer/rejected/declined).

### `followup`
Show applications needing follow-up (7+ days since last contact).

### `report`
Weekly pipeline summary: counts, activity, what needs attention.

### `notes [company] [text]`
Add timestamped note to application.

### `contact [company] [name] [email]`
Add or update contact info.

### `priority [company] [1|2|3]`
Change priority level.

### `archive`
Show all applications including closed ones.

## Implementation

Use `scripts/tracker_commands.py` for all CSV operations. Import and call functions directly — don't rewrite CSV logic.

## CSV Schema

| Column | Description |
|---|---|
| company | Company name |
| role | Job title |
| job_url | Link to posting |
| status | Current status |
| date_added | When first added (YYYY-MM-DD) |
| last_contact | Last communication date |
| contact_name | Hiring manager/recruiter |
| contact_email | Contact email |
| priority | 1=high, 2=standard, 3=backlog |
| notes | Timestamped notes |

## Rules

- **NEVER edit `applications.csv` directly.** Always use `scripts/tracker_commands.py` functions (`add_application`, `update_status`, `add_note`, `add_contact`). Direct CSV edits bypass Todoist sync and validation.
- After any tracker modification, sync to Todoist using `scripts/todoist_sync.py` (skipped automatically if `integrations.todoist_enabled: false` in `config.yaml`).
- Read CSV before any operation
- Write CSV after any modification
- Preserve all existing data
- Use ISO date format (YYYY-MM-DD)

## Integration

- **company-research** → researches target companies and can feed tracking decisions
- **cv-tailor** → prepares materials before applying
- **company-research** → culture + company dossier before applying

## Reference Files

- `data/applications.csv` — Main data store
- `scripts/tracker_commands.py` — Python implementation
- `scripts/add_to_tracker.py` — Batch add from target companies
- `references/example-output.md` — Output format examples

## Error Handling
- If company is not found on update operations, return explicit "not found" and suggest `list`.
- If priority/status is invalid, reject write and return allowed values.
- If CSV is malformed, stop write operations and require repair before proceeding.
