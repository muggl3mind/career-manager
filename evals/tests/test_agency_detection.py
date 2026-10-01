"""Verify baseline staffing agency detection catches recruiter firms
even when user config doesn't list them."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(ROOT / 'job-search' / 'scripts' / 'core'))


# Real recruiter/agency names that slipped past the previous detector
# in production runs. Each of these has hidden the real employer behind
# a reposted job listing at least once, so the baseline detector must
# treat them as agencies regardless of user config.
KNOWN_AGENCIES = [
    "Resourceful Talent Group",
    "Spectrum Search",
    "Epic Placements",
    "Pivotal Partners",
    "Green Key Resources",
    "Selby Jennings",
    "Nicholson Glover",
    "David Joseph & Co",
    "Lawrence Harvey",
    "People In AI",
    "Robert Half",
    "Michael Page",
    "Randstad",
    "Medilinkers",
    "Talent Partners Inc",
    "Executive Search Group",
]

REAL_EMPLOYERS = [
    "Anthropic",
    "OpenAI",
    "Hebbia",
    "Basis",
    "Ramp",
    "BlackRock",
    "Charles Schwab",
    "Snowflake",
    "Kraken",
    "Alteryx",
    "Cresta",
    "Databricks",
]


def test_baseline_agency_detects_known_recruiters():
    """The baseline detector fires on well-known staffing firms even
    without any user agency_patterns configured."""
    import discovery_pipeline as dp
    for name in KNOWN_AGENCIES:
        assert dp.AGENCY_DETECT.search(name), (
            f"expected {name!r} to be flagged as agency by the baseline "
            f"detector, but AGENCY_DETECT.search({name!r}) returned None"
        )


def test_baseline_agency_does_not_flag_real_employers():
    """The baseline detector must not false-positive on real target
    companies. If any real employer trips the regex, tighten the
    pattern rather than accept the false positive."""
    import discovery_pipeline as dp
    for name in REAL_EMPLOYERS:
        assert not dp.AGENCY_DETECT.search(name), (
            f"real employer {name!r} was falsely flagged as an agency; "
            f"tighten the baseline pattern"
        )


def test_user_patterns_extend_baseline(monkeypatch):
    """User-provided agency_patterns are additive, not replace-only.
    Loading a config with an extra pattern should still flag all
    baseline names."""
    import discovery_pipeline as dp
    # Baseline still fires
    assert dp.AGENCY_DETECT.search("Robert Half")
    # And extending would fire on the extension too (verify via a
    # manually-built regex using the same _build_regex helper).
    user_extra = ["hyper niche recruiters"]
    combined = dp._build_regex(dp._BASELINE_AGENCY_PATTERNS + user_extra)
    assert combined.search("Hyper Niche Recruiters")
    assert combined.search("Robert Half")
