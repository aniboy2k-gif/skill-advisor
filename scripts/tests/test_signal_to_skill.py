"""
signal_to_skill.py 유닛 테스트.
TDD RED: signal_to_skill.py 구현 전에 작성.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from signal_to_skill import map_signals_to_skills  # noqa: E402


def _signals(errors=None, corrections=None):
    return {
        "errors": errors or [],
        "corrections": corrections or [],
        "stats": {
            "total_errors": len(errors or []),
            "total_corrections": len(corrections or []),
        },
    }


# ── 기본 매핑 ──────────────────────────────────────────────────────────────────

def test_assertion_error_maps_to_systematic_debugging():
    signals = _signals(errors=[{"error_snippet": "AssertionError: expected 1", "line_index": 5}])
    recs = map_signals_to_skills(signals)
    skills = [r["skill"] for r in recs]
    assert "systematic-debugging" in skills


def test_type_error_maps_to_build_fix():
    signals = _signals(errors=[{"error_snippet": "TypeError: cannot convert", "line_index": 3}])
    recs = map_signals_to_skills(signals)
    skills = [r["skill"] for r in recs]
    assert "build-fix" in skills


def test_no_signals_returns_empty():
    recs = map_signals_to_skills(_signals())
    assert recs == []


# ── provenance 필드 계약 ────────────────────────────────────────────────────────

def test_recommendation_has_provenance_fields():
    signals = _signals(errors=[{"error_snippet": "AssertionError", "line_index": 1}])
    recs = map_signals_to_skills(signals)
    assert recs
    rec = recs[0]
    assert "source" in rec, "source 필드 없음"
    assert "signal" in rec, "signal 필드 없음"
    assert "confidence" in rec, "confidence 필드 없음"
    assert "evidence_count" in rec, "evidence_count 필드 없음"


def test_source_is_error_signal_for_error():
    signals = _signals(errors=[{"error_snippet": "AssertionError", "line_index": 1}])
    recs = map_signals_to_skills(signals)
    assert recs[0]["source"] == "error_signal"


def test_source_is_correction_signal_for_correction():
    corrections = [{"user_message": "아니 틀렸어", "line_index": 2}] * 3
    signals = _signals(corrections=corrections)
    recs = map_signals_to_skills(signals)
    correction_recs = [r for r in recs if r["source"] == "correction_signal"]
    assert correction_recs, f"correction_signal 추천 없음. 전체: {recs}"


def test_confidence_valid_value():
    signals = _signals(errors=[{"error_snippet": "AssertionError", "line_index": 1}])
    recs = map_signals_to_skills(signals)
    for r in recs:
        assert r["confidence"] in ("high", "medium", "low"), f"잘못된 confidence: {r['confidence']}"


def test_evidence_count_is_int():
    signals = _signals(errors=[{"error_snippet": "AssertionError", "line_index": 1}])
    recs = map_signals_to_skills(signals)
    for r in recs:
        assert isinstance(r["evidence_count"], int)


# ── 중복 스킬 제거 ──────────────────────────────────────────────────────────────

def test_duplicate_skills_deduplicated():
    signals = _signals(errors=[
        {"error_snippet": "AssertionError", "line_index": 1},
        {"error_snippet": "test failed", "line_index": 2},
    ])
    recs = map_signals_to_skills(signals)
    skills = [r["skill"] for r in recs]
    assert len(skills) == len(set(skills)), f"중복 스킬: {skills}"
