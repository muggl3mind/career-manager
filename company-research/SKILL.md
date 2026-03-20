---
name: company-research
description: "Research a company and return a consistent dossier: executives + LinkedIn profiles, Glassdoor reviews, financial health, and latest news. Use when evaluating whether a role is worth pursuing."
---

# Company Research

Generate a consistent company dossier for job search decision-making.

## Trigger

User says: "research [company]", "look into [company]", "what do you know about [company]", or agent identifies a company worth investigating.

## Output Format (ALWAYS this structure)

### 1) Overview
- Name, website, industry
- Size (employees, include numeric estimate/range), stage (startup/public/PE-backed)
- HQ location, remote policy
- Founded, key milestones
- Executives & key contacts table:

| Name | Title | LinkedIn | Notes |
|------|-------|----------|-------|
| CEO | ... | linkedin.com/in/... | Background |
| CTO/VP Eng | ... | ... | ... |
| Hiring Manager (if identifiable) | ... | ... | ... |

- Role-relevant outreach targets (ALWAYS include 2-5 people when available):

| Name | Title | Why relevant to this role | LinkedIn |
|------|-------|---------------------------|----------|
| ... | ... | Hiring owner / cross-functional partner / team lead | ... |

### 2) Signals
- Glassdoor/employee review snapshot (rating, pros/cons themes, CEO approval)
- Financial health (funding, profitability signals, layoffs/hiring freezes)
- Latest news table (last 90 days):

| Date | Headline | Source | Relevance |
|------|----------|--------|-----------|
| ... | ... | ... | High/Med/Low |

### 3) Fit
- Match to target roles (Y/N + why)
- Comp range estimate
- Culture fit signals
- Growth trajectory
- Recommendation: PURSUE / RESEARCH MORE / PASS

### 4) Risks
- Top red flags and uncertainty notes
- Data freshness concerns
- Validation gaps (what to verify before applying)

## Data Sources (in order)
1. web_search (company name + "glassdoor reviews")
2. web_search (company name + "funding crunchbase")
3. web_search (company name + "news" last 90 days)
4. web_search (company name + "executives leadership team")
5. Company careers page (for role details)
6. target-companies.csv (for existing research)

## After Research

These steps happen automatically after every dossier. Do not ask the user.

1. Save dossier to `company-research/dossiers/[company].md`
2. Update `job-search/data/target-companies.csv` with findings (fit_score, fit_rationale, industry, size, stage, recent_funding, tech_signals)
3. If recommendation is PURSUE, suggest: "Want me to tailor your CV for [role] at [company]?"
4. If recommendation is RESEARCH MORE, suggest: "Want me to dig deeper on [specific gap]?"
5. If recommendation is PASS, no suggestion needed.

## Rules
- ALWAYS use this exact structure — no freestyling
- Include sources for every section
- Flag when data is uncertain or outdated
- If Glassdoor has no reviews, say so (don't skip the section)
- Financial health for private companies = funding + signals (don't guess revenue)

## Error Handling
- If one source is unavailable (e.g., Glassdoor), continue and mark section as unavailable with source note.
- If conflicting data appears, report both values and recommend verification step.
- If company has minimal public footprint, return best-effort dossier with explicit confidence labels.
