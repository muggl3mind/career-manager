"""
Single source of truth for target-companies.csv column schema.

All scripts that read/write target-companies.csv must import HEADER from here.
This prevents column drift between scripts (e.g., one script dropping role_url).
"""

HEADER = [
    'rank', 'company', 'website', 'careers_url', 'role_url',
    'industry', 'size', 'stage', 'recent_funding',
    'tech_signals', 'open_positions', 'last_checked',
    'notes', 'role_family', 'source',
    'location_detected', 'validation_status', 'exclusion_reason',
    'llm_score', 'llm_rationale', 'llm_flags',
    'llm_hard_pass', 'llm_hard_pass_reason', 'llm_evaluated_at',
    'lifecycle_state', 'last_verified_at', 'watching_run_count',
]
