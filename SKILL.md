---
name: career-manager
description: "Orchestrate the complete career-manager system across job-search, company-research, job-tracker, and cv-tailor. Use when coordinating multi-step job hunt workflows, routing requests to the right sub-skill, and enforcing shared data ownership boundaries."
---

# Career Manager Orchestrator

> This is intentionally a **router skill** (thin coordinator), not a heavy execution skill. Execution lives in sub-skills below.

## Before Any Workflow: Status Briefing

Before starting any workflow, run the briefing script to understand current state:

```bash
uv run python3 scripts/generate_briefing.py
```

Read the JSON output and present a natural-language summary to the user:

- **First run** (first_run=true): "This is your first run. I'll search across your career paths and probably find 15-25 companies. Should take about 20 minutes."
- **Ongoing** (first_run=false): "You have [total_companies] companies tracked, [stale_companies] are stale. [active_applications] active applications, [followup_needed] need follow-up. [Context-appropriate time estimate]."

Use the briefing to inform which workflow to suggest.

## Route by Intent

- **"What should I do today?" / "what's my status?" / "briefing"** - Run briefing, then suggest highest-priority action: follow-ups first, then monitor if stale companies exist, then prospecting if >7 days since last.
- **Target list scoring / hygiene / dedupe / stale checks / broken links** - `job-search`
- **"Run job search" / "find companies" / "run the pipeline"** - `job-search`
- **Single company deep research dossier** - `company-research`
- **"Pursue [company]" / "research and apply to [company]"** - `company-research` then `cv-tailor` then `job-tracker`
- **Application pipeline CRUD + follow-up reporting** - `job-tracker`
- **First-time setup / profile update / regenerate config** - `onboarding`
- **"Tailor my CV" / "apply to [role]"** - `cv-tailor`

## Cross-Skill Flow

After any skill completes, suggest the logical next action (one suggestion, not a chain):

| Skill completes | Suggest |
|---|---|
| Onboarding | "Want me to find your first companies?" |
| Job search phase 3 | "Top 3 are [names]. Want me to research them?" |
| Company research says PURSUE | "Want me to tailor your CV for [role] at [company]?" |
| CV tailor produces artifacts | "Want me to add this to your tracker?" |
| Job tracker shows stale follow-ups | "Want me to draft follow-up text for these?" |

These are suggestions. The user can always decline.

## Source of Truth

- `job-search/data/target-companies.csv`
- `job-tracker/data/applications.csv`

## Boundaries

- Keep non-career work out of this skill.
- Use `company-research` for one-company analysis, not bulk pipeline operations.
- Use `job-tracker` for application status operations, not market/company research.

## Error Handling

- If a sub-skill path or file is missing, stop and report the missing dependency.
- If requested action spans multiple skills, execute sequentially (don't ask for permission between each step unless a decision is needed).
- If data sources conflict, prefer canonical owners (`job-search` for target companies, `job-tracker` for applications) and log the discrepancy.

## Reference

- `references/apply-workflow.md` - end-to-end research, tailor, apply, track, follow-up flow
