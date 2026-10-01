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

    def test_defaults_to_four_to_five_paths(self):
        content = _read("onboarding/SKILL.md")
        assert "4-5 paths" in content, \
            "Onboarding must default to 4-5 career paths"
        assert "5-8 paths" not in content, \
            "Onboarding must not reference the old 5-8 path default"
        assert "Minimum: 5 paths" not in content, \
            "Onboarding must not require a 5-path minimum"

    def test_add_more_paths_later_guidance(self):
        content = _read("onboarding/SKILL.md")
        assert "add more paths later" in content.lower(), \
            "Onboarding must tell users they can add more paths later"


class TestOnboardingExample:
    """Pins onboarding/references/example-output.md to the current schemas."""

    def test_search_config_matches_current_schema(self):
        content = _read("onboarding/references/example-output.md")
        for key in ('"setup_required": false', '"query_packs"',
                    '"path_check_instructions"', '"path_aliases"',
                    '"display_groups"', '"search_locations"'):
            assert key in content, f"Example search-config must include {key}"

    def test_search_config_shows_four_to_five_packs(self):
        content = _read("onboarding/references/example-output.md")
        assert content.count('"job_type"') in (4, 5), \
            "Example must show 4-5 query packs to match the onboarding default"

    def test_criteria_uses_ratio_rubric(self):
        content = _read("onboarding/references/example-output.md")
        assert "yes count / evaluated count" in content, \
            "Example criteria must use the canonical ratio scoring formula"
        assert "never 0" in content, \
            "Example criteria must state unknowns are null, never 0"
        assert "Must-Haves" not in content, \
            "Example must not use the retired Must-Haves rubric format"

    def test_config_yaml_uses_current_keys(self):
        content = _read("onboarding/references/example-output.md")
        for key in ("cv_base", "jobspy_enabled", "apply_min_score",
                    "discover_min_score", "archive_grace_runs"):
            assert key in content, f"Example config.yaml must include {key}"
        for legacy in ("update_frequency", "auto_search", "notify_strong_matches"):
            assert legacy not in content, \
                f"Example config.yaml must not include retired key {legacy}"


# --- Email templates ---

class TestEmailTemplates:
    def test_unused_digest_templates_deleted(self):
        for name in ("morning-email.md", "afternoon-email.md", "evening-email.md"):
            assert not (PROJECT_ROOT / "job-search" / "templates" / name).exists(), \
                f"{name} is an orphaned digest artifact and must stay deleted"

    def test_followup_template_kept(self):
        assert (PROJECT_ROOT / "job-search" / "templates" / "follow-up-email.md").exists(), \
            "follow-up-email.md is referenced by job-tracker and must exist"

    def test_send_email_listing_removed(self):
        content = _read("job-search/SKILL.md")
        assert "send_email.py" not in content, \
            "job-search SKILL.md must not list send_email.py (not part of the pipeline)"


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
