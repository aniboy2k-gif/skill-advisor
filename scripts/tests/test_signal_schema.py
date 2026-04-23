"""
Phase 0 게이트 테스트 — signal-skills.json 스키마 계약 검증.

이 테스트가 GREEN이어야 Phase 1 진입 allowed.
Run: pytest scripts/tests/test_signal_schema.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
SCHEMA_FILE = DATA_DIR / "signal-skills.json"


def _load_schema() -> dict:
    assert SCHEMA_FILE.exists(), f"signal-skills.json not found: {SCHEMA_FILE}"
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def test_schema_file_exists():
    assert SCHEMA_FILE.exists(), f"signal-skills.json not found: {SCHEMA_FILE}"


def test_schema_version_present():
    schema = _load_schema()
    assert "schema_version" in schema, "schema_version field missing"
    assert schema["schema_version"] == "1.0", f"expected version 1.0, got: {schema['schema_version']}"


def test_mappings_present():
    schema = _load_schema()
    assert "mappings" in schema, "mappings field missing"
    assert isinstance(schema["mappings"], list), "mappings must be a list"
    assert len(schema["mappings"]) >= 1, "mappings must contain at least one entry"


def test_each_mapping_has_required_fields():
    schema = _load_schema()
    required = {"id", "triggers", "skill", "confidence", "evidence_label"}
    for i, m in enumerate(schema["mappings"]):
        missing = required - set(m.keys())
        assert not missing, f"mappings[{i}] missing fields: {missing}"


def test_mapping_confidence_values():
    schema = _load_schema()
    valid = {"high", "medium", "low"}
    for i, m in enumerate(schema["mappings"]):
        assert m["confidence"] in valid, (
            f"mappings[{i}].invalid confidence value: {m['confidence']!r} (allowed: {valid})"
        )


def test_mapping_ids_unique():
    schema = _load_schema()
    ids = [m["id"] for m in schema["mappings"]]
    assert len(ids) == len(set(ids)), f"duplicate ids found: {ids}"


def test_triggers_have_valid_structure():
    schema = _load_schema()
    for i, m in enumerate(schema["mappings"]):
        triggers = m["triggers"]
        assert isinstance(triggers, dict), f"mappings[{i}].triggers must be a dict"
        has_keywords = "error_keywords" in triggers
        has_correction = "correction_count_min" in triggers
        assert has_keywords or has_correction, (
            f"mappings[{i}].triggers에 must have error_keywords or correction_count_min"
        )
        if has_keywords:
            assert isinstance(triggers["error_keywords"], list), (
                f"mappings[{i}].triggers.error_keywords must be a list"
            )
            assert "min_count" in triggers, (
                f"mappings[{i}].triggers missing min_count"
            )
