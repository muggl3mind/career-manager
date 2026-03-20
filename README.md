# Career Manager Pipeline

An AI-assisted career management system built as a set of Claude Code skills. Orchestrates job discovery, company research, application tracking, and resume tailoring through a pipeline of Python scripts and Claude Code interactions.

> **Note:** This is a personal productivity tool shared for inspiration and adaptation, not a production service.

## Demo

> **Watch:** Short walkthrough of the full pipeline from onboarding to dashboard.

<!-- TODO: Replace with actual video embed/link after recording -->
<!-- ![Demo Video](assets/demo/demo-thumbnail.png) -->

[Video coming soon]

## Getting Started

1. Install [Claude Code](https://claude.ai/code)
2. Install Python 3.13+ and [uv](https://docs.astral.sh/uv/)
3. Paste this repo's URL into Claude Code and say: **"Set up the requirements and start onboarding"**

---

## Prerequisites

- **Python 3.13+** — [Download Python](https://www.python.org/downloads/)
- **uv** — Python package manager. Install: `curl -LsSf https://astral.sh/uv/install.sh | sh` ([full instructions](https://docs.astral.sh/uv/getting-started/installation/))
- **Claude Code** — the AI CLI that runs this pipeline. Requires an [Anthropic API key](https://console.anthropic.com/). Install and get started:
  ```bash
  npm install -g @anthropic-ai/claude-code
  ```
  Full setup guide: [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code/overview)
- (Optional) **[python-jobspy](https://github.com/Bunsly/JobSpy)** — scrapes job boards (LinkedIn, Indeed) for open roles. Included in `requirements.txt` but may not always work reliably as it depends on job board access. The pipeline works fine without it — Claude discovers companies through web search instead. You can disable it in `config.yaml` with `jobspy_enabled: false`.
## Setup

1. Clone this repo and install dependencies:

   ```bash
   git clone https://github.com/[YOUR_GITHUB]/[YOUR_PROJECT].git
   cd career-manager
   uv venv
   uv pip install -r requirements.txt
   ```

   > **Note:** python-jobspy may downgrade numpy. This is expected and does not affect the pipeline.

2. Configure Claude Code permissions: the repo includes a working `.claude/settings.local.json` with default permissions already set. You can customize it as needed to add or remove allowed domains.

3. Start Claude Code in this directory:

   ```bash
   cd career-manager
   claude
   ```

   This opens an interactive chat with Claude in your terminal. You'll use this to run the pipeline.

## Onboarding

Once Claude Code is running, personalize the pipeline:

1. Drop your resume and cover letter (`.docx` or `.pdf`) into `cv-tailor/data/CV/Master CV/`. The onboarding skill reads these to pre-fill your profile, so you'll answer fewer questions. Without them, you'll go through the full interview instead.
2. Tell Claude: *"Run the onboarding skill"* — it will interview you about your background, target roles, compensation, and preferences
3. It generates all personalized config files:
   - `config.yaml` — paths, integration settings, email addresses
   - `job-search/references/criteria.md` — your career paths and scoring rubric
   - `job-search/references/background-context.md` — your professional summary
   - `job-search/data/search-config.json` — job board search queries and filters
4. Run the smoke test to verify everything is set up correctly:

   ```bash
   uv run python3 scripts/smoke_test.py
   ```

   This checks dependencies, config files, and module imports. Fix any failures before running the pipeline.

5. Your pipeline is ready to run

> **Manual setup:** If you prefer to skip onboarding, copy `config.yaml.example` to `config.yaml` and edit the reference files manually.

## How to Use

This pipeline runs through [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — a CLI tool where you chat with Claude in your terminal. Open Claude Code in this project's directory and just tell it what you want in plain English:

| What you want | What to say |
|---------------|-------------|
| Set up the pipeline | *"Run the onboarding skill"* |
| Find new companies | *"Run the job search pipeline"* |
| Research a specific company | *"Research Stripe for me"* |
| Tailor your resume for a role | *"Tailor my CV for the Product Manager role at Stripe"* |
| Track an application | *"Add Stripe PM to my tracker"* |
| Check what needs follow-up | *"Show me applications that need follow-up"* |
| Run a health check | *"Run the pipeline health check"* |

You don't need to memorize commands. Just describe what you need and Claude will route to the right skill.

## Skills Overview

| Skill | Purpose | Entry Point |
|-------|---------|-------------|
| **job-search** | Discover companies, score against 8 career paths, maintain target list | `job-search/SKILL.md` |
| **job-tracker** | Track application status, follow-ups, pipeline reports | `job-tracker/SKILL.md` |
| **company-research** | Deep dossier on a single company (overview, signals, fit, risks) | `company-research/SKILL.md` |
| **cv-tailor** | Generate tailored resume + cover letter for a specific role | `cv-tailor/SKILL.md` |
| **evals** | Pipeline quality assurance (code review, runtime verify, health monitor) | `evals/SKILL.md` |
| **onboarding** | Personalized pipeline setup via guided interview | `onboarding/SKILL.md` |

## Pipeline Flow

### Job Search (how companies are discovered)

When you say "run the job search pipeline", this happens:

```
Phase 1 — Python exports (automated)
  ├── JobSpy scrape: searches job boards (LinkedIn, Indeed) for matching listings
  ├── Monitor export: identifies which known companies haven't been checked recently
  └── Prospecting export: prepares context for finding new companies

Agent work — Claude does the research
  ├── Monitor: visits careers pages of known target companies, looks for new roles
  ├── Evaluate: scores JobSpy results against your criteria.md rubric
  └── Prospect: searches the web for new companies + checks named targets

Phase 2 — Python merges everything into target-companies.csv

Phase 3 — Generates ranked action list (action-list.csv)
```

### End-to-end career workflow

```
1. Discover companies (job-search)
2. Score & rank them (job-search)
3. Deep-dive a specific company (company-research)
4. Tailor your CV for a role (cv-tailor)
5. Track your application (job-tracker)
6. Follow up on stale applications (job-tracker)
```

Each skill has its own `SKILL.md` with detailed usage instructions.

## Sample Data

See `examples/` for anonymized sample CSVs that demonstrate the data schema.

## Customization

- **Career paths**: Edit `job-search/references/criteria.md` to define your own target industries and scoring rubric
- **Scoring weights**: Adjust the 10-dimension rubric in `job-search/references/criteria.md`
- **Email templates**: Customize templates in `job-search/templates/`

## Optional Integrations

These integrations are disabled by default. Enable them in `config.yaml` when you're ready.

### Gmail (email digests)

Send yourself daily email digests with new job discoveries.

1. Set up Gmail OAuth credentials ([guide](https://developers.google.com/gmail/api/quickstart/python))
2. Save token as `.credentials/gmail-token.pickle`
3. Set `gmail_enabled: true` in `config.yaml`
4. Add your email addresses under `email:` in `config.yaml`

### Todoist (task sync)

Sync completed applications to Todoist for tracking.

1. Get an API token from [Todoist Integrations](https://todoist.com/app/settings/integrations)
2. Save as `.credentials/todoist-token.json`: `{"token": "your-token"}`
3. Set `todoist_enabled: true` in `config.yaml`

### Tavily (job posting links)

Get direct links to specific job postings instead of generic careers pages. Free tier: 1,000 credits/month.

1. Sign up at [tavily.com](https://tavily.com) and get an API key
2. Save as `.credentials/tavily-token.json`: `{"api_key": "tvly-your-key"}`
3. Set `tavily_enabled: true` in `config.yaml`

## Architecture

Each skill owns its data and exposes clear interfaces:

- `job-search/data/target-companies.csv` — Source of truth for all discovered companies
- `job-tracker/data/applications.csv` — Source of truth for application pipeline
- `company-research/dossiers/*.md` — Deep research output
- `cv-tailor/data/CV/[company]/` — Per-company tailored materials

See `references/ownership-matrix.md` for the full ownership map.
