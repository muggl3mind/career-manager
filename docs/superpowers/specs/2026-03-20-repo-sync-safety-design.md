# Repo Sync Safety + Restore Working Versions

## Problem

On March 20, a private-to-public repo sync (`export_public.py`) overwrote 11 files in the public repo with older versions from the private repo. The public repo had newer, user-approved versions of these files (committed March 19) that were lost. There is no mechanism to prevent this from recurring.

Three root causes:
1. **No timestamp guard** in the export script. It blindly copies private→public regardless of which version is newer.
2. **No regression tests** on UX-critical skill content. The broken onboarding flow (sequential questions, no CV path prompt) passed all existing tests.
3. **No backport discipline.** Edits made directly in the public repo were never synced back to private, creating a hidden divergence.

## Solution

### Part 1: Restore 11 Regressed Files

Restore the file state as of public repo commit `55bbf49` (the last known-good commit before the overwrite) into both repos. Note: `git show 55bbf49:<path>` returns the file state at that commit point, even if the file was last modified in an earlier commit. Do NOT touch pipeline code (company_dedup.py, path_normalizer.py, generate_dashboard.py, etc.) which was correctly added on March 20.

**Files to restore:**

| File | What was broken | Working version has |
|---|---|---|
| `onboarding/SKILL.md` | Asks user to drop CV manually; questions one-at-a-time; asks about integrations | Asks "Where's your resume?"; single combined question; silent config generation |
| `onboarding/references/example-output.md` | Simplified/broken search-config schema | Full working search-config with query_packs, prospecting_paths, scoring |
| `SKILL.md` (router) | No briefing step; no cross-skill suggestions | Runs generate_briefing.py; suggests next actions after each skill |
| `README.md` | No quick-start; no demo section; slash commands shown as optional DIY | 3-step getting started; demo placeholder; structured optional integrations |
| `config.yaml.example` | todoist_enabled: true, gmail_enabled: true | todoist_enabled: false, gmail_enabled: false, jobspy_enabled: true |
| `cv-tailor/SKILL.md` | No preview step; no page count check; no JD fetch guidance | Preview-before-apply; page count pre-check; fetch JD from URL |
| `company-research/SKILL.md` | Minimal "Integration" section | Auto after-research steps (save dossier, update CSV, suggest next action) |
| `job-tracker/SKILL.md` | No after-completion suggestions | Suggests follow-up drafts, next actions |
| `CLAUDE.md` | Missing status briefing section | Status Briefing section referencing generate_briefing.py |
| `references/command-map.md` | Only job-search commands | Full career-manager command map with natural language equivalents |

| `.claude/commands/job-search.md` | Missing router briefing step | References router for briefing step |

**Process:**
1. `git show 55bbf49:<path>` for each file to get the working content
2. Write to both public and private repos
3. Commit separately in each repo

### Part 2: Timestamp Guard in export_public.py

Modify `scripts/export_public.py` to check file age before overwriting.

**Logic for each file being copied:**
1. Get the file's last commit date in the private repo: `git log -1 --format=%cI -- <path>` (committer date, not author date, to handle cherry-picks/rebases correctly)
2. Get the file's last commit date in the public repo: `git log -1 --format=%cI -- <path>`
3. If public is newer than private: **skip the file** and print a warning: `SKIP (public is newer): <path>`
4. If private is newer or file doesn't exist in public: copy normally
5. If file is new (not in public repo): copy normally

**Force override:** Pass `--force` to bypass the timestamp guard for all files, or `--force-file <path>` to override a specific file. Use when you intentionally rewrote something in private that should replace the public version.

**Edge cases:**
- Files that only exist in private (new files): always copy
- Files that only exist in public: never delete (export only adds/updates)
- PII scrub patches: still apply to the copied content, but only if the file is being copied
- Identical content with different timestamps: guard compares timestamps only (not content hashes), so it may re-copy identical files. This is harmless.

**Output:** At the end of export, print a summary:
```
Exported: 15 files
Skipped (public newer): 3 files
  - onboarding/SKILL.md (public: 2026-03-19, private: 2026-03-18)
  - README.md (public: 2026-03-19, private: 2026-03-17)
  - cv-tailor/SKILL.md (public: 2026-03-19, private: 2026-03-15)
```

### Part 3: Regression Tests for Skill Content

Add `evals/tests/test_skill_content.py` with assertions on UX-critical strings in skill files. These run with `pytest evals/` alongside existing tests.

**Onboarding tests:**
- SKILL.md contains "Where's your resume?" or "Give me the file path"
- SKILL.md contains "I need three things your resume doesn't tell me" (single combined question)
- SKILL.md does NOT contain "one at a time" or "sequentially" in the questions step
- SKILL.md does NOT contain "Drop your resume" or "Check for Master CV" (passive drop-it-in-a-folder pattern)
- SKILL.md contains "Do NOT ask the user to copy files manually"
- SKILL.md contains "silently" in the generate files step

**Config tests:**
- config.yaml.example has `jobspy_enabled: true`
- config.yaml.example has `todoist_enabled: false`
- config.yaml.example has `gmail_enabled: false`

**Router tests:**
- SKILL.md contains "generate_briefing.py"
- SKILL.md contains "Cross-Skill Flow" or cross-skill suggestion table

**CV tailor tests:**
- cv-tailor/SKILL.md contains "Preview Before Apply" or "preview"

**Company research tests:**
- company-research/SKILL.md contains "After Research" section

**README tests:**
- README.md contains "Getting Started"

These are intentionally simple string checks. They catch regressions without being brittle to minor wording changes. All paths are resolved relative to the repo root via `Path(__file__).resolve().parents[2]`.

### Part 4: Divergence Detection Script + Backport Workflow

Add `scripts/check_sync.py` that compares skill/config files between the two repos and reports divergence. This prevents the manual discipline failure that caused the original incident.

**Logic:**
1. For each tracked file (the 11 files from Part 1 + any future skill files), compare content between private and public repos
2. If content differs, report which repo has the newer version (by committer date)
3. Exit with non-zero status if any divergence is found

**Usage:**
```bash
python3 scripts/check_sync.py --private /path/to/private --public /path/to/public
```

**Output:**
```
DIVERGED: onboarding/SKILL.md (public newer: 2026-03-19 vs private: 2026-03-18)
DIVERGED: README.md (public newer: 2026-03-19 vs private: 2026-03-17)
2 files diverged. Run with --fix to copy newer versions to the older repo.
```

**Backport workflow (documented in private repo CLAUDE.md under "Repo Sync"):**

After editing skill files in either repo:
1. Run `check_sync.py` to detect divergence
2. If diverged, copy the newer version to the other repo
3. Commit with message: `sync: backport <file> from [public|private] repo`

## Files Changed

**New files:**
- `evals/tests/test_skill_content.py` — regression tests
- `scripts/check_sync.py` — divergence detection between repos

**Modified files:**
- `scripts/export_public.py` — add timestamp guard + force flags
- 11 restored files (listed in Part 1)
- Private repo CLAUDE.md — add repo sync instructions

## Testing

- All existing tests pass after restore (`pytest evals/`)
- New skill content tests pass (`pytest evals/tests/test_skill_content.py`)
- Run `export_public.py` against the synced repos and verify no files are skipped (since both are now identical)
- Run onboarding on a test machine to verify the frictionless flow works end-to-end
