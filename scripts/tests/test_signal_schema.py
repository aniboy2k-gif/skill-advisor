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
    # CSR #970: v1.1 — domain_globs 컨텍스트 매칭 + confidence_thresholds 파생 모델
    assert schema["schema_version"] == "1.1", f"expected version 1.1, got: {schema['schema_version']}"


def test_mappings_present():
    schema = _load_schema()
    assert "mappings" in schema, "mappings field missing"
    assert isinstance(schema["mappings"], list), "mappings must be a list"
    assert len(schema["mappings"]) >= 1, "mappings must contain at least one entry"


def test_each_mapping_has_required_fields():
    schema = _load_schema()
    # CSR #970: v1.1 — per-mapping confidence 제거(confidence_thresholds로 파생).
    # domain_globs 는 선택(빈 배열/부재 시 컨텍스트 체크 skip — signal_to_skill.py).
    required = {"id", "triggers", "skill", "evidence_label"}
    for i, m in enumerate(schema["mappings"]):
        missing = required - set(m.keys())
        assert not missing, f"mappings[{i}] missing fields: {missing}"


def test_confidence_thresholds_valid():
    """CSR #970 v1.1: confidence 는 confidence_thresholds(evidence_count 기반)로 파생."""
    schema = _load_schema()
    th = schema.get("confidence_thresholds")
    assert isinstance(th, dict), "confidence_thresholds dict 누락 (v1.1)"
    assert "high" in th and "medium" in th, f"high/medium 임계 누락: {th}"
    assert isinstance(th["high"], int) and isinstance(th["medium"], int), "임계는 정수여야 함"
    assert th["high"] >= th["medium"], f"high({th['high']}) >= medium({th['medium']}) 위배"


def test_domain_globs_is_list_when_present():
    """CSR #970 v1.1: domain_globs 존재 시 list 여야 함(컨텍스트 매칭용)."""
    schema = _load_schema()
    for i, m in enumerate(schema["mappings"]):
        if "domain_globs" in m:
            assert isinstance(m["domain_globs"], list), (
                f"mappings[{i}].domain_globs must be a list"
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
