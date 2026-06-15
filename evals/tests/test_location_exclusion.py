"""Location-exclude scoping tests (finding M1).

The location-exclude regex used to run over title + description +
location, so a US-remote job whose description mentioned "our London
office" was rejected as excluded_location. The exclusion is now scoped
to the location field only via discovery_pipeline.location_excluded().
"""
import inspect
import re
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'
sys.path.insert(0, str(OPS))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))

import discovery_pipeline as dp

EXCLUDE_PAT = dp._build_regex(['london', 'united kingdom', r'\bUK\b', 'berlin'])


class TestLocationExcluded:
    def test_excluded_location_field_matches(self):
        assert dp.location_excluded('London, United Kingdom', EXCLUDE_PAT)
        assert dp.location_excluded('Berlin', EXCLUDE_PAT)

    def test_us_location_passes(self):
        assert not dp.location_excluded('New York, NY', EXCLUDE_PAT)
        assert not dp.location_excluded('Remote, US', EXCLUDE_PAT)

    def test_empty_location_passes(self):
        assert not dp.location_excluded('', EXCLUDE_PAT)
        assert not dp.location_excluded(None, EXCLUDE_PAT)

    def test_regression_m1_description_mention_does_not_reject(self):
        """A US job whose description mentions a London office must pass.

        The old code searched f"{title} {desc} {location}". The fix only
        ever sees the location field, so the description text cannot
        trigger the exclusion.
        """
        title = 'Senior Product Manager'
        desc = 'US-remote role. You will occasionally visit our London office.'
        location = 'Remote, United States'
        old_text = f'{title} {desc} {location}'
        # The old behavior was broken:
        assert EXCLUDE_PAT.search(old_text) is not None
        # The scoped check is correct:
        assert not dp.location_excluded(location, EXCLUDE_PAT)

    def test_default_pattern_is_module_config(self):
        # With no explicit pattern the module-level NON_US_PAT is used.
        assert dp.location_excluded('x', None) == bool(dp.NON_US_PAT.search('x'))


class TestMainWiring:
    def test_main_gates_on_location_field_only(self):
        """main() must call location_excluded on the location field, never run
        the exclude regex over the combined title+desc+location text."""
        src = inspect.getsource(dp.main)
        assert "location_excluded(d.get('location'" in src
        assert 'NON_US_PAT.search(text)' not in src
