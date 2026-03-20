# Repo Sync Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore 11 regressed skill/config files, then add safeguards (timestamp guard, regression tests, divergence detection) to prevent future sync overwrites.

**Architecture:** Part 1 restores files from a known-good git commit into both repos. Parts 2-4 add three layers of protection: the export script checks timestamps before overwriting, regression tests catch content changes, and a sync checker detects divergence between repos.

**Tech Stack:** Python 3, pytest, git CLI, pathlib, subprocess, argparse

---

## File Structure

**New files:**
- `evals/tests/test_skill_content.py` — regression tests for UX-critical skill content (public repo)
- `scripts/check_sync.py` — divergence detection between private and public repos (private repo only, skipped by export)

**Modified files:**
- `scripts/export_public.py` — add timestamp guard + `--force` / `--force-file` flags (private repo only)
- 11 restored files (both repos, content from public repo commit `55bbf49`)

---

### Task 1: Restore 11 Regressed Files to Public Repo

**Files:**
- Modify: `onboarding/SKILL.md`
- Modify: `onboarding/references/example-output.md`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `config.yaml.example`
- Modify: `cv-tailor/SKILL.md`
- Modify: `company-research/SKILL.md`
- Modify: `job-tracker/SKILL.md`
- Modify: `CLAUDE.md`
- Modify: `references/command-map.md`
- Modify: `.claude/commands/job-search.md`

All work in this task happens in the **public repo**: `/Users/bot/Documents/AI Projects/career-manager-public/`

- [ ] **Step 1: Extract all 11 files from the known-good commit**

Run these commands to restore each file from commit `55bbf49` (the last known-good state before the overwrite):

```bash
cd /Users/bot/Documents/AI\ Projects/career-manager-public
git show 55bbf49:onboarding/SKILL.md > onboarding/SKILL.md
git show 55bbf49:onboarding/references/example-output.md > onboarding/references/example-output.md
git show 55bbf49:SKILL.md > SKILL.md
git show 55bbf49:README.md > README.md
git show 55bbf49:config.yaml.example > config.yaml.example
git show 55bbf49:cv-tailor/SKILL.md > cv-tailor/SKILL.md
git show 55bbf49:company-research/SKILL.md > company-research/SKILL.md
git show 55bbf49:job-tracker/SKILL.md > job-tracker/SKILL.md
git show 55bbf49:CLAUDE.md > CLAUDE.md
git show 55bbf49:references/command-map.md > references/command-map.md
git show 55bbf49:.claude/commands/job-search.md > .claude/commands/job-search.md
```

- [ ] **Step 2: Verify restored files have expected content**

Spot-check critical files:

```bash
# Onboarding should ask for CV path, not tell user to drop it
grep -c "Where's your resume" onboarding/SKILL.md
# Expected: 1

# Onboarding should have single combined question
grep -c "I need three things" onboarding/SKILL.md
# Expected: 1

# Onboarding should NOT have one-at-a-time
grep -c "one at a time" onboarding/SKILL.md
# Expected: 0

# Config should have jobspy true, others false
grep "jobspy_enabled" config.yaml.example
# Expected: jobspy_enabled: true

grep "todoist_enabled" config.yaml.example
# Expected: todoist_enabled: false

grep "gmail_enabled" config.yaml.example
# Expected: gmail_enabled: false

# Router should have briefing
grep -c "generate_briefing" SKILL.md
# Expected: >= 1
```

- [ ] **Step 3: Run existing tests to ensure nothing breaks**

```bash
cd /Users/bot/Documents/AI\ Projects/career-manager-public
python3 -m pytest evals/tests/ -v
```

Expected: All existing tests pass. The restored files are skill docs and config, not pipeline code, so no test should break.

- [ ] **Step 4: Commit in public repo**

```bash
cd /Users/bot/Documents/AI\ Projects/career-manager-public
git add onboarding/SKILL.md onboarding/references/example-output.md SKILL.md README.md config.yaml.example cv-tailor/SKILL.md company-research/SKILL.md job-tracker/SKILL.md CLAUDE.md references/command-map.md .claude/commands/job-search.md
git commit -m "fix: restore 11 skill/config files overwritten by sync

Reverts to the working versions from commit 55bbf49 (March 19).
The pipeline data integrity sync on March 20 overwrote these with
older private repo versions, breaking frictionless onboarding,
cross-skill suggestions, and other UX features."
```

---

### Task 2: Backport Restored Files to Private Repo

**Files:** Same 11 files, written to `/Users/bot/Documents/AI Projects/skills/career-manager/`

- [ ] **Step 1: Copy each restored file from public to private repo**

```bash
PUBLIC="/Users/bot/Documents/AI Projects/career-manager-public"
PRIVATE="/Users/bot/Documents/AI Projects/skills/career-manager"

for f in \
  onboarding/SKILL.md \
  onboarding/references/example-output.md \
  SKILL.md \
  README.md \
  config.yaml.example \
  cv-tailor/SKILL.md \
  company-research/SKILL.md \
  job-tracker/SKILL.md \
  CLAUDE.md \
  references/command-map.md \
  .claude/commands/job-search.md; do
  cp "$PUBLIC/$f" "$PRIVATE/$f"
done
```

- [ ] **Step 2: Verify private repo files match public**

```bash
for f in \
  onboarding/SKILL.md \
  SKILL.md \
  config.yaml.example \
  cv-tailor/SKILL.md; do
  diff "$PUBLIC/$f" "$PRIVATE/$f" && echo "$f: OK" || echo "$f: MISMATCH"
done
```

Expected: All files show OK.

- [ ] **Step 3: Run private repo tests**

```bash
cd /Users/bot/Documents/AI\ Projects/skills/career-manager
uv run python3 -m pytest evals/tests/ -v
```

Expected: All tests pass.

- [ ] **Step 4: Commit in private repo**

```bash
cd /Users/bot/Documents/AI\ Projects/skills
git add career-manager/onboarding/SKILL.md career-manager/onboarding/references/example-output.md career-manager/SKILL.md career-manager/README.md career-manager/config.yaml.example career-manager/cv-tailor/SKILL.md career-manager/company-research/SKILL.md career-manager/job-tracker/SKILL.md career-manager/CLAUDE.md career-manager/references/command-map.md career-manager/.claude/commands/job-search.md
git commit -m "sync: backport 11 restored skill/config files from public repo

These files were updated in the public repo on March 19 but the
private repo still had older versions, causing a regression when
export_public.py synced private->public on March 20."
```

---

### Task 3: Add Regression Tests for Skill Content

**Files:**
- Create: `evals/tests/test_skill_content.py` (in public repo)

- [ ] **Step 1: Write the test file**

Create `/Users/bot/Documents/AI Projects/career-manager-public/evals/tests/test_skill_content.py`:

```python
"""Regression tests for UX-critical skill content.

These catch sync overwrites that silently break the user experience.
Each test asserts that key strings exist (or don't exist) in skill files.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


# --- Onboarding ---

class TestOnboardingSkill:
    def test_asks_for_resume_path(self):
        content = _read("onboarding/SKILL.md")
        assert ("file path" in content.lower()) or ("where" in content.lower() and "resume" in content.lower()), \
            "Onboarding must ask user for their resume path, not tell them to drop it in a folder"

    def test_single_combined_question(self):
        content = _read("onboarding/SKILL.md")
        assert "three things" in content.lower() or "i need" in content.lower(), \
            "Onboarding must ask all questions in a single combined message"

    def test_no_sequential_questions(self):
        content = _read("onboarding/SKILL.md")
        assert "one at a time" not in content.lower(), \
            "Onboarding must NOT ask questions one at a time"
        assert "sequentially" not in content.lower(), \
            "Onboarding must NOT ask questions sequentially"

    def test_no_passive_cv_drop(self):
        content = _read("onboarding/SKILL.md")
        assert "Drop your resume" not in content, \
            "Onboarding must NOT tell user to drop resume in a folder"
        assert "Check for Master CV" not in content, \
            "Onboarding must NOT passively check a folder for CV"

    def test_claude_handles_copy(self):
        content = _read("onboarding/SKILL.md")
        assert "Do NOT ask the user to copy files manually" in content, \
            "Onboarding must explicitly state Claude handles the file copy"

    def test_silent_generation(self):
        content = _read("onboarding/SKILL.md")
        assert "silently" in content.lower(), \
            "Onboarding must generate files silently without overwrite warnings"


# --- Config ---

class TestConfigDefaults:
    def test_jobspy_enabled_by_default(self):
        content = _read("config.yaml.example")
        assert "jobspy_enabled: true" in content, \
            "JobSpy must be enabled by default for new users"

    def test_todoist_disabled_by_default(self):
        content = _read("config.yaml.example")
        assert "todoist_enabled: false" in content, \
            "Todoist must be disabled by default (requires API token)"

    def test_gmail_disabled_by_default(self):
        content = _read("config.yaml.example")
        assert "gmail_enabled: false" in content, \
            "Gmail must be disabled by default (requires OAuth setup)"


# --- Router ---

class TestRouterSkill:
    def test_has_briefing_step(self):
        content = _read("SKILL.md")
        assert "generate_briefing" in content, \
            "Router must reference generate_briefing.py for status snapshot"

    def test_has_cross_skill_flow(self):
        content = _read("SKILL.md")
        assert "Cross-Skill Flow" in content or "Suggest" in content, \
            "Router must have cross-skill flow suggestions"


# --- CV Tailor ---

class TestCVTailorSkill:
    def test_has_preview_step(self):
        content = _read("cv-tailor/SKILL.md")
        assert "preview" in content.lower() or "Preview Before Apply" in content, \
            "CV tailor must have a preview-before-apply step"


# --- Company Research ---

class TestCompanyResearchSkill:
    def test_has_after_research_steps(self):
        content = _read("company-research/SKILL.md")
        assert "After Research" in content, \
            "Company research must have automatic after-research steps"


# --- README ---

class TestReadme:
    def test_has_getting_started(self):
        content = _read("README.md")
        assert "Getting Started" in content, \
            "README must have a Getting Started section"
```

- [ ] **Step 2: Run the tests to verify they pass**

```bash
cd /Users/bot/Documents/AI\ Projects/career-manager-public
python3 -m pytest evals/tests/test_skill_content.py -v
```

Expected: All 14 tests pass (the restored files have the correct content).

- [ ] **Step 3: Copy test file to private repo**

```bash
cp "/Users/bot/Documents/AI Projects/career-manager-public/evals/tests/test_skill_content.py" \
   "/Users/bot/Documents/AI Projects/skills/career-manager/evals/tests/test_skill_content.py"
```

- [ ] **Step 4: Run tests in private repo too**

```bash
cd /Users/bot/Documents/AI\ Projects/skills/career-manager
uv run python3 -m pytest evals/tests/test_skill_content.py -v
```

Expected: All 14 tests pass.

- [ ] **Step 5: Commit in both repos**

```bash
cd /Users/bot/Documents/AI\ Projects/career-manager-public
git add evals/tests/test_skill_content.py
git commit -m "test: add regression tests for UX-critical skill content

13 string-based assertions that catch sync overwrites breaking:
- Frictionless onboarding (CV path prompt, single question, silent gen)
- Config defaults (JobSpy on, Todoist/Gmail off)
- Router briefing and cross-skill flow
- CV tailor preview step
- Company research after-research steps
- README getting started section"
```

```bash
cd /Users/bot/Documents/AI\ Projects/skills
git add career-manager/evals/tests/test_skill_content.py
git commit -m "test: add regression tests for UX-critical skill content"
```

---

### Task 4: Add Timestamp Guard to export_public.py

**Files:**
- Modify: `/Users/bot/Documents/AI Projects/skills/career-manager/scripts/export_public.py`

- [ ] **Step 1: Add the timestamp comparison function**

Add this function right before the `export()` function definition (line 389) in `scripts/export_public.py`:

```python
def get_last_commit_ts(repo_path: Path, file_path: str) -> int:
    """Get unix timestamp of the last commit touching a file. Returns 0 if not found."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", file_path],
        capture_output=True, text=True, cwd=repo_path,
    )
    ts = result.stdout.strip()
    return int(ts) if ts else 0


def get_last_commit_date_str(repo_path: Path, file_path: str) -> str:
    """Get human-readable date of last commit (for display only)."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", file_path],
        capture_output=True, text=True, cwd=repo_path,
    )
    return result.stdout.strip() or "unknown"
```

- [ ] **Step 2: Add --force and --force-file arguments**

In the `main()` function (around line 543), add after the existing `--skip-validation` argument:

```python
    ap.add_argument("--force", action="store_true",
                    help="Bypass timestamp guard — overwrite even if public is newer")
    ap.add_argument("--force-file", action="append", default=[],
                    help="Bypass timestamp guard for specific file(s)")
```

- [ ] **Step 3: Make three surgical edits to the export() function**

Three changes to `scripts/export_public.py`. Do NOT replace the entire loop — make targeted insertions.

**Edit 3a:** Update the function signature (line 389):

```python
# Before:
def export(src: Path, dest: Path, dry_run: bool = False):

# After:
def export(src: Path, dest: Path, dry_run: bool = False,
           force: bool = False, force_files: list[str] | None = None):
```

**Edit 3b:** Add `skipped_newer = []` right after the existing counter variables (after line 394, before the `for` loop):

```python
    scrubbed = 0
    templated = 0
    skipped_newer = []       # <-- add this line

    for rel in tracked:
```

**Edit 3c:** Add the timestamp guard block inside the loop, right after `if not src_path.exists(): continue` (after line 409), BEFORE the `if dry_run:` block:

```python
        if not src_path.exists():
            continue

        # --- NEW: Timestamp guard ---
        if not force and rel not in (force_files or []):
            dest_ts = get_last_commit_ts(dest, rel)
            if dest_ts:
                src_ts = get_last_commit_ts(src, rel)
                if src_ts and dest_ts > src_ts:
                    pub_date = get_last_commit_date_str(dest, rel)
                    priv_date = get_last_commit_date_str(src, rel)
                    skipped_newer.append((rel, pub_date, priv_date))
                    skipped += 1
                    if dry_run:
                        print(f"  SKIP     {rel} (public newer: {pub_date} vs {priv_date})")
                    continue
        # --- END NEW ---

        if dry_run:
```

**Edit 3d:** Change the return statement at the end of `export()` (line 454):

```python
# Before:
    return exported, skipped, scrubbed, templated

# After:
    return exported, skipped, scrubbed, templated, skipped_newer
```

- [ ] **Step 4: Update the main() function to pass new args and print summary**

Update the `export()` call and summary printing in `main()`:

```python
    exported, skipped, scrubbed, templated, skipped_newer = export(
        SRC, args.dest, dry_run=args.dry_run,
        force=args.force, force_files=args.force_file,
    )
```

After the existing summary print block (around line 577), add:

```python
        if skipped_newer:
            print(f"\n--- Timestamp guard ---")
            print(f"Skipped (public newer): {len(skipped_newer)} files")
            for rel, pub_date, priv_date in skipped_newer:
                print(f"  - {rel} (public: {pub_date}, private: {priv_date})")
            print("Use --force to overwrite, or --force-file <path> for specific files.")
```

- [ ] **Step 5: Add export_public.py to SKIP_FILES**

Verify that `scripts/export_public.py` is already in `SKIP_FILES` (it is — line 24). No change needed, but confirm the script won't export itself.

- [ ] **Step 6: Test the timestamp guard (happy path)**

```bash
cd /Users/bot/Documents/AI\ Projects/skills/career-manager
uv run python3 scripts/export_public.py --dry-run
```

Expected: All files show COPY/SCRUB/TEMPLATE/SKIP. No files should show "public newer" since we just synced them in Tasks 1-2.

- [ ] **Step 7: Test the timestamp guard (negative test — verify it actually blocks)**

Create a trivial change in the public repo that is newer than private, then verify the guard catches it:

```bash
# Make a trivial change in public repo and commit it
cd /Users/bot/Documents/AI\ Projects/career-manager-public
echo "" >> config.yaml.example
git add config.yaml.example
git commit -m "test: verify timestamp guard (will revert)"

# Run dry-run from private repo — should show SKIP for config.yaml.example
cd /Users/bot/Documents/AI\ Projects/skills/career-manager
uv run python3 scripts/export_public.py --dry-run 2>&1 | grep "config.yaml.example"
# Expected: "SKIP     config.yaml.example (public newer: ...)"

# Verify --force overrides the guard
uv run python3 scripts/export_public.py --dry-run --force 2>&1 | grep "config.yaml.example"
# Expected: "COPY     config.yaml.example" (not SKIP)

# Revert the test change
cd /Users/bot/Documents/AI\ Projects/career-manager-public
git reset --hard HEAD~1
```

- [ ] **Step 8: Commit**

```bash
cd /Users/bot/Documents/AI\ Projects/skills
git add career-manager/scripts/export_public.py
git commit -m "feat: add timestamp guard to export_public.py

Compares committer dates before overwriting. Skips files where the
public repo version is newer than private. Prevents accidental
regression of public-repo-only changes during sync.

Flags: --force (all files), --force-file <path> (specific file)"
```

---

### Task 5: Add Divergence Detection Script

**Files:**
- Create: `/Users/bot/Documents/AI Projects/skills/career-manager/scripts/check_sync.py`
- Modify: `/Users/bot/Documents/AI Projects/skills/career-manager/CLAUDE.md` (add Repo Sync section)

- [ ] **Step 1: Write check_sync.py**

Create `/Users/bot/Documents/AI Projects/skills/career-manager/scripts/check_sync.py`:

```python
#!/usr/bin/env python3
"""
Detect divergence between private and public career-manager repos.

Usage:
    python3 scripts/check_sync.py [--public /path/to/public/repo] [--fix]

Compares tracked skill/config files. Reports which repo has the newer
version when content differs. Use --fix to auto-copy newer files.
"""
import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

PRIVATE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC = PRIVATE_ROOT.parent.parent / "career-manager-public"

# Files that must stay in sync between repos
TRACKED_FILES = [
    "onboarding/SKILL.md",
    "onboarding/references/example-output.md",
    "SKILL.md",
    "README.md",
    "config.yaml.example",
    "cv-tailor/SKILL.md",
    "company-research/SKILL.md",
    "job-tracker/SKILL.md",
    "CLAUDE.md",
    "references/command-map.md",
    ".claude/commands/job-search.md",
]


def get_commit_ts(repo: Path, rel: str) -> int:
    """Get unix timestamp of last commit touching a file."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", rel],
        capture_output=True, text=True, cwd=repo,
    )
    ts = result.stdout.strip()
    return int(ts) if ts else 0


def get_commit_date_str(repo: Path, rel: str) -> str:
    """Get human-readable date (for display only)."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", rel],
        capture_output=True, text=True, cwd=repo,
    )
    return result.stdout.strip() or "unknown"


def check(private: Path, public: Path, fix: bool = False) -> int:
    diverged = []

    for rel in TRACKED_FILES:
        priv_path = private / rel
        pub_path = public / rel

        if not priv_path.exists() and not pub_path.exists():
            continue
        if not priv_path.exists():
            diverged.append((rel, "public only", "", ""))
            continue
        if not pub_path.exists():
            diverged.append((rel, "private only", "", ""))
            continue

        if filecmp.cmp(priv_path, pub_path, shallow=False):
            continue

        priv_ts = get_commit_ts(private, rel)
        pub_ts = get_commit_ts(public, rel)
        priv_date = get_commit_date_str(private, rel)
        pub_date = get_commit_date_str(public, rel)

        if pub_ts > priv_ts:
            newer = "public"
        elif priv_ts > pub_ts:
            newer = "private"
        else:
            newer = "same date, content differs"

        diverged.append((rel, newer, pub_date, priv_date))

        if fix:
            if newer == "public":
                shutil.copy2(pub_path, priv_path)
                print(f"  FIXED: {rel} (copied public -> private)")
            elif newer == "private":
                shutil.copy2(priv_path, pub_path)
                print(f"  FIXED: {rel} (copied private -> public)")

    if not diverged:
        print("All tracked files are in sync.")
        return 0

    if not fix:
        print(f"{len(diverged)} file(s) diverged:\n")
        for rel, newer, pub_date, priv_date in diverged:
            if newer in ("public only", "private only"):
                print(f"  DIVERGED: {rel} ({newer})")
            else:
                print(f"  DIVERGED: {rel} ({newer} newer: pub={pub_date} vs priv={priv_date})")
        print(f"\nRun with --fix to copy newer versions to the older repo.")

    return 1


def main():
    ap = argparse.ArgumentParser(description="Check sync between private and public repos")
    ap.add_argument("--public", type=Path, default=DEFAULT_PUBLIC,
                    help="Path to public repo")
    ap.add_argument("--fix", action="store_true",
                    help="Auto-copy newer files to the older repo")
    args = ap.parse_args()

    print(f"Private: {PRIVATE_ROOT}")
    print(f"Public:  {args.public}\n")

    sys.exit(check(PRIVATE_ROOT, args.public, fix=args.fix))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test the sync checker**

```bash
cd /Users/bot/Documents/AI\ Projects/skills/career-manager
uv run python3 scripts/check_sync.py
```

Expected: "All tracked files are in sync." (since we just synced in Tasks 1-2).

- [ ] **Step 3: Add check_sync.py to SKIP_FILES in export_public.py**

In `scripts/export_public.py`, update SKIP_FILES:

```python
SKIP_FILES = {
    "scripts/export_public.py",
    "scripts/check_sync.py",
}
```

- [ ] **Step 4: Add Repo Sync section to private repo CLAUDE.md**

Append this section to the end of `/Users/bot/Documents/AI Projects/skills/career-manager/CLAUDE.md` (after the "Testing" section, which is the last section in the file):

```markdown
## Repo Sync

The public repo at `career-manager-public/` is synced from this private repo via `scripts/export_public.py`. Both repos must stay in sync for skill files.

**Before exporting:**
```bash
uv run python3 scripts/check_sync.py
```

If divergence is found, resolve before exporting. The export script has a timestamp guard that skips files where the public version is newer, but always verify with `check_sync.py` first.

**After editing skill files in either repo:** run `check_sync.py --fix` to copy the newer version to the other repo, then commit in both.
```

- [ ] **Step 5: Commit**

```bash
cd /Users/bot/Documents/AI\ Projects/skills
git add career-manager/scripts/check_sync.py career-manager/scripts/export_public.py career-manager/CLAUDE.md
git commit -m "feat: add divergence detection between private and public repos

New scripts/check_sync.py compares 11 tracked skill/config files
between repos, reports which has newer versions, and can auto-fix
with --fix flag. Also adds check_sync.py to export skip list."
```

---

### Task 6: Final Verification

- [ ] **Step 1: Run full test suite in public repo**

```bash
cd /Users/bot/Documents/AI\ Projects/career-manager-public
python3 -m pytest evals/tests/ -v
```

Expected: All tests pass, including the 13 new skill content tests.

- [ ] **Step 2: Run full test suite in private repo**

```bash
cd /Users/bot/Documents/AI\ Projects/skills/career-manager
uv run python3 -m pytest evals/tests/ -v
```

Expected: All tests pass.

- [ ] **Step 3: Run sync checker to verify both repos match**

```bash
cd /Users/bot/Documents/AI\ Projects/skills/career-manager
uv run python3 scripts/check_sync.py
```

Expected: "All tracked files are in sync."

- [ ] **Step 4: Dry-run export to verify timestamp guard works**

```bash
cd /Users/bot/Documents/AI\ Projects/skills/career-manager
uv run python3 scripts/export_public.py --dry-run
```

Expected: No files show "public newer" (all synced). All files show COPY/SCRUB/TEMPLATE/SKIP as appropriate.

- [ ] **Step 5: Push public repo to GitHub**

```bash
cd /Users/bot/Documents/AI\ Projects/career-manager-public
git push origin main
```
