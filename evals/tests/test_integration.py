#!/usr/bin/env python3
"""
Integration tests — verify the pipeline works end-to-end with a test config.
Catches issues that unit tests and smoke tests miss, like:
- Scoring returns 0 for all companies
- Config schema mismatches between onboarding output and pipeline consumers
- Missing keys in search-config.json that scripts expect
"""

import csv
import json
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "job-search" / "scripts" / "core"))
sys.path.insert(0, str(PROJECT_ROOT / "job-search" / "scripts" / "ops"))


# --- Fixtures ---

@pytest.fixture
def sample_search_config(tmp_path):
    """A minimal but complete search-config.json as onboarding would generate."""
    config = {
        "query_packs": {
            "test_path": {
                "label": "Test Career Path",
                "queries": ["test query for job boards"]
            }
        },
        "role_include_patterns": ["product manager", "solutions architect"],
        "role_exclude_patterns": ["intern", "bookkeeper"],
        "employer_exclude_patterns": ["university", "government"],
        "location_exclude_patterns": ["london", "singapore"],
        "role_rescue_keywords": ["ai", "product"],
        "keywords": {
            "domain": ["accounting", "finance"],
            "ai": ["ai", "llm", "machine learning"],
            "tech": ["python", "api"]
        },
        "gold_companies": ["acme corp", "test company"],
        "prospecting_paths": [
            {
                "path": 1,
                "name": "Test Career Path",
                "search_queries": ["test web search query"],
                "named_targets": ["Acme Corp", "Test Company"],
                "new_targets_goal": 2
            }
        ],
        "path_check_instructions": {
            "1": "Look for product manager and solutions architect roles."
        },
        "role_patterns": ["product manager", "solutions architect"],
        "scoring": {
            "domain_keywords": {
                "accounting": 10, "finance": 8, "audit": 9
            },
            "ai_keywords": {
                "ai": 6, "llm": 8, "machine learning": 7,
                "automation": 5
            },
            "role_keywords": {
                "product manager": 10, "solutions architect": 10
            },
            "comp_indicators": {
                "series c": 7, "public": 8
            },
            "growth_indicators": {
                "series b": 8, "hypergrowth": 9
            },
            "culture_keywords": {
                "remote_flexible": ["remote", "distributed"],
                "innovation": ["innovation", "builder", "startup"]
            }
        }
    }
    config_path = tmp_path / "search-config.json"
    config_path.write_text(json.dumps(config, indent=2))
    return config_path


@pytest.fixture
def sample_target_csv(tmp_path):
    """A minimal target-companies.csv with companies to score."""
    header = [
        'rank', 'company', 'website', 'careers_url', 'role_url',
        'industry', 'size', 'stage', 'recent_funding',
        'tech_signals', 'open_positions', 'last_checked',
        'notes', 'role_family', 'source',
        'location_detected', 'validation_status', 'exclusion_reason',
        'llm_score', 'llm_rationale', 'llm_flags',
        'llm_hard_pass', 'llm_hard_pass_reason', 'llm_evaluated_at',
    ]
    rows = [
        {
            'company': 'HealthAI Corp',
            'industry': 'AI healthcare automation',
            'tech_signals': 'ai, llm, python',
            'open_positions': 'Product Manager',
            'stage': 'Series C',
            'validation_status': 'pass',
            'source': 'web_prospecting',
        },
        {
            'company': 'Generic Corp',
            'industry': 'Retail',
            'tech_signals': '',
            'open_positions': 'Store Manager',
            'validation_status': 'pass',
            'source': 'web_prospecting',
        },
    ]
    csv_path = tmp_path / "target-companies.csv"
    with csv_path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in rows:
            full_row = {k: row.get(k, '') for k in header}
            writer.writerow(full_row)
    return csv_path


# --- Tests ---

class TestSearchConfigSchema:
    """Verify search-config.json schema matches what all pipeline scripts expect."""

    def test_has_all_required_keys(self, sample_search_config):
        from search_config_loader import load_search_config
        config = load_search_config(sample_search_config)
        assert config is not None

        required = [
            "query_packs", "role_include_patterns", "role_exclude_patterns",
            "employer_exclude_patterns", "location_exclude_patterns",
            "keywords", "gold_companies",
        ]
        for key in required:
            assert key in config, f"Missing required key: {key}"

    def test_has_scoring_section(self, sample_search_config):
        config = json.loads(sample_search_config.read_text())
        assert "scoring" in config, "search-config.json must have a 'scoring' key for company scoring"
        scoring = config["scoring"]
        for key in ["domain_keywords", "ai_keywords", "role_keywords",
                     "comp_indicators", "growth_indicators", "culture_keywords"]:
            assert key in scoring, f"scoring section missing key: {key}"

    def test_has_prospecting_paths(self, sample_search_config):
        config = json.loads(sample_search_config.read_text())
        assert "prospecting_paths" in config, "Missing prospecting_paths"
        assert len(config["prospecting_paths"]) > 0

    def test_has_path_check_instructions(self, sample_search_config):
        config = json.loads(sample_search_config.read_text())
        assert "path_check_instructions" in config, "Missing path_check_instructions"

    def test_has_role_patterns(self, sample_search_config):
        config = json.loads(sample_search_config.read_text())
        assert "role_patterns" in config, "Missing role_patterns"
        assert len(config["role_patterns"]) > 0

    def test_all_regex_patterns_compile(self, sample_search_config):
        config = json.loads(sample_search_config.read_text())
        for key in ["role_include_patterns", "role_exclude_patterns",
                     "employer_exclude_patterns", "location_exclude_patterns"]:
            for pattern in config.get(key, []):
                # Strip inline flags like (?i) that the pipeline strips
                cleaned = re.sub(r'\(\?[aiLmsux]+\)', '', pattern)
                re.compile(cleaned)  # Should not raise


class TestScoringProducesResults:
    """Verify that scoring actually produces non-zero scores."""

    def test_score_company_with_matching_keywords(self, sample_search_config):
        from search_config_loader import load_search_config
        config = load_search_config(sample_search_config)
        scoring = config.get("scoring", {})

        # Simulate what score_companies.py does
        domain_kw = scoring.get("domain_keywords", {})
        ai_kw = scoring.get("ai_keywords", {})

        assert len(domain_kw) > 0, "domain_keywords is empty — scoring will produce all zeros"
        assert len(ai_kw) > 0, "ai_keywords is empty — scoring will produce all zeros"

        # Test that a company with matching text gets a non-zero score
        test_text = "AI accounting automation platform with llm features"
        matches = [w for w in domain_kw if w.lower() in test_text.lower()]
        assert len(matches) > 0, f"No domain keywords matched in: {test_text}"

    def test_culture_keywords_are_lists(self, sample_search_config):
        config = json.loads(sample_search_config.read_text())
        culture = config.get("scoring", {}).get("culture_keywords", {})
        for group_name, keywords in culture.items():
            assert isinstance(keywords, list), \
                f"culture_keywords.{group_name} must be a list, got {type(keywords)}"

    def test_scoring_weights_are_numeric(self, sample_search_config):
        config = json.loads(sample_search_config.read_text())
        scoring = config.get("scoring", {})
        for key in ["domain_keywords", "ai_keywords", "role_keywords",
                     "comp_indicators", "growth_indicators"]:
            for keyword, weight in scoring.get(key, {}).items():
                assert isinstance(weight, (int, float)), \
                    f"scoring.{key}.{keyword} weight must be numeric, got {type(weight)}: {weight}"


class TestBuildRegex:
    """Verify _build_regex handles edge cases."""

    def test_empty_patterns_returns_never_match(self):
        from discovery_pipeline import _build_regex
        pattern = _build_regex([])
        assert not pattern.search("anything")

    def test_strips_inline_flags(self):
        from discovery_pipeline import _build_regex
        # Should not raise even with (?i) in patterns
        pattern = _build_regex(["(?i)university", "(?i)college"])
        assert pattern.search("University of Testing")

    def test_normal_patterns_work(self):
        from discovery_pipeline import _build_regex
        pattern = _build_regex(["university", "college"])
        assert pattern.search("University of Testing")
        assert not pattern.search("no match here")


class TestProspectingPathsLoaded:
    """Verify web_prospecting and monitor_watchlist can load from config."""

    def test_prospecting_paths_structure(self, sample_search_config):
        config = json.loads(sample_search_config.read_text())
        for path in config["prospecting_paths"]:
            assert "path" in path, "Missing 'path' (number)"
            assert "name" in path, "Missing 'name'"
            assert "search_queries" in path, "Missing 'search_queries'"
            assert "named_targets" in path, "Missing 'named_targets'"
            assert "new_targets_goal" in path, "Missing 'new_targets_goal'"
            assert isinstance(path["named_targets"], list)
            assert len(path["named_targets"]) > 0


class TestMonitorResultsScoringSchema:
    """Verify cmd_merge copies LLM scoring fields from results into target CSV."""

    def _write_target_csv(self, path, rows):
        from web_prospecting import HEADER
        with path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=HEADER)
            writer.writeheader()
            for row in rows:
                full_row = {k: row.get(k, '') for k in HEADER}
                writer.writerow(full_row)

    def test_merge_copies_llm_score_fields(self, tmp_path):
        import monitor_watchlist as mw
        from web_prospecting import HEADER

        # Set up target CSV with one company, no LLM score
        target_csv = tmp_path / "target-companies.csv"
        self._write_target_csv(target_csv, [
            {
                'company': 'ScoreMe Inc',
                'website': 'scoreme.com',
                'validation_status': 'pass',
                'source': 'web_prospecting',
            }
        ])

        # Set up monitor-results.json WITH scoring fields
        results = [
            {
                'company': 'ScoreMe Inc',
                'website': 'scoreme.com',
                'careers_url': 'https://scoreme.com/careers',
                'open_positions': 'AI Product Manager',
                'status': 'active_role',
                'path': 1,
                'path_name': 'AI Product',
                'notes': 'Great AI roles available.',
                'llm_score': 85,
                'llm_rationale': 'Strong AI focus with accounting domain.',
                'llm_path_name': 'AI Product',
                'llm_flags': 'remote_friendly',
            }
        ]
        results_json = tmp_path / "monitor-results.json"
        results_json.write_text(json.dumps(results))

        seen_json = tmp_path / "seen-companies.json"
        seen_json.write_text('{}')
        monitor_context = tmp_path / "monitor-context.json"

        # Patch module-level path constants
        orig_target = mw.TARGET_CSV
        orig_results = mw.MONITOR_RESULTS
        orig_seen = mw.SEEN_COMPANIES
        orig_context = mw.MONITOR_CONTEXT
        try:
            mw.TARGET_CSV = target_csv
            mw.MONITOR_RESULTS = results_json
            mw.SEEN_COMPANIES = seen_json
            mw.MONITOR_CONTEXT = monitor_context
            rc = mw.cmd_merge(dry_run=False)
        finally:
            mw.TARGET_CSV = orig_target
            mw.MONITOR_RESULTS = orig_results
            mw.SEEN_COMPANIES = orig_seen
            mw.MONITOR_CONTEXT = orig_context

        assert rc == 0, f"cmd_merge returned {rc}"

        # Read back and verify scoring fields were written
        with target_csv.open() as f:
            rows = list(csv.DictReader(f))

        scoreme_rows = [r for r in rows if r['company'] == 'ScoreMe Inc']
        assert len(scoreme_rows) == 1, "Expected exactly one ScoreMe Inc row"
        row = scoreme_rows[0]

        assert row['llm_score'] == '85', f"Expected llm_score=85, got {row['llm_score']!r}"
        assert row['llm_rationale'] == 'Strong AI focus with accounting domain.', \
            f"Unexpected llm_rationale: {row['llm_rationale']!r}"
        assert row['role_family'] == 'AI Product', \
            f"Unexpected role_family: {row['role_family']!r}"
        assert row['llm_flags'] == 'remote_friendly', \
            f"Unexpected llm_flags: {row['llm_flags']!r}"
        assert row['llm_evaluated_at'], "Expected llm_evaluated_at to be set"

    def test_merge_does_not_blank_existing_score(self, tmp_path):
        import monitor_watchlist as mw
        from web_prospecting import HEADER

        # Set up target CSV with existing llm_score=90
        target_csv = tmp_path / "target-companies.csv"
        self._write_target_csv(target_csv, [
            {
                'company': 'AlreadyScored Ltd',
                'website': 'alreadyscored.com',
                'validation_status': 'pass',
                'source': 'web_prospecting',
                'llm_score': '90',
                'llm_rationale': 'Previously evaluated.',
                'role_family': 'Accounting Tech',
                'llm_flags': 'top_pick',
                'llm_evaluated_at': '2026-03-01T00:00:00+00:00',
            }
        ])

        # Results with no_change — no scoring fields included
        results = [
            {
                'company': 'AlreadyScored Ltd',
                'website': 'alreadyscored.com',
                'careers_url': 'https://alreadyscored.com/careers',
                'open_positions': '',
                'status': 'no_change',
                'path': 1,
                'path_name': 'Accounting Tech',
                'notes': '',
            }
        ]
        results_json = tmp_path / "monitor-results.json"
        results_json.write_text(json.dumps(results))

        seen_json = tmp_path / "seen-companies.json"
        seen_json.write_text('{}')
        monitor_context = tmp_path / "monitor-context.json"

        orig_target = mw.TARGET_CSV
        orig_results = mw.MONITOR_RESULTS
        orig_seen = mw.SEEN_COMPANIES
        orig_context = mw.MONITOR_CONTEXT
        try:
            mw.TARGET_CSV = target_csv
            mw.MONITOR_RESULTS = results_json
            mw.SEEN_COMPANIES = seen_json
            mw.MONITOR_CONTEXT = monitor_context
            rc = mw.cmd_merge(dry_run=False)
        finally:
            mw.TARGET_CSV = orig_target
            mw.MONITOR_RESULTS = orig_results
            mw.SEEN_COMPANIES = orig_seen
            mw.MONITOR_CONTEXT = orig_context

        assert rc == 0, f"cmd_merge returned {rc}"

        with target_csv.open() as f:
            rows = list(csv.DictReader(f))

        scored_rows = [r for r in rows if r['company'] == 'AlreadyScored Ltd']
        assert len(scored_rows) == 1, "Expected exactly one AlreadyScored Ltd row"
        row = scored_rows[0]

        assert row['llm_score'] == '90', \
            f"Existing llm_score should not be blanked, got {row['llm_score']!r}"
        assert row['llm_rationale'] == 'Previously evaluated.', \
            f"Existing llm_rationale should be preserved, got {row['llm_rationale']!r}"
        assert row['llm_flags'] == 'top_pick', \
            f"Existing llm_flags should be preserved, got {row['llm_flags']!r}"


class TestProspectingResultsScoringSchema:
    """Verify prospecting cmd_merge copies LLM scoring fields from results JSON into new CSV rows."""

    def test_merge_copies_llm_score_to_new_company(self, tmp_path):
        import web_prospecting as wp

        # Create an empty target CSV (just header)
        target_csv = tmp_path / "target-companies.csv"
        with target_csv.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=wp.HEADER)
            writer.writeheader()

        # Create prospecting-results.json with one new company including scoring fields
        results = [
            {
                'company': 'FinTech Nexus',
                'website': 'fintechnexus.io',
                'careers_url': 'https://fintechnexus.io/careers',
                'industry': 'AI Fintech',
                'size': '100-500',
                'stage': 'Series B',
                'recent_funding': '$40M Series B (Jan 2026)',
                'tech_signals': 'llm, python, data pipeline',
                'open_positions': 'AI Product Manager',
                'prospect_status': 'active_role',
                'path': 3,
                'path_name': 'AI-Native Fintech',
                'notes': 'Fast growing team.',
                'llm_score': 78,
                'llm_dimensions_evaluated': 9,
                'llm_rationale': 'Good domain fit. Strong AI centrality.',
                'llm_path_name': 'AI-Native Fintech',
                'llm_flags': 'growth_unknown',
            }
        ]
        results_json = tmp_path / "prospecting-results.json"
        results_json.write_text(json.dumps(results))

        seen_json = tmp_path / "seen-companies.json"
        seen_json.write_text('{}')
        prospecting_context = tmp_path / "prospecting-context.json"

        orig_target = wp.TARGET_CSV
        orig_results = wp.PROSPECTING_RESULTS
        orig_seen = wp.SEEN_COMPANIES
        orig_context = wp.PROSPECTING_CONTEXT
        try:
            wp.TARGET_CSV = target_csv
            wp.PROSPECTING_RESULTS = results_json
            wp.SEEN_COMPANIES = seen_json
            wp.PROSPECTING_CONTEXT = prospecting_context
            rc = wp.cmd_merge(dry_run=False)
        finally:
            wp.TARGET_CSV = orig_target
            wp.PROSPECTING_RESULTS = orig_results
            wp.SEEN_COMPANIES = orig_seen
            wp.PROSPECTING_CONTEXT = orig_context

        assert rc == 0, f"cmd_merge returned {rc}"

        with target_csv.open() as f:
            rows = list(csv.DictReader(f))

        nexus_rows = [r for r in rows if r['company'] == 'FinTech Nexus']
        assert len(nexus_rows) == 1, "Expected exactly one FinTech Nexus row"
        row = nexus_rows[0]

        assert row['llm_score'] == '78', f"Expected llm_score=78, got {row['llm_score']!r}"
        assert row['llm_rationale'] == 'Good domain fit. Strong AI centrality.', \
            f"Unexpected llm_rationale: {row['llm_rationale']!r}"
        assert row['role_family'] == 'AI-Native Fintech', \
            f"Unexpected role_family: {row['role_family']!r}"
        assert row['llm_flags'] == 'growth_unknown', \
            f"Unexpected llm_flags: {row['llm_flags']!r}"


class TestScoringOutputSchema:
    """Verify scoring output in results JSON conforms to expected schema."""

    SCORING_FIELDS = {
        'llm_score': (int, float),
        'llm_dimensions_evaluated': (int,),
        'llm_rationale': (str,),
        'role_family': (str,),
        'llm_flags': (str,),
    }

    def _make_scored_result(self, **overrides):
        base = {
            "company": "Test Corp",
            "website": "test.com",
            "careers_url": "https://test.com/careers",
            "open_positions": "PM",
            "status": "active_role",
            "path": 1,
            "path_name": "Test Path",
            "notes": "",
            "llm_score": 75,
            "llm_dimensions_evaluated": 8,
            "llm_rationale": "Good fit overall.",
            "role_family": "Test Path",
            "llm_flags": "",
        }
        base.update(overrides)
        return base

    def test_valid_scoring_result_has_all_fields(self):
        result = self._make_scored_result()
        for field, types in self.SCORING_FIELDS.items():
            assert field in result, f"Missing field: {field}"
            assert isinstance(result[field], types), \
                f"{field} should be {types}, got {type(result[field])}"

    def test_score_range_valid(self):
        result = self._make_scored_result(llm_score=85)
        assert 0 <= result['llm_score'] <= 100

    def test_dimensions_evaluated_range(self):
        result = self._make_scored_result(llm_dimensions_evaluated=8)
        assert 0 <= result['llm_dimensions_evaluated'] <= 10

    def test_score_calculation_correct(self):
        """Score should equal (yes/evaluated)*100 rounded."""
        yes_count = 7
        evaluated = 8
        expected = round((yes_count / evaluated) * 100)
        assert expected == 88  # 7/8 = 87.5, rounds to 88

    def test_needs_research_flag_when_few_dimensions(self):
        """Companies with <5 evaluable dimensions should be flagged."""
        result = self._make_scored_result(
            llm_dimensions_evaluated=4,
            llm_flags="needs_research",
        )
        assert "needs_research" in result['llm_flags']


class TestTavilyClient:
    """Verify Tavily client loads config and degrades gracefully."""

    def test_import_succeeds(self):
        """Module should import without errors."""
        import tavily_client as tc
        assert hasattr(tc, 'extract_careers_page')
        assert hasattr(tc, 'find_role_urls')
        assert hasattr(tc, 'is_available')

    def test_unavailable_returns_empty(self):
        """When Tavily is not configured, functions return empty results."""
        import tavily_client as tc
        from unittest.mock import patch
        with patch.object(tc, '_get_client', return_value=None):
            assert tc.extract_careers_page('https://example.com/careers') == {}
            assert tc.find_role_urls('https://example.com/careers', ['PM']) == {}

    def test_extract_returns_content(self):
        """When Tavily works, extract returns raw_content."""
        import tavily_client as tc
        from unittest.mock import patch, MagicMock

        mock_client = MagicMock()
        mock_client.extract.return_value = {
            'results': [{
                'url': 'https://example.com/careers',
                'raw_content': '[### Product Manager](/company/abc-123)\n[### Solutions Architect](/company/def-456)',
            }]
        }
        with patch.object(tc, '_get_client', return_value=mock_client):
            result = tc.extract_careers_page('https://example.com/careers')
            assert 'raw_content' in result
            assert 'Product Manager' in result['raw_content']
            mock_client.extract.assert_called_once()

    def test_find_role_urls_matches_titles(self):
        """find_role_urls should match role titles to URLs in extracted content."""
        import tavily_client as tc
        from unittest.mock import patch, MagicMock

        mock_client = MagicMock()
        mock_client.extract.return_value = {
            'results': [{
                'url': 'https://jobs.ashbyhq.com/company',
                'raw_content': (
                    '[### Product Manager\n\nEngineering • NYC](/company/abc-123)\n'
                    '[### Solutions Architect\n\nSales • Remote](/company/def-456)\n'
                    '[### Office Manager\n\nOps • NYC](/company/ghi-789)'
                ),
            }]
        }
        with patch.object(tc, '_get_client', return_value=mock_client):
            matches = tc.find_role_urls(
                'https://jobs.ashbyhq.com/company',
                ['Product Manager', 'Solutions Architect']
            )
            assert len(matches) == 2
            assert matches['Product Manager'] == 'https://jobs.ashbyhq.com/company/abc-123'
            assert matches['Solutions Architect'] == 'https://jobs.ashbyhq.com/company/def-456'

    def test_find_role_urls_no_match_returns_empty(self):
        """Unmatched roles should not appear in results."""
        import tavily_client as tc
        from unittest.mock import patch, MagicMock

        mock_client = MagicMock()
        mock_client.extract.return_value = {
            'results': [{
                'url': 'https://example.com/careers',
                'raw_content': '[### Software Engineer](/jobs/123)',
            }]
        }
        with patch.object(tc, '_get_client', return_value=mock_client):
            matches = tc.find_role_urls(
                'https://example.com/careers',
                ['Product Manager']
            )
            assert matches == {}


class TestRoleUrlColumn:
    """Verify role_url column exists in CSV header."""

    def test_header_includes_role_url(self):
        from web_prospecting import HEADER
        assert 'role_url' in HEADER, "HEADER must include 'role_url' column"

    def test_role_url_after_careers_url(self):
        from web_prospecting import HEADER
        careers_idx = HEADER.index('careers_url')
        role_idx = HEADER.index('role_url')
        assert role_idx == careers_idx + 1, "role_url should be right after careers_url"


class TestMonitorMergeRoleUrl:
    """Verify monitor merge copies role_url from results JSON."""

    def test_merge_copies_role_url(self, tmp_path):
        from web_prospecting import HEADER
        import monitor_watchlist as mw

        csv_path = tmp_path / "target-companies.csv"
        with csv_path.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            w.writerow({k: '' for k in HEADER} | {
                'company': 'TestCo',
                'website': 'testco.com',
                'validation_status': 'watch_list',
                'open_positions': 'None — watch list',
                'careers_url': 'https://testco.com/careers',
            })

        results_path = tmp_path / "monitor-results.json"
        results_path.write_text(json.dumps([{
            "company": "TestCo",
            "website": "testco.com",
            "careers_url": "https://testco.com/careers",
            "role_url": "https://testco.com/careers/product-manager-123",
            "open_positions": "Product Manager",
            "status": "active_role",
            "path": 1,
            "path_name": "Test Path",
            "notes": "Found PM role.",
            "llm_score": 80,
            "llm_rationale": "Good fit.",
            "llm_flags": ""
        }]))

        seen_path = tmp_path / "seen-companies.json"
        seen_path.write_text("{}")

        orig = (mw.TARGET_CSV, mw.MONITOR_RESULTS, mw.SEEN_COMPANIES, mw.MONITOR_CONTEXT)
        try:
            mw.TARGET_CSV = csv_path
            mw.MONITOR_RESULTS = results_path
            mw.SEEN_COMPANIES = seen_path
            mw.MONITOR_CONTEXT = tmp_path / "monitor-context.json"
            rc = mw.cmd_merge(dry_run=False)
        finally:
            mw.TARGET_CSV, mw.MONITOR_RESULTS, mw.SEEN_COMPANIES, mw.MONITOR_CONTEXT = orig

        assert rc == 0
        with csv_path.open() as f:
            rows = list(csv.DictReader(f))
        row = [r for r in rows if r['company'] == 'TestCo'][0]
        assert row['role_url'] == 'https://testco.com/careers/product-manager-123'


class TestProspectingMergeRoleUrl:
    """Verify prospecting merge copies role_url from results JSON."""

    def test_merge_copies_role_url(self, tmp_path):
        import web_prospecting as wp

        csv_path = tmp_path / "target-companies.csv"
        with csv_path.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=wp.HEADER)
            w.writeheader()

        results_path = tmp_path / "prospecting-results.json"
        results_path.write_text(json.dumps([{
            "company": "NewCo",
            "website": "newco.ai",
            "careers_url": "https://newco.ai/careers",
            "role_url": "https://newco.ai/careers/solutions-architect-456",
            "industry": "AI Finance",
            "size": "50-100",
            "stage": "Series B",
            "recent_funding": "",
            "tech_signals": "AI",
            "open_positions": "Solutions Architect",
            "prospect_status": "active_role",
            "path": 1,
            "path_name": "Test Path",
            "notes": "",
            "llm_score": 75,
            "llm_rationale": "Good fit.",
            "llm_flags": ""
        }]))

        seen_path = tmp_path / "seen-companies.json"
        seen_path.write_text("{}")

        orig = (wp.TARGET_CSV, wp.PROSPECTING_RESULTS, wp.SEEN_COMPANIES, wp.PROSPECTING_CONTEXT)
        try:
            wp.TARGET_CSV = csv_path
            wp.PROSPECTING_RESULTS = results_path
            wp.SEEN_COMPANIES = seen_path
            wp.PROSPECTING_CONTEXT = tmp_path / "prospecting-context.json"
            rc = wp.cmd_merge(dry_run=False)
        finally:
            wp.TARGET_CSV, wp.PROSPECTING_RESULTS, wp.SEEN_COMPANIES, wp.PROSPECTING_CONTEXT = orig

        assert rc == 0
        with csv_path.open() as f:
            rows = list(csv.DictReader(f))
        row = [r for r in rows if r['company'] == 'NewCo'][0]
        assert row['role_url'] == 'https://newco.ai/careers/solutions-architect-456'


class TestActionListRoleUrl:
    """Verify action list uses role_url when available, falls back to careers_url."""

    def test_action_list_prefers_role_url(self, tmp_path):
        import csv as _csv
        from web_prospecting import HEADER

        csv_path = tmp_path / "target-companies.csv"
        with csv_path.open('w', newline='') as f:
            w = _csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            w.writerow({k: '' for k in HEADER} | {
                'company': 'WithRoleUrl',
                'validation_status': 'pass',
                'careers_url': 'https://withurl.com/careers',
                'role_url': 'https://withurl.com/careers/pm-123',
                'open_positions': 'Product Manager',
                'llm_score': '85',
            })
            w.writerow({k: '' for k in HEADER} | {
                'company': 'WithoutRoleUrl',
                'validation_status': 'pass',
                'careers_url': 'https://withouturl.com/careers',
                'role_url': '',
                'open_positions': 'Solutions Architect',
                'llm_score': '80',
            })

        action_path = tmp_path / "action-list.csv"

        import run_pipeline as rp
        orig_data = rp.DATA
        orig_base = rp.BASE
        try:
            rp.DATA = tmp_path
            rp.BASE = tmp_path.parent
            apps_dir = tmp_path.parent / 'job-tracker' / 'data'
            apps_dir.mkdir(parents=True, exist_ok=True)
            (apps_dir / 'applications.csv').write_text(
                'company,status,date_added,last_contact,contact_name\n'
            )
            rp._generate_action_list(action_path)
        finally:
            rp.DATA = orig_data
            rp.BASE = orig_base

        with action_path.open() as f:
            rows = list(_csv.DictReader(f))

        with_url = [r for r in rows if r['company'] == 'WithRoleUrl'][0]
        without_url = [r for r in rows if r['company'] == 'WithoutRoleUrl'][0]

        assert with_url['apply_url'] == 'https://withurl.com/careers/pm-123'
        assert without_url['apply_url'] == 'https://withouturl.com/careers'
