"""Link-check policy tests.

LinkedIn answers a burst of link checks with HTTP 429, and the pipeline
used to read that as a dead link. In one run that discarded 270 jobs that
had already passed the title and location gates.

Two changes cover it:
- A job the scraper returned with a full description was loaded moments
  ago, so its link is not checked again (needs_link_check).
- check_url retries a 429 after a pause instead of failing on the first one.

No test here touches the network.
"""
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'
sys.path.insert(0, str(OPS))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))

import discovery_pipeline as dp


class _Resp:
    def __init__(self, code, headers=None):
        self.status_code = code
        self.headers = headers or {}


def _stub_get(monkeypatch, codes, headers=None):
    calls = []
    seq = list(codes)

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Resp(seq.pop(0), headers)

    monkeypatch.setattr(dp.requests, 'get', fake_get)
    return calls


def _no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(dp.time, 'sleep', lambda s: slept.append(s))
    return slept


class TestNeedsLinkCheck:
    def test_scraped_description_skips_check(self):
        assert dp.needs_link_check({'desc': 'x' * 500}) is False

    def test_missing_description_needs_check(self):
        assert dp.needs_link_check({'desc': ''}) is True
        assert dp.needs_link_check({}) is True

    def test_stub_description_needs_check(self):
        """A few words is not evidence the page loaded."""
        assert dp.needs_link_check({'desc': 'Apply now'}) is True


class TestCheckUrlRateLimit:
    def test_429_then_200_passes(self, monkeypatch):
        slept = _no_sleep(monkeypatch)
        calls = _stub_get(monkeypatch, [429, 200])
        assert dp.check_url('https://www.linkedin.com/jobs/view/1') == (True, '')
        assert len(calls) == 2
        assert len(slept) == 1

    def test_persistent_429_still_fails(self, monkeypatch):
        _no_sleep(monkeypatch)
        calls = _stub_get(monkeypatch, [429] * 10)
        assert dp.check_url('https://x') == (False, 'link_bad_429')
        assert len(calls) == dp.RATE_LIMIT_RETRIES + 1

    def test_retry_after_header_is_honored_and_capped(self, monkeypatch):
        slept = _no_sleep(monkeypatch)
        _stub_get(monkeypatch, [429, 200], headers={'Retry-After': '3'})
        dp.check_url('https://x')
        assert slept == [3.0]

        slept.clear()
        _stub_get(monkeypatch, [429, 200], headers={'Retry-After': '9999'})
        dp.check_url('https://x')
        assert slept == [dp.RATE_LIMIT_MAX_WAIT]

    def test_404_fails_without_retry(self, monkeypatch):
        slept = _no_sleep(monkeypatch)
        calls = _stub_get(monkeypatch, [404])
        assert dp.check_url('https://x') == (False, 'link_bad_404')
        assert len(calls) == 1
        assert slept == []


class TestWiring:
    def test_main_gates_checks_on_needs_link_check(self):
        import inspect
        assert 'needs_link_check(' in inspect.getsource(dp.main)
