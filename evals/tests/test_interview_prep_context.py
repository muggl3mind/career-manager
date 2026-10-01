"""Tests for interview-prep/scripts/build_prep_context.py — graceful-degradation context builder."""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'interview-prep' / 'scripts'))
from build_prep_context import build_context, slugify


def _make_root(tmp_path: Path) -> Path:
    """Empty repo skeleton — no data anywhere."""
    for d in ['company-research/dossiers', 'job-tracker/data',
              'job-search/data', 'cv-tailor/data/CV', 'interview-prep/preps']:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_apps_csv(root: Path, rows: list[dict]):
    path = root / 'job-tracker/data/applications.csv'
    headers = ['company', 'role', 'status', 'priority', 'last_contact', 'notes']
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_opps_csv(root: Path, rows: list[dict]):
    path = root / 'job-search/data/opportunities.csv'
    headers = ['opportunity_key', 'company', 'role_title', 'role_url',
               'opportunity_status', 'llm_score', 'role_family', 'fit_summary', 'notes']
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


class TestSlugify:
    def test_basic(self):
        assert slugify('Allvue Systems') == 'allvue-systems'

    def test_punctuation(self):
        assert slugify('C3.ai, Inc.') == 'c3-ai-inc'


class TestAllMissing:
    def test_runs_and_reports_gaps(self, tmp_path):
        root = _make_root(tmp_path)
        summary = build_context('Ghost Corp', root)
        assert summary['company'] == 'Ghost Corp'
        assert summary['found'] == {'dossier': False, 'tracker': False,
                                    'opportunities': False, 'base_cv': False}
        out = Path(summary['output_path'])
        assert out.exists()
        text = out.read_text(encoding='utf-8')
        assert text.count('MISSING') >= 4

    def test_missing_data_dirs_dont_crash(self, tmp_path):
        # Only the output dir exists — every source dir absent entirely.
        (tmp_path / 'interview-prep/preps').mkdir(parents=True)
        summary = build_context('Ghost Corp', tmp_path)
        assert summary['found']['dossier'] is False


class TestPartialSources:
    def test_dossier_and_tracker_found(self, tmp_path):
        root = _make_root(tmp_path)
        (root / 'company-research/dossiers/Allvue Systems.md').write_text(
            '# Allvue Systems\n\nGreat company.', encoding='utf-8')
        _write_apps_csv(root, [
            {'company': 'Allvue Systems', 'role': 'Solutions Architect',
             'status': 'interviewing', 'priority': '1',
             'last_contact': '2026-09-20', 'notes': 'phone screen done'},
            {'company': 'Other Co', 'role': 'PM', 'status': 'applied',
             'priority': '2', 'last_contact': '', 'notes': ''},
        ])
        summary = build_context('Allvue Systems', root)
        assert summary['found']['dossier'] is True
        assert summary['found']['tracker'] is True
        assert summary['found']['opportunities'] is False
        text = Path(summary['output_path']).read_text(encoding='utf-8')
        assert 'Great company.' in text
        assert 'interviewing' in text
        assert 'Other Co' not in text

    def test_dossier_filename_case_insensitive(self, tmp_path):
        root = _make_root(tmp_path)
        (root / 'company-research/dossiers/allvue systems.md').write_text(
            'dossier body', encoding='utf-8')
        summary = build_context('Allvue Systems', root)
        assert summary['found']['dossier'] is True

    def test_opportunities_rows_filtered_by_company(self, tmp_path):
        root = _make_root(tmp_path)
        _write_opps_csv(root, [
            {'opportunity_key': 'k1', 'company': 'Allvue Systems',
             'role_title': 'Solutions Architect', 'role_url': 'https://x/1',
             'opportunity_status': 'open', 'llm_score': '100',
             'role_family': 'Enterprise Finance', 'fit_summary': '8 of 8 yes',
             'notes': ''},
            {'opportunity_key': 'k2', 'company': 'Zother',
             'role_title': 'PM', 'role_url': 'https://x/2',
             'opportunity_status': 'open', 'llm_score': '70',
             'role_family': 'Other', 'fit_summary': '', 'notes': ''},
        ])
        summary = build_context('Allvue Systems', root)
        assert summary['found']['opportunities'] is True
        text = Path(summary['output_path']).read_text(encoding='utf-8')
        assert 'Solutions Architect' in text
        assert 'Zother' not in text

    def test_base_cv_newest_file_referenced(self, tmp_path):
        root = _make_root(tmp_path)
        old = root / 'cv-tailor/data/CV/old.docx'
        new = root / 'cv-tailor/data/CV/Master CV V2.docx'
        old.write_bytes(b'a')
        new.write_bytes(b'b')
        import os, time
        past = time.time() - 1000
        os.utime(old, (past, past))
        summary = build_context('Any Co', root)
        assert summary['found']['base_cv'] is True
        assert summary['base_cv_path'].endswith('Master CV V2.docx')


class TestOutput:
    def test_output_path_is_slug_context(self, tmp_path):
        root = _make_root(tmp_path)
        summary = build_context('Allvue Systems', root)
        assert summary['output_path'].endswith('interview-prep/preps/allvue-systems-context.md')
