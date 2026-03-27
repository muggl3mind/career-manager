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
