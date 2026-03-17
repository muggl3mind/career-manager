"""
Single source of truth for target-companies.csv column schema.

All scripts that read/write target-companies.csv must import HEADER from here.
This prevents column drift between scripts (e.g., one script dropping role_url).
"""

HEADER = [
    'rank', 'company', 'website', 'careers_url', 'role_url', 'industry', 'size', 'stage', 'recent_funding',
    'tech_signals', 'open_positions', 'fit_score', 'fit_rationale', 'last_checked',
    'notes', 'numeric_score', 'score_breakdown', 'role_family', 'source',
    'source_tier', 'location_detected', 'validation_status', 'exclusion_reason',
    'llm_score', 'llm_path', 'llm_path_name', 'llm_rationale', 'llm_flags',
    'llm_cv_template', 'llm_hard_pass', 'llm_hard_pass_reason', 'llm_evaluated_at',
]
