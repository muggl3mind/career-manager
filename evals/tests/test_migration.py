"""Tests for CSV column migration."""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


def test_migration_removes_columns():
    from migrate_csv_columns import migrate

    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
        w = csv.writer(f)
        w.writerow(['company', 'fit_score', 'numeric_score', 'role_family', 'llm_path_name', 'llm_score'])
        w.writerow(['Acme', 'High', '85', 'manual', 'AI Product', '90'])
        path = Path(f.name)

    result = migrate(path)
    assert result['status'] == 'migrated'
    assert result['columns_removed'] == 3  # fit_score, numeric_score, llm_path_name

    with path.open() as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        rows = list(reader)

    assert 'fit_score' not in headers
    assert 'numeric_score' not in headers
    assert 'llm_path_name' not in headers
    assert rows[0]['role_family'] == 'AI Product'  # merged from llm_path_name
    path.unlink()


def test_migration_idempotent():
    from migrate_csv_columns import migrate

    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
        w = csv.writer(f)
        w.writerow(['company', 'role_family', 'llm_score'])
        w.writerow(['Acme', 'AI Product', '90'])
        path = Path(f.name)

    result = migrate(path)
    assert result['status'] == 'skipped'
    assert result['reason'] == 'already migrated'
    path.unlink()


def test_migration_preserves_existing_role_family():
    from migrate_csv_columns import migrate

    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
        w = csv.writer(f)
        w.writerow(['company', 'role_family', 'llm_path_name', 'fit_score'])
        w.writerow(['Acme', 'AI Product', 'Different Path', 'High'])
        path = Path(f.name)

    result = migrate(path)
    with path.open() as f:
        rows = list(csv.DictReader(f))
    # Existing non-manual role_family should be preserved
    assert rows[0]['role_family'] == 'AI Product'
    path.unlink()
