"""
Signal-to-skill mapper with provenance generation.

Converts error/correction signals into skill recommendations using data/signal-skills.json.
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
        logger.warning("[skill-advisor] signal-skills.json not found — signal recommendations disabled")
        return []
    try:
        schema = json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[skill-advisor] signal-skills.json parse error: %s", e)
        return []

    version = schema.get("schema_version", "")
    if version != _SUPPORTED_SCHEMA_VERSION:
        logger.warning(
            "[skill-advisor] signal-skills.json version mismatch: expected %s, got %s — using empty mappings",
            _SUPPORTED_SCHEMA_VERSION, version,
        )
        return []
    return schema.get("mappings", [])


def map_signals_to_skills(signals: dict) -> list[dict]:
    """
    Convert error/correction signals into a list of skill recommendations.

    Args:
        signals: Return value from analyze_session_signals()
    Returns:
        [{"skill": str, "source": str, "signal": str,
          "confidence": str, "evidence_count": int}, ...]
        Duplicate skills are merged by accumulating evidence_count.
    """
    mappings = _load_mappings()
    if not mappings:
        return []

    errors = signals.get("errors", [])
    corrections = signals.get("corrections", [])

    # best-match accumulator per skill (dedup)
    skill_map: dict[str, dict] = {}

    for mapping in mappings:
        triggers = mapping.get("triggers", {})
        skill = mapping["skill"]
        confidence = mapping["confidence"]
        evidence_label = mapping.get("evidence_label", "")

        # error keyword matching
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

        # correction count matching
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
    """Accumulate evidence_count if skill already exists, otherwise insert."""
    if skill in skill_map:
        skill_map[skill]["evidence_count"] += rec["evidence_count"]
    else:
        skill_map[skill] = rec
