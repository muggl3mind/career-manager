---
name: onboarding
description: "Set up your personalized career-manager pipeline. Reads your resume, asks 1 question, then generates all config files so the pipeline is ready to run. Use when first setting up the pipeline or when your career goals change."
---

# Onboarding

Personalize the career-manager pipeline for a new user through a focused setup.

## When to Use

- First time setting up the pipeline after cloning
- Career goals, target roles, or compensation targets have changed
- Want to regenerate search queries or scoring criteria

## Flow

### Step 1: Get the Resume

Ask: "Where's your resume? Give me the file path (e.g., ~/Desktop/resume.docx)"

When the user provides a path:
1. Verify the file exists and is `.docx` or `.pdf`
2. Copy it to `cv-tailor/data/CV/Master CV/` (create directory if needed)
3. Read the resume and extract: work history, skills, industries, seniority, education, accomplishments

If the file doesn't exist or isn't a supported format, ask again with guidance.

**Do NOT ask the user to copy files manually.** You handle the copy.

### Step 2: One Question

Ask this single combined question:

"Based on your resume, I can see your background. I need three things your resume doesn't tell me:

1. **Target roles** - What roles are you going after? Be specific about seniority (Senior PM, Director of Engineering, Solutions Architect) and domain.
2. **Salary floor** - What's the minimum base salary you'd accept?
3. **Location** - Remote, hybrid, or onsite? Open to relocation?"

### Step 3: Confirm Profile

Present the full profile combining resume inference + user answers:

"Here's your profile:

**Background:** [inferred from resume - key roles, industries, years of experience, strongest skills]
**Target roles:** [from answer]
**Salary floor:** [from answer]
**Location:** [from answer]
**Career paths I'd search:** [3-8 paths derived from background + targets]

Anything you'd change?"

Wait for confirmation. If the user tweaks anything, update and re-confirm.

### Step 4: Generate Files

After confirmation, generate all files **silently**. No overwrite warnings. No "about to write..." messages. Just write them.

**IMPORTANT:** Before writing each file, read the existing file first (Write tool requirement). Do this silently. Do NOT tell the user you're reading before writing. Do NOT warn about overwriting.

**Never touch pipeline data files** (target-companies.csv, applications.csv, etc.).

#### File 1: `config.yaml`

Generate from `config.yaml.example` template with:
- `paths.cv_base` set to the directory where the user's resume was found (parent of the file they provided)
- All integrations set to `false`
- Email fields left as placeholders

#### File 2: `job-search/references/criteria.md`

Generate with this structure:

```
## Unique Value Proposition
[2-3 paragraphs: what makes this person uniquely valuable]

## Target Roles
[Role categories with descriptions]

## Target Company Types
[3-8 career paths. Each path has:]
### Path N: [Path Name]
- **Description:** [What kind of companies]
- **Example Companies:** [Named targets]
- **Role Types:** [Specific roles that fit]
- **Why You Fit:** [Connection to background]
- **Compensation Notes:** [Range based on salary floor]

## Evaluation Framework
[10 personalized yes/no scoring dimensions]

### Group 1: Core Fit (4 dimensions)
### Group 2: Compensation & Career (3 dimensions)
### Group 3: Culture & Growth (3 dimensions)

## Scoring Guide
- 9-10 yes = Pursue aggressively
- 7-8 yes = Strong fit, apply and investigate
- 5-6 yes = Moderate fit, consider or watchlist
- <4 yes = Skip

**Handling unknowns:** Mark as unknown rather than no. Score = (yes count / evaluated count) * 100. If fewer than 5 dimensions evaluable, flag as "needs_research".
```

#### File 3: `job-search/references/background-context.md`

Generate with this structure:

```
## Personal Information
## Technical Capabilities
## Project Portfolio
## Professional Experience
## Education & Certifications
## Positioning Angles
## Travel & Location Preferences
```

#### File 4: `job-search/data/search-config.json`

Generate valid JSON matching this schema (query_packs, role_include_patterns, role_exclude_patterns, employer_exclude_patterns, location_exclude_patterns, keywords, gold_companies, prospecting_paths, path_check_instructions, role_patterns, scoring).

**Query generation rules:**
- One query pack per career path (for JobSpy)
- One prospecting path per career path (for web discovery)
- All regex patterns must be valid Python regex, no inline flags like `(?i)`
- Minimum: 3+ paths, 3+ queries per pack, 5+ named targets per path, 10+ gold companies

### Step 5: Verify Setup

Run smoke test checks **inline** (do not ask the user to run a separate command):

1. Verify all 4 generated files exist and are non-empty
2. Verify `search-config.json` parses as valid JSON
3. Verify Python dependencies import (`yaml`, `requests`, `docx`, `openpyxl`)
4. Verify `config.yaml` reads correctly via `scripts/config_loader.py`

If all checks pass: "Setup complete."
If any check fails: report the specific issue and fix it.

### Step 6: Offer First Search

"Want me to find your first companies? I'll search across your career paths and score what I find."

If yes, hand off to job-search skill.

## Re-run Behavior

If the user has already run onboarding (files exist):
- Ask: "You already have a profile set up. What's changed?"
- Only regenerate files that need updating
- Never touch pipeline data (target-companies.csv, applications.csv)

## Boundaries

- This skill generates config files only. It does not run the pipeline.
- It does not modify pipeline scripts.
- It does not create or modify the Master CV content. It only copies the user's file.
