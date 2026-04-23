"""
추천 결과 provenance 계약 테스트.
모든 추천 항목에 source, signal, confidence, evidence_count가 있어야 함.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from signal_to_skill import map_signals_to_skills  # noqa: E402


PROVENANCE_FIELDS = {"source", "signal", "confidence", "evidence_count"}
VALID_SOURCES = {"file_glob", "error_signal", "correction_signal"}
VALID_CONFIDENCES = {"high", "medium", "low"}


def _signals(errors=None, corrections=None):
    return {
        "errors": errors or [],
        "corrections": corrections or [],
        "stats": {
            "total_errors": len(errors or []),
            "total_corrections": len(corrections or []),
        },
    }


def test_all_recommendations_have_provenance_fields():
    signals = _signals(
        errors=[
            {"error_snippet": "AssertionError", "line_index": 1},
            {"error_snippet": "TypeError", "line_index": 5},
        ],
        corrections=[{"user_message": "아니", "line_index": 10}] * 3,
    )
    recs = map_signals_to_skills(signals)
    for i, rec in enumerate(recs):
        missing = PROVENANCE_FIELDS - set(rec.keys())
        assert not missing, f"추천[{i}] 누락 필드: {missing}. 전체: {rec}"


def test_source_values_are_valid():
    signals = _signals(errors=[{"error_snippet": "AssertionError", "line_index": 1}])
    recs = map_signals_to_skills(signals)
    for rec in recs:
        assert rec["source"] in VALID_SOURCES, f"잘못된 source: {rec['source']}"


def test_confidence_values_are_valid():
    signals = _signals(errors=[{"error_snippet": "AssertionError", "line_index": 1}])
    recs = map_signals_to_skills(signals)
    for rec in recs:
        assert rec["confidence"] in VALID_CONFIDENCES, f"잘못된 confidence: {rec['confidence']}"


def test_evidence_count_is_positive_int():
    signals = _signals(errors=[{"error_snippet": "AssertionError", "line_index": 1}])
    recs = map_signals_to_skills(signals)
    for rec in recs:
        assert isinstance(rec["evidence_count"], int) and rec["evidence_count"] >= 1


def test_signal_field_is_nonempty_string():
    signals = _signals(errors=[{"error_snippet": "AssertionError", "line_index": 1}])
    recs = map_signals_to_skills(signals)
    for rec in recs:
        assert isinstance(rec["signal"], str) and rec["signal"], "signal이 빈 문자열"
