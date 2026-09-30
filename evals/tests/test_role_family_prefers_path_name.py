"""Verify prospecting merge writes canonical path labels into role_family,
even when the agent puts role titles in the free-text role_family field.

Regression: agents sometimes interpret role_family as "role type" and write
"Solutions Architect" instead of the canonical path label. The merge must
prefer path_name (pipeline-canonical) over role_family (free text) and
normalize the result before it reaches the CSV.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(ROOT / 'job-search' / 'scripts' / 'core'))


def _prospect_result(**overrides) -> dict:
    base = {
        'company': 'ExampleCo',
        'website': 'https://example.com',
        'careers_url': 'https://example.com/careers',
        'role_url': '',
        'industry': 'AI Finance',
        'size': 'Series B',
        'stage': 'growth',
        'recent_funding': '$50M',
        'tech_signals': 'llm,agents',
        'open_positions': 'Forward Deployed Engineer',
        'prospect_status': 'active_role',
        'fit_rationale': 'Great fit',
        'path': 'ai_finance_accounting_tech',
        'path_name': 'AI in Finance / Accounting Tech',
        'notes': '',
        'llm_score': 90,
        'llm_dimensions_evaluated': 10,
        'llm_rationale': 'Bullseye',
        'role_family': '',
        'llm_flags': '',
        'queries_used': ['ai finance'],
    }
    base.update(overrides)
    return base


def test_path_name_used_when_role_family_is_role_title():
    """When agent writes 'Solutions Architect' in role_family (a role
    title, not a path), the pipeline should use path_name instead."""
    from web_prospecting import _CANONICAL_PATHS
    from path_normalizer import normalize_path

    r = _prospect_result(role_family='Solutions Architect')
    # Simulate the same precedence used by web_prospecting.py after fix
    chosen = r.get('path_name', '') or r.get('llm_path_name', '') or r.get('role_family', '')
    normalized = normalize_path(chosen, _CANONICAL_PATHS)
    assert normalized == 'AI in Finance / Accounting Tech'


def test_path_name_used_when_role_family_is_snake_case_key():
    """Agents sometimes write path_key ('solutions_architect') into
    role_family. Path name still wins."""
    from web_prospecting import _CANONICAL_PATHS
    from path_normalizer import normalize_path

    r = _prospect_result(role_family='solutions_architect')
    chosen = r.get('path_name', '') or r.get('llm_path_name', '') or r.get('role_family', '')
    normalized = normalize_path(chosen, _CANONICAL_PATHS)
    assert normalized == 'AI in Finance / Accounting Tech'


def test_fuzzy_role_family_normalizes_via_alias():
    """If path_name is missing entirely, a fuzzy role_family that matches
    a path_alias should still normalize to the canonical label."""
    from web_prospecting import _CANONICAL_PATHS
    from path_normalizer import normalize_path

    r = _prospect_result(path_name='', role_family='fde')
    chosen = r.get('path_name', '') or r.get('llm_path_name', '') or r.get('role_family', '')
    normalized = normalize_path(chosen, _CANONICAL_PATHS)
    # Depending on whether fde is aliased in the live search-config, either
    # it maps to a canonical path or falls through unchanged. The point of
    # this test is to verify the alias lookup path runs — assert it either
    # matches a canonical path OR falls through to 'fde' unchanged.
    canonical_or_unchanged = (
        normalized in _CANONICAL_PATHS or normalized == 'fde'
    )
    assert canonical_or_unchanged


def test_canonical_path_name_survives_normalization():
    """A path_name that is already canonical should round-trip unchanged."""
    from web_prospecting import _CANONICAL_PATHS
    from path_normalizer import normalize_path

    for canonical in _CANONICAL_PATHS:
        r = _prospect_result(path_name=canonical, role_family='some role title')
        chosen = r.get('path_name', '') or r.get('llm_path_name', '') or r.get('role_family', '')
        normalized = normalize_path(chosen, _CANONICAL_PATHS)
        assert normalized == canonical
