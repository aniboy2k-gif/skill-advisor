"""
Signal-to-skill mapper with provenance generation.

Converts error/correction signals into skill recommendations using data/signal-skills.json.

v1.1 (CSR #812):
- domain_globs[] context matching: signal triggers AND edited file glob 매칭 시에만 발화
  (empty domain_globs[] = skip context check, 기존 동작 유지)
- confidence auto-derived by evidence_count thresholds (data/signal-skills.json confidence_thresholds)
  현재 임계값: <3 = low / 3-4 = medium / ≥5 = high
"""
from __future__ import annotations

import fnmatch
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from constants import DATA_DIR  # noqa: E402

logger = logging.getLogger(__name__)

_SCHEMA_FILE = DATA_DIR / "signal-skills.json"
_SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})

_DEFAULT_THRESHOLDS = {"low": 0, "medium": 3, "high": 5}

# CSR #1029: total cap for the canonical snippet text propagated into an error_signal record.
# Bounds payload size; per-snippet text is already truncated upstream (jsonl_analyzer _MAX_SNIPPET).
_MAX_SIGNAL_SNIPPET = 4000


def _canonical_snippet(matched: list[dict]) -> str:
    """Join matched error snippets into one canonical, value-deduped, length-capped string.

    CSR #1029: session-review.build_hard_gate_candidates reads err.get("snippet","").lower() and
    matches gate session_signals against it. Exposing a single canonical string (rather than
    emitting per-snippet) follows the G-Ex Sentry-style fingerprint-grouping design — it keeps the
    branch live while avoiding duplicate-trigger false positives.
    """
    seen: set[str] = set()
    parts: list[str] = []
    for e in matched:
        s = e.get("error_snippet", "")
        if s and s not in seen:
            seen.add(s)
            parts.append(s)
    return "\n".join(parts)[:_MAX_SIGNAL_SNIPPET]


def _load_schema() -> dict:
    if not _SCHEMA_FILE.exists():
        logger.warning("[skill-advisor] signal-skills.json not found — signal recommendations disabled")
        return {}
    try:
        return json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[skill-advisor] signal-skills.json parse error: %s", e)
        return {}


def _load_mappings_and_thresholds() -> tuple[list[dict], dict]:
    schema = _load_schema()
    if not schema:
        return [], _DEFAULT_THRESHOLDS

    version = schema.get("schema_version", "")
    if version not in _SUPPORTED_SCHEMA_VERSIONS:
        logger.warning(
            "[skill-advisor] signal-skills.json version mismatch: expected one of %s, got %s — using empty mappings",
            sorted(_SUPPORTED_SCHEMA_VERSIONS), version,
        )
        return [], _DEFAULT_THRESHOLDS

    thresholds = schema.get("confidence_thresholds", _DEFAULT_THRESHOLDS)
    return schema.get("mappings", []), thresholds


def _derive_confidence(evidence_count: int, thresholds: dict, fallback: str | None = None) -> str:
    """evidence_count를 thresholds에 따라 low/medium/high로 자동 산출.

    v1.0 schema의 고정 confidence는 fallback으로 사용 (호환성).
    v1.1 schema는 thresholds 기준 자동 산출.
    """
    high = thresholds.get("high", 5)
    medium = thresholds.get("medium", 3)
    if evidence_count >= high:
        return "high"
    if evidence_count >= medium:
        return "medium"
    if fallback:
        return fallback
    return "low"


def _matches_domain(edited_files: list[str], domain_globs: list[str]) -> bool:
    """편집 파일이 domain_globs 중 하나라도 매칭하는지 확인.

    domain_globs가 비어있으면 컨텍스트 검증 skip (True 반환 — 기존 동작 유지).
    """
    if not domain_globs:
        return True
    for f in edited_files:
        for g in domain_globs:
            if fnmatch.fnmatch(f, g):
                return True
    return False


def map_signals_to_skills(signals: dict, edits: list[dict] | None = None) -> list[dict]:
    """
    Convert error/correction signals into a list of skill recommendations.

    Args:
        signals: Return value from analyze_session_signals()
        edits: List of edit events from extract_edits() — used for domain_globs context matching.
               When None or empty, domain_globs check is skipped (backward-compatible).

    Returns:
        [{"skill": str, "source": str, "signal": str,
          "confidence": str, "evidence_count": int, "snippet": str (error_signal only)}, ...]
        Duplicate skills are merged by accumulating evidence_count.
        confidence is auto-derived from accumulated evidence_count after merging.
        CSR #1029: error_signal records also carry `snippet` (canonical matched error text) for
        downstream error-token matching; correction_signal records have NO `snippet` key — consumers
        must use rec.get("snippet", "").
    """
    mappings, thresholds = _load_mappings_and_thresholds()
    if not mappings:
        return []

    errors = signals.get("errors", [])
    corrections = signals.get("corrections", [])
    edited_files = [e.get("file", "") for e in (edits or []) if e.get("file")]

    # best-match accumulator per skill (dedup)
    skill_map: dict[str, dict] = {}

    for mapping in mappings:
        triggers = mapping.get("triggers", {})
        skill = mapping["skill"]
        evidence_label = mapping.get("evidence_label", "")
        domain_globs = mapping.get("domain_globs", [])
        fallback_conf = mapping.get("confidence")

        # Domain matching — when edits available and domain_globs configured,
        # require at least one edited file to match. Skip mapping otherwise.
        if domain_globs and edited_files and not _matches_domain(edited_files, domain_globs):
            continue

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
                    "evidence_count": len(matched),
                    "snippet": _canonical_snippet(matched),  # CSR #1029: revive dead branch
                    "_fallback_confidence": fallback_conf,
                })

        # correction count matching
        corr_min = triggers.get("correction_count_min")
        if corr_min is not None and len(corrections) >= corr_min:
            _upsert(skill_map, skill, {
                "skill": skill,
                "source": "correction_signal",
                "signal": evidence_label,
                "evidence_count": len(corrections),
                "_fallback_confidence": fallback_conf,
            })

    # confidence 자동 산출 + 내부 필드 제거
    result = []
    for rec in skill_map.values():
        fallback = rec.pop("_fallback_confidence", None)
        rec["confidence"] = _derive_confidence(rec["evidence_count"], thresholds, fallback)
        result.append(rec)
    return result


def _upsert(skill_map: dict, skill: str, rec: dict) -> None:
    """Accumulate evidence_count (and merge canonical snippet text) if skill already exists,
    otherwise insert."""
    if skill in skill_map:
        existing = skill_map[skill]
        existing["evidence_count"] += rec["evidence_count"]
        # CSR #1029: merge the incoming canonical snippet (value-deduped, length-capped) so the
        # error_signal branch stays live when a skill is matched by more than one mapping.
        # Reachable within the error path (e.g. systematic-debugging has 3 error mappings), but NOT
        # across error/correction: only the error path sets `snippet`, and the error_keyword skills
        # and the correction_count skills are disjoint in signal-skills.json — so this never attaches
        # a snippet onto a record whose `source` is "correction_signal" (Gemini DA C1 unreachable,
        # CSR #1029 da-chain). If a skill ever gains both trigger types, revisit source semantics.
        new_snip = rec.get("snippet")
        if new_snip:
            cur = existing.get("snippet", "")
            if not cur:
                existing["snippet"] = new_snip
            elif new_snip not in cur:
                existing["snippet"] = (cur + "\n" + new_snip)[:_MAX_SIGNAL_SNIPPET]
    else:
        skill_map[skill] = rec
