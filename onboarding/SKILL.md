---
name: onboarding
description: "Set up your personalized career-manager pipeline. Reads your resume, asks 3 targeted questions, then generates all config files so the pipeline is ready to run. Use when first setting up the pipeline or when your career goals change."
---

# Onboarding

Personalize the career-manager pipeline for a new user through a focused setup.

## When to Use

- First time setting up the pipeline after cloning
- Career goals, target roles, or compensation targets have changed
- Want to regenerate search queries or scoring criteria

## Flow

### Step 1: Check for Master CV

Check `cv-tailor/data/CV/Master CV/` for a `.docx` or `.pdf` file.

**If found:** Read the resume and extract:
- Work history (roles, companies, years, industries)
- Skills (technical and domain)
- Education and certifications
- Key accomplishments

Present a summary: "Here's what I gathered from your resume: [summary]. Anything to correct or add?"

**If not found:** Tell the user: "Drop your resume (.docx or .pdf) into `cv-tailor/data/CV/Master CV/` and re-run onboarding. The resume is needed to generate accurate search queries and scoring criteria."

### Step 2: Three Questions

Ask these three questions **one at a time, sequentially**:

1. "What roles are you targeting? Be specific about seniority (Associate, Manager, Director, VP) and industry. **Tip:** 'Senior Product Manager, fintech/accounting SaaS' will get you much better results than just 'Product Manager.'"
2. "What's your target salary range?"
3. "What's your willingness to travel? (e.g., fully remote, hybrid, open to relocation, X% travel)"

### Step 3: Generate Files

After the questions, generate all files. Warn before overwriting any existing files.

**IMPORTANT:** Before writing each file, you MUST read the existing file first (even if it's a template placeholder). Claude Code's Write tool requires reading before overwriting. If the file doesn't exist yet, create the parent directory with Bash (`mkdir -p`) first, then use Write.

**Never touch pipeline data files** (target-companies.csv, applications.csv, etc.).

#### File 1: `job-search/references/criteria.md`

Generate with this structure:

```
## Unique Value Proposition
[2-3 paragraphs: what makes this person uniquely valuable, derived from their background + non-obvious angle]

## Target Roles
[Role categories with descriptions, from question 1]

## Target Company Types
[3-8 career paths based on user's breadth. Each path has:]
### Path N: [Path Name]
- **Description:** [What kind of companies]
- **Example Companies:** [Named targets]
- **Role Types:** [Specific roles that fit]
- **Why You Fit:** [Connection to user's background]
- **Compensation Notes:** [Range based on user's target from question 2]

## Evaluation Framework
[10 personalized yes/no scoring dimensions, generated fresh]

### Group 1: Core Fit
1. [Dimension based on user's domain expertise]
2. [Dimension based on role alignment]
3. [Dimension based on influence/autonomy needs]
4. [Dimension based on culture/background fit]

### Group 2: Compensation & Career
5. [Dimension using user's stated comp target]
6. [Dimension about growth trajectory]
7. [Dimension about funding/stability]

### Group 3: Culture & Growth
8. [Dimension about problem excitement]
9. [Dimension about visibility/voice]
10. [Dimension about unique leverage]

## Scoring Guide
- 9-10 yes = Pursue aggressively
- 7-8 yes = Strong fit, apply and investigate
- 5-6 yes = Moderate fit, consider or watchlist
- <4 yes = Skip

**Handling unknowns:** When a dimension can't be assessed (e.g., comp data unavailable for a stealth startup), mark it as unknown rather than no. Score = (yes count / evaluated count) * 100 — unknowns don't count against the company. If fewer than 5 dimensions can be evaluated, flag the company as "needs_research" instead of assigning a score.

## Reference Background
[Condensed professional summary for Claude to reference during evaluation]
```

#### File 2: `job-search/references/background-context.md`

Generate with this structure:

```
## Personal Information
[Name, location, links — as provided]

## Technical Capabilities
[Skills organized by category]

## Project Portfolio
[If mentioned — key projects with impact]

## Professional Experience
[Roles, companies, years, key accomplishments]

## Education & Certifications
[Degrees, certifications, relevant training]

## Positioning Angles
[3-6 angles: the narratives that make this person compelling]

## Travel & Location Preferences
[From question 3 — willingness to travel, remote/hybrid/onsite preferences]
```

#### File 3: `job-search/data/search-config.json`

Generate valid JSON matching this schema:

```json
{
  "query_packs": {
    "<snake_case_key>": {
      "label": "Human-readable path name",
      "queries": ["6-12 job board search queries"]
    }
  },
  "role_include_patterns": ["15-25 regex patterns for target role titles"],
  "role_exclude_patterns": ["5-15 regex patterns for roles to reject"],
  "employer_exclude_patterns": ["patterns for employer types to skip"],
  "location_exclude_patterns": ["patterns for locations outside target geography"],
  "role_rescue_keywords": ["keywords that rescue borderline titles from exclusion"],
  "keywords": {
    "domain": ["industry terms"],
    "ai": ["AI/ML terms"],
    "tech": ["technical skills"]
  },
  "gold_companies": ["20-40 named target companies, lowercase"],
  "prospecting_paths": [
    {
      "path": 1,
      "name": "Career path name (matches criteria.md paths)",
      "search_queries": ["2-4 web search queries for finding new companies in this path"],
      "named_targets": ["5-15 specific company names to monitor"],
      "new_targets_goal": 2
    }
  ],
  "path_check_instructions": {
    "1": "Instructions for Claude when checking this path's companies for open roles"
  },
  "role_patterns": ["role title keywords for monitoring (e.g., product manager, solutions architect)"],
  "scoring": {
    "domain_keywords": {"keyword": 10, "another_keyword": 8},
    "ai_keywords": {"ai": 6, "llm": 8, "machine learning": 7},
    "role_keywords": {"target role title": 10, "another role": 8},
    "comp_indicators": {"series c": 7, "public": 8, "$150k": 10},
    "growth_indicators": {"series b": 8, "hypergrowth": 9, "raised": 6},
    "culture_keywords": {
      "remote_flexible": ["remote", "distributed", "flexible"],
      "innovation": ["innovation", "builder", "startup", "open source"],
      "technical": ["product-led", "engineer", "technical"]
    }
  }
}
```

**Query generation rules:**
- One query pack per career path from criteria.md (for JobSpy board scraping)
- One prospecting path per career path (for web-based company discovery)
- Each query: concrete search string (e.g., "product manager ai accounting software")
- Mix company-specific queries with generic ones
- All regex patterns must be valid Python regex. Do NOT use inline flags like `(?i)` — the pipeline adds case-insensitivity automatically
- `named_targets`: specific companies the user wants to track — derived from career paths in criteria.md
- `path_check_instructions`: tell Claude what role types to look for when visiting each path's company careers pages
- `role_patterns`: general role keywords used across all paths for monitoring

**Scoring keywords:** The `scoring` section powers the keyword-based company scorer. Generate weighted keywords (0-10 scale) based on the user's profile:
- `domain_keywords`: industry terms from their background. Higher weight = stronger signal of fit.
- `ai_keywords`: AI/ML terms relevant to their target roles.
- `role_keywords`: their target job titles with weights.
- `comp_indicators`: company traits that signal target compensation.
- `growth_indicators`: signals of company growth trajectory.
- `culture_keywords`: grouped keywords for culture fit scoring.

**Minimum viable output:**
- 3+ career paths / query packs / prospecting paths
- 3+ queries per pack
- 5+ named targets per prospecting path
- 5+ role include patterns
- 3+ role exclude patterns
- 10+ gold companies
- 10+ role patterns

#### File 4: `config.yaml`

Ask the user:
- CV base path (default: `cv-tailor/data/CV/`)
- Which integrations to enable (default: all disabled for new users):
  - **JobSpy** — scrapes job boards (Indeed, LinkedIn) for open roles
  - **Todoist** — syncs completed tasks to Todoist for tracking
  - **Gmail** — sends daily digest emails with new job discoveries

Use `config.yaml.example` as the template. Use defaults for fields not asked about.

### Step 4: Report

After generating all files, report:
- Which files were created/overwritten
- Summary of career paths generated
- Next steps: "Your pipeline is ready. Run the job-search skill to start discovering companies."

## Re-run Behavior

If the user has already run onboarding (files exist):
- Ask: "You already have a profile set up. What's changed?"
- Only regenerate files that need updating
- Never touch pipeline data (target-companies.csv, applications.csv)

## Boundaries

- This skill generates config files only — it does not run the pipeline
- It does not modify pipeline scripts (that's a code change, not onboarding)
- It does not create or modify the Master CV — user provides their own
