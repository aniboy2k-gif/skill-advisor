"""
시그널 → 스킬 매핑 + Provenance 생성.

data/signal-skills.json 기반으로 오류·수정 시그널을 스킬 추천으로 변환한다.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from constants import DATA_DIR  # noqa: E402

logger = logging.getLogger(__name__)

_SCHEMA_FILE = DATA_DIR / "signal-skills.json"
_SUPPORTED_SCHEMA_VERSION = "1.0"


def _load_mappings() -> list[dict]:
    if not _SCHEMA_FILE.exists():
        logger.warning("[skill-advisor] signal-skills.json 없음 — 시그널 추천 비활성")
        return []
    try:
        schema = json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[skill-advisor] signal-skills.json 파싱 실패: %s", e)
        return []

    version = schema.get("schema_version", "")
    if version != _SUPPORTED_SCHEMA_VERSION:
        logger.warning(
            "[skill-advisor] signal-skills.json 버전 불일치: 기대 %s, 실제 %s — 빈 매핑 사용",
            _SUPPORTED_SCHEMA_VERSION, version,
        )
        return []
    return schema.get("mappings", [])


def map_signals_to_skills(signals: dict) -> list[dict]:
    """
    오류·수정 시그널을 스킬 추천 목록으로 변환한다.

    Args:
        signals: analyze_session_signals()의 반환값
    Returns:
        [{"skill": str, "source": str, "signal": str,
          "confidence": str, "evidence_count": int}, ...]
        중복 스킬은 evidence_count를 합산하여 단일 항목으로 반환.
    """
    mappings = _load_mappings()
    if not mappings:
        return []

    errors = signals.get("errors", [])
    corrections = signals.get("corrections", [])

    # skill → 최선 추천 집계 (dedup)
    skill_map: dict[str, dict] = {}

    for mapping in mappings:
        triggers = mapping.get("triggers", {})
        skill = mapping["skill"]
        confidence = mapping["confidence"]
        evidence_label = mapping.get("evidence_label", "")

        # 오류 키워드 매칭
        keywords = [kw.lower() for kw in triggers.get("error_keywords", [])]
        min_count = triggers.get("min_count", 1)
        if keywords and errors:
            matched = [
                e for e in errors
                if any(kw in e.get("error_snippet", "").lower() for kw in keywords)
            ]
            if len(matched) >= min_count:
                _upsert(skill_map, skill, {
                    "skill": skill,
                    "source": "error_signal",
                    "signal": evidence_label,
                    "confidence": confidence,
                    "evidence_count": len(matched),
                })

        # 수정 횟수 매칭
        corr_min = triggers.get("correction_count_min")
        if corr_min is not None and len(corrections) >= corr_min:
            _upsert(skill_map, skill, {
                "skill": skill,
                "source": "correction_signal",
                "signal": evidence_label,
                "confidence": confidence,
                "evidence_count": len(corrections),
            })

    return list(skill_map.values())


def _upsert(skill_map: dict, skill: str, rec: dict) -> None:
    """이미 있으면 evidence_count를 누적, 없으면 삽입."""
    if skill in skill_map:
        skill_map[skill]["evidence_count"] += rec["evidence_count"]
    else:
        skill_map[skill] = rec
