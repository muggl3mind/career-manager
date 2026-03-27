#!/usr/bin/env python3
"""
Tests for eval-results.json schema contract.

Validates that eval-results.json (when present) conforms to the schema,
and tests the schema itself against known good/bad inputs.

Run: pytest career-manager/evals/tests/test_schema_validation.py -v
"""

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'schemas' / 'eval-results.schema.json'
EVAL_RESULTS = Path(__file__).resolve().parents[2] / 'job-search' / 'data' / 'eval-results.json'


def _load_schema():
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def _validate(data, schema):
    """Minimal schema validation without jsonschema dependency.

    Checks required fields and basic types for each item in the array.
    Returns list of error strings.
    """
    errors = []
    if not isinstance(data, list):
        return [f"Expected array, got {type(data).__name__}"]

    item_schema = schema.get('items', {})
    required = item_schema.get('required', [])
    properties = item_schema.get('properties', {})

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"Item {i}: expected object, got {type(item).__name__}")
            continue
        for field in required:
            if field not in item:
                errors.append(f"Item {i}: missing required field '{field}'")
            elif properties.get(field, {}).get('type') == 'string' and not isinstance(item[field], str):
                errors.append(f"Item {i}: '{field}' should be string, got {type(item[field]).__name__}")
            elif properties.get(field, {}).get('type') == 'integer' and not isinstance(item[field], int):
                errors.append(f"Item {i}: '{field}' should be integer, got {type(item[field]).__name__}")
            elif properties.get(field, {}).get('type') == 'boolean' and not isinstance(item[field], bool):
                errors.append(f"Item {i}: '{field}' should be boolean, got {type(item[field]).__name__}")
            elif properties.get(field, {}).get('type') == 'object' and not isinstance(item[field], dict):
                errors.append(f"Item {i}: '{field}' should be object, got {type(item[field]).__name__}")
        # Check minLength constraints
        for field, props in properties.items():
            if field in item and props.get('minLength') and isinstance(item[field], str):
                if len(item[field]) < props['minLength']:
                    errors.append(f"Item {i}: '{field}' is too short (min {props['minLength']})")

    return errors


VALID_ENTRY = {
    'company': 'TestCo',
    'careers_url': 'https://testco.com/careers',
    'scores': {'domain': 20, 'ai': 15},
    'total_score': 72,
    'path': 'pm',
    'path_name': 'Product Manager',
    'fit_summary': 'Strong domain overlap with healthcare focus',
    'hard_pass': False,
}


class TestSchemaStructure:
    def test_schema_file_exists(self):
        assert SCHEMA_PATH.exists(), f"Schema not found at {SCHEMA_PATH}"

    def test_schema_is_valid_json(self):
        schema = _load_schema()
        assert schema['type'] == 'array'
        assert 'items' in schema

    def test_required_fields_defined(self):
        schema = _load_schema()
        required = schema['items']['required']
        expected = ['company', 'careers_url', 'scores', 'total_score', 'path', 'path_name', 'fit_summary', 'hard_pass']
        assert set(required) == set(expected)


class TestValidData:
    def test_valid_single_entry(self):
        schema = _load_schema()
        errors = _validate([VALID_ENTRY], schema)
        assert errors == [], f"Validation errors: {errors}"

    def test_valid_multiple_entries(self):
        schema = _load_schema()
        entry2 = {**VALID_ENTRY, 'company': 'OtherCo', 'careers_url': 'https://other.com/jobs'}
        errors = _validate([VALID_ENTRY, entry2], schema)
        assert errors == []

    def test_valid_with_optional_fields(self):
        schema = _load_schema()
        full = {
            **VALID_ENTRY,
            'red_flags': ['No healthcare focus'],
            'hard_pass_reason': '',
            'cv_template': 'technical',
        }
        errors = _validate([full], schema)
        assert errors == []

    def test_empty_array_is_valid(self):
        schema = _load_schema()
        errors = _validate([], schema)
        assert errors == []


class TestInvalidData:
    def test_not_array(self):
        schema = _load_schema()
        errors = _validate({'company': 'test'}, schema)
        assert len(errors) > 0

    def test_missing_company(self):
        schema = _load_schema()
        entry = {k: v for k, v in VALID_ENTRY.items() if k != 'company'}
        errors = _validate([entry], schema)
        assert any("'company'" in e for e in errors)

    def test_missing_careers_url(self):
        schema = _load_schema()
        entry = {k: v for k, v in VALID_ENTRY.items() if k != 'careers_url'}
        errors = _validate([entry], schema)
        assert any("'careers_url'" in e for e in errors)

    def test_missing_scores(self):
        schema = _load_schema()
        entry = {k: v for k, v in VALID_ENTRY.items() if k != 'scores'}
        errors = _validate([entry], schema)
        assert any("'scores'" in e for e in errors)

    def test_wrong_type_total_score(self):
        schema = _load_schema()
        entry = {**VALID_ENTRY, 'total_score': '72'}
        errors = _validate([entry], schema)
        assert any("'total_score'" in e for e in errors)

    def test_wrong_type_hard_pass(self):
        schema = _load_schema()
        entry = {**VALID_ENTRY, 'hard_pass': 'false'}
        errors = _validate([entry], schema)
        assert any("'hard_pass'" in e for e in errors)

    def test_empty_company_name(self):
        schema = _load_schema()
        entry = {**VALID_ENTRY, 'company': ''}
        errors = _validate([entry], schema)
        assert any("'company'" in e and "too short" in e for e in errors)

    def test_item_not_object(self):
        schema = _load_schema()
        errors = _validate(['not an object'], schema)
        assert len(errors) > 0


class TestLiveData:
    """Validate actual eval-results.json if it exists (transient file)."""

    def test_live_eval_results_if_present(self):
        if not EVAL_RESULTS.exists():
            import pytest
            pytest.skip('eval-results.json not present (consumed after merge)')
        schema = _load_schema()
        with EVAL_RESULTS.open() as f:
            data = json.load(f)
        errors = _validate(data, schema)
        assert errors == [], f"Live eval-results.json failed validation:\n" + '\n'.join(errors)
