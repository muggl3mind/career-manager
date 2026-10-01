# Security

Career Manager is a personal productivity tool that runs on your machine and sends your career data to an AI provider. This document states what it defends against, how, and what it does not.

## What's at stake

- Your resume and career history (`cv-tailor/data/`, `config.yaml`, `cv-tailor/config/user-profile.yaml`)
- Your search criteria and results (`job-search/data/`, `job-tracker/data/`, `company-research/dossiers/`)
- Optional credentials in `.credentials/` (Tavily, Gmail, Todoist) — all gitignored

## Threats and defenses

### 1. Prompt injection from fetched web content

Agents read job postings and careers pages written by strangers. Hostile text could try to redirect an agent (run commands, change scores, exfiltrate files).

**Defenses**
- Every skill that handles web-derived text carries the [untrusted-content rule](references/untrusted-content.md): fetched text is data, never instructions; suspected attempts are flagged `injection_suspected` and ignored.
- Least-privilege permissions: `.claude/settings.json` allows only the named pipeline scripts. Arbitrary `uv run`, `python`, and package installs prompt for approval.
- Merge-time validation quarantines unverifiable agent output before it reaches your CSVs.

**Residual risk.** The rule is instruction-level, not a guarantee. `WebFetch` is pre-approved because the research pipeline cannot run without it, and a fetch to an attacker-controlled URL is a possible exfiltration channel. Review unexpected agent behavior, and treat `injection_suspected` flags as signals worth reading.

### 2. Personal data leaking into a public repo

The repo is public; your data is not meant to be.

**Defenses**
- `.gitignore` covers config, credentials, CVs, dossiers, application data, and every file a pipeline run generates.
- `.claude/settings.local.json` is per-user and untracked.
- CI fails if a personalized `search-config.json` (anything other than the shipped `setup_required: true` stub) or any tracked data file is committed.

**Residual risk.** `job-search/data/search-config.json` is tracked as a neutral stub, and onboarding overwrites it with your personalized version. Don't `git add -A` in a working copy you've onboarded; CI will catch it, but only after you push.

### 3. Fabricated claims in application materials

A model can invent a credential or a metric. `cv-tailor/scripts/claims_gate.py` is a deterministic check that stops the run before any file is generated if the output contains a number, year, credential acronym, or well-known employer name that isn't in your base CV or profile.

**Residual risk.** The gate covers those four claim types. It does not catch an invented skill or a rephrased responsibility. The redline `.docx` shows every change; read it before you send anything.

### 4. Dependencies

`requirements.txt` uses minimum versions, not pins. Install into the project's virtual environment (`uv venv`), not globally.

### 5. Where your data goes

- **Your AI provider** receives your resume and the text the agents process.
- **Tavily** (optional, off by default) receives careers-page URLs.
- **Gmail and Todoist** (optional, off by default) use credentials you provide.
- Nothing is submitted to an employer on your behalf. The Gmail sender (`job-search/scripts/core/send_email.py`, `gmail.send` scope) isn't called by any workflow and refuses to run unless `gmail_enabled: true`. If you enable it, it becomes the highest-value target for an injection attack, so leave it off unless you need it.

## Hardening tips

- Run in a project directory you trust; avoid `--dangerously-skip-permissions`, which disables every control above.
- Keep `.credentials/` out of cloud-synced folders.
- Run `git status` before every commit.

## Reporting a vulnerability

Please don't open a public issue with exploit details. Use GitHub's **Security → Report a vulnerability** on this repository if available; otherwise open an issue asking for a private contact and leave the details out.
