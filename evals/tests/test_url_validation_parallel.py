"""Parallel URL validation tests (fix plan Phase 3, item 16).

discovery_pipeline used to validate careers URLs one at a time over the
network. check_urls() now fans the per-URL validator out over a bounded
thread pool while preserving input order and isolating failures per URL.
No test here touches the network; every test injects a stubbed validator.
"""
import inspect
import sys
import threading
import time
from pathlib import Path

OPS = Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'
sys.path.insert(0, str(OPS))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))

import discovery_pipeline as dp


class TestOrderPreservation:
    def test_results_align_with_input_order(self):
        """Early URLs sleep longest, so completion order is reversed.
        Results must still come back in input order."""
        urls = [f'https://example.com/{i}' for i in range(10)]
        delays = {u: (len(urls) - i) * 0.01 for i, u in enumerate(urls)}

        def validator(u):
            time.sleep(delays[u])
            return True, f'checked:{u}'

        results = dp.check_urls(urls, max_workers=8, validator=validator)
        assert results == [(True, f'checked:{u}') for u in urls]

    def test_empty_input_returns_empty_list(self):
        assert dp.check_urls([]) == []

    def test_validator_called_exactly_once_per_url(self):
        lock = threading.Lock()
        calls = []
        urls = [f'https://example.com/{i}' for i in range(7)]

        def validator(u):
            with lock:
                calls.append(u)
            return False, 'link_bad_404'

        results = dp.check_urls(urls, validator=validator)
        assert sorted(calls) == sorted(urls)
        assert results == [(False, 'link_bad_404')] * len(urls)


class TestErrorIsolation:
    def test_one_crashing_url_does_not_affect_others(self):
        urls = ['https://ok-1', 'https://boom', 'https://ok-2']

        def validator(u):
            if u == 'https://boom':
                raise RuntimeError('validator crashed')
            return True, ''

        results = dp.check_urls(urls, validator=validator)
        assert results == [(True, ''), (False, 'link_error'), (True, '')]

    def test_all_urls_crashing_yields_link_error_for_each(self):
        def validator(u):
            raise ValueError('always crashes')

        results = dp.check_urls(['https://a', 'https://b'], validator=validator)
        assert results == [(False, 'link_error'), (False, 'link_error')]


class TestBoundedConcurrency:
    def test_worker_bound_respected(self):
        lock = threading.Lock()
        active = 0
        peak = 0

        def validator(u):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return True, ''

        urls = [f'https://example.com/{i}' for i in range(12)]
        dp.check_urls(urls, max_workers=3, validator=validator)
        assert peak <= 3


class TestWiring:
    def test_default_validator_is_check_url(self, monkeypatch):
        seen = []

        def fake_check_url(u):
            seen.append(u)
            return True, ''

        monkeypatch.setattr(dp, 'check_url', fake_check_url)
        assert dp.check_urls(['https://x']) == [(True, '')]
        assert seen == ['https://x']

    def test_main_routes_urls_through_thread_pool(self):
        """main() must validate URLs via check_urls, never by calling
        check_url inline one row at a time."""
        src = inspect.getsource(dp.main)
        assert 'check_urls(' in src
        assert 'check_url(url)' not in src
