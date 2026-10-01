"""Regression tests for repo hygiene: leak paths, permission scope, and
untrusted-content rules.

These pin the guarantees that keep personal data out of the public repo and
limit what an injected instruction in fetched web content could do.
"""
import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True)


# --- .gitignore covers everything a pipeline run generates ---

class TestGitignoreLeakPaths:
    # Files a normal pipeline run or onboarding session writes into the repo.
    GENERATED_PATHS = [
        "job-search/data/opportunities.csv",
        "job-search/data/previous-run-snapshot.json",
        "job-search/data/job-search-run-report-2026-01-01.md",
        "job-search/data/pending-eval-shard-1.json",
        "job-search/data/eval-results-shard-1.json",
        "job-search/data/monitor-results.json",
        "job-search/data/prospecting-context-some_path.json",
        "job-search/data/prospecting-context-some_path-expansion.json",
        "job-search/data/prospecting-results-some_path.json",
        "job-search/data/research-results.json",
        ".demo-archive/2026-01-01-pre-fresh-run/target-companies.csv",
        ".claude/settings.local.json",
    ]

    def test_generated_paths_are_ignored(self):
        for path in self.GENERATED_PATHS:
            result = _git("check-ignore", "--no-index", "-q", path)
            assert result.returncode == 0, f"{path} is generated per-user and must be gitignored"

    def test_local_settings_not_tracked(self):
        result = _git("ls-files", "--error-unmatch", ".claude/settings.local.json")
        assert result.returncode != 0, \
            ".claude/settings.local.json is per-user and must not be committed"


# --- Permission allowlist is least-privilege ---

class TestPermissionScope:
    def _allow(self) -> list[str]:
        return json.loads(_read(".claude/settings.json"))["permissions"]["allow"]

    def test_no_blanket_uv_run(self):
        assert "Bash(uv run:*)" not in self._allow(), \
            "Blanket 'uv run' matches 'uv run python -c ...' — allow only named script prefixes"

    def test_no_blanket_interpreter_or_install(self):
        for rule in self._allow():
            assert not rule.startswith(("Bash(python:", "Bash(python3:")), \
                f"{rule} allows arbitrary code execution"
            assert not rule.startswith("Bash(uv pip install:"), \
                f"{rule} allows installing arbitrary packages — pin to requirements.txt"

    def test_pipeline_scripts_allowed(self):
        allow = self._allow()
        for prefix in ("job-search/scripts/ops/", "cv-tailor/scripts/",
                       "job-tracker/scripts/", "interview-prep/scripts/",
                       "evals/scripts/"):
            assert any(prefix in rule for rule in allow), \
                f"Allowlist must cover the pipeline scripts under {prefix}"

    def test_web_tools_allowed(self):
        allow = self._allow()
        assert "WebSearch" in allow and "WebFetch" in allow, \
            "The research pipeline needs WebSearch and WebFetch without per-call prompts"


# --- Untrusted web content is treated as data, never instructions ---

class TestUntrustedContentRules:
    DISPATCHING_SKILLS = [
        "job-search/SKILL.md",
        "company-research/SKILL.md",
        "cv-tailor/SKILL.md",
        "interview-prep/SKILL.md",
    ]

    def test_each_skill_carries_the_rule(self):
        for rel in self.DISPATCHING_SKILLS:
            content = _read(rel)
            assert "Untrusted content" in content, \
                f"{rel} reads web-derived text and must state the untrusted-content rule"
            assert "untrusted-content.md" in content, \
                f"{rel} must link the full rule in references/untrusted-content.md"

    def test_reference_and_security_docs_exist(self):
        assert (PROJECT_ROOT / "references" / "untrusted-content.md").exists()
        assert (PROJECT_ROOT / "SECURITY.md").exists()


# --- README stays in sync with the skills that exist ---

class TestReadmeSkillTable:
    def test_every_skill_is_listed(self):
        readme = _read("README.md")
        skill_dirs = sorted(p.parent.name for p in PROJECT_ROOT.glob("*/SKILL.md"))
        assert skill_dirs, "expected at least one skill directory"
        for name in skill_dirs:
            assert f"{name}/SKILL.md" in readme, \
                f"README Skills Overview is missing the {name} skill"
