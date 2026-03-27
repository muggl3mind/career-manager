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

"Based on your resume, I can see your background. I need four things your resume doesn't tell me:

1. **Target roles** - What roles are you going after? Be specific about seniority (Senior PM, Director of Engineering, Solutions Architect) and domain.
2. **Salary floor** - What's the minimum base salary you'd accept?
3. **Location** - Remote, hybrid, or onsite? Open to relocation?
4. **Job markets** - Which countries should I search for jobs in? (Default: United States)"

### Step 3: Confirm Profile

Present the full profile combining resume inference + user answers:

"Here's your profile:

**Background:** [inferred from resume - key roles, industries, years of experience, strongest skills]
**Target roles:** [from answer]
**Salary floor:** [from answer]
**Location:** [from answer]
**Career paths I'd search:**

Derive paths in two phases:

1. **From resume:** For each sector or employer type the user spent 2+ years in, derive a career path. Group similar employers (e.g., multiple Big 4 firms = one "Professional Services / Advisory" path, not four). If no employer meets the 2-year threshold, use the user's longest-tenured roles regardless.
2. **From targets:** Add paths from the user's stated target roles that aren't already covered by Phase 1.

Merge overlapping paths. List Phase 1 paths first (longest tenure first), then Phase 2 paths. Final count: 3-8 paths.

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
- **Example Companies:** [2-3 well-known examples for context, not monitored]
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

Generate valid JSON matching this exact structure. **Pay close attention to types. `query_packs` and `path_check_instructions` are dicts, not lists.**

```json
{
  "search_locations": ["United States"],
  "query_packs": {
    "<snake_case_path_key>": {
      "label": "Human-Readable Path Name",
      "queries": ["search query 1", "search query 2", "..."],
      "locations": ["Remote", "United States"],
      "job_type": "fulltime"
    }
  },
  "role_include_patterns": ["regex_pattern", "..."],
  "role_exclude_patterns": ["regex_pattern", "..."],
  "employer_exclude_patterns": ["regex_pattern", "..."],
  "location_exclude_patterns": ["regex_pattern", "..."],
  "keywords": {
    "domain": ["keyword", "..."],
    "ai": ["keyword", "..."],
    "tech": ["keyword", "..."]
  },
  "path_check_instructions": {
    "1": "Multi-sentence discovery strategy for path 1...",
    "2": "Multi-sentence discovery strategy for path 2..."
  },
  "role_patterns": ["human-readable role title", "..."],
  "scoring": {
    "domain_keywords": {"keyword": 8},
    "ai_keywords": {"keyword": 6},
    "role_keywords": {"keyword": 7},
    "comp_indicators": {"keyword": 5},
    "growth_indicators": {"keyword": 4}
  },
  "path_aliases": {
    "fuzzy variant": "Exact Query Pack Label",
    "another variant": "Exact Query Pack Label"
  },
  "display_groups": {
    "Group Name": ["Query Pack Label 1", "Query Pack Label 2"],
    "Another Group": ["Query Pack Label 3"]
  }
}
```

**Critical rules:**
- `query_packs` is a **dict keyed by snake_case name**, NOT a list. Each value has `label`, `queries`, `locations`, `job_type`
- `path_check_instructions` is a **dict keyed by path number as string** ("1", "2", etc.), NOT a single string
- One query pack per career path (for JobSpy)
- All regex patterns must be valid Python regex, no inline flags like `(?i)`
- Minimum: 3+ paths, 3+ queries per pack
- `display_groups` groups related query pack labels into 3-4 dashboard display categories. Each label must match a query pack's `label` field exactly. Paths not mapped go to "Other"

**Search locations:**
- `search_locations` is the user's answer to "Which countries should I search for jobs in?"
- Default: `["United States"]` if the user doesn't specify
- If user says "Europe", expand to specific countries: Ireland, United Kingdom, Germany, Netherlands, France
- Populate each query pack's `locations` field from `search_locations` (plus "Remote")
- Auto-generate `location_exclude_patterns` to exclude countries NOT in `search_locations`. Do not add exclude patterns for countries the user wants to search in.

**Scoring keywords:** Each scoring dict maps keyword strings to integer weights. Higher weights = stronger signal for that category. Generate weights based on how central each term is to the user's target roles.

**Path aliases:** Map fuzzy LLM path variants to canonical query_pack labels. The LLM sometimes returns shortened or rephrased path names during evaluation. This map catches common variants so they normalize correctly. Generate 3-5 aliases per career path based on likely LLM rephrasings. Keys are lowercase variants, values are exact query_pack labels.

**Path check instructions:** Generate 3-4 sentence discovery strategies per path. Each instruction must include:
- What signals indicate a good fit for this path
- What to look for on careers pages
- What disqualifies a company
- Location requirements (reference `search_locations`)

See `onboarding/references/example-output.md` for a complete working example.

### Step 5: Verify Setup

Run smoke test checks **inline** (do not ask the user to run a separate command):

1. Verify all 4 generated files exist and are non-empty
2. Run `uv run python3 scripts/smoke_test.py` and verify all checks pass (this validates search-config schema, query_packs is a dict, path_check_instructions is a dict, dependencies, and config.yaml)

If all checks pass: "Setup complete."
If any check fails: report the specific issue and fix it.

### Step 6: Start First Search

Automatically hand off to the job-search skill and run the full pipeline. Do not ask the user for confirmation — they just completed setup, so the next step is always discovery.

## Re-run Behavior

If the user has already run onboarding (files exist):
- Ask: "You already have a profile set up. What's changed?"
- Only regenerate files that need updating
- Never touch pipeline data (target-companies.csv, applications.csv)

## Boundaries

- This skill generates config files only. It does not run the pipeline.
- It does not modify pipeline scripts.
- It does not create or modify the Master CV content. It only copies the user's file.
