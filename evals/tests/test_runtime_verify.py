"""Tests for runtime pipeline verification."""
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'evals' / 'scripts'))

from runtime_verify import check_action_list_matches_opportunities


def test_action_list_sync_accepts_company_rows_with_multiple_roles():
    opportunities = [
        {
            'company': 'OpenAI',
            'role_title': 'Solutions Architect',
            'opportunity_status': 'open',
        },
        {
            'company': 'OpenAI',
            'role_title': 'Backend Engineer',
            'opportunity_status': 'open',
        },
    ]
    action_rows = [
        {
            'company': 'OpenAI',
            'role': 'Backend Engineer; Solutions Architect',
        }
    ]

    checks = check_action_list_matches_opportunities(opportunities, action_rows)

    assert checks[0]['check'] == 'action_list_sync'
    assert checks[0]['status'] == 'pass'
