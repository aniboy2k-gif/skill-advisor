"""
JSONL session analyzer — extracts error and correction signals.

Independently implemented (inspired by accidentalrebel/claude-skill-session-retrospective concept).
Based on the public Claude Code JSONL format.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Correction detection keywords — conservative design: false negatives accepted, false positives avoided
_NEGATION_KW = frozenset([
    "아니", "틀렸", "잘못", "다시해", "틀린",
    "no", "wrong", "redo", "incorrect", "mistake",
])

# 오류 스니펫 최대 길이
_MAX_SNIPPET = 300


class AnalysisError(Exception):
    """JSONL 파일 접근 또는 스키마 검증 실패."""


def analyze_session_signals(
    jsonl_path: Path,
    max_events: int = 200,
) -> dict:
    """
    세션 JSONL에서 오류·수정 시그널을 추출한다.

    Returns:
        {
          "errors": [{"error_snippet": str, "line_index": int}, ...],
          "corrections": [{"user_message": str, "line_index": int}, ...],
          "stats": {"total_errors": int, "total_corrections": int},
        }
    Raises:
        AnalysisError: 파일 없음 또는 치명적 파싱 실패
    """
    if not jsonl_path.exists():
        raise AnalysisError(f"JSONL 파일 없음: {jsonl_path}")

    errors: list[dict] = []
    corrections: list[dict] = []
    prev_had_tool_use = False

    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise AnalysisError(f"JSONL 읽기 실패: {e}") from e

    if not lines:
        return {"errors": [], "corrections": [], "stats": {"total_errors": 0, "total_corrections": 0}}

    processed = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if processed >= max_events:
            break

        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("[skill-advisor] line %d: JSON parse error — skipping", i)
            continue

        msg_type = d.get("type")
        content = d.get("message", {}).get("content") or []
        if not isinstance(content, list):
            # unknown field 형태 — warn하고 무시
            logger.debug("[skill-advisor] line %d: content is not a list — ignored", i)
            content = []

        if msg_type == "assistant":
            # tool_use가 있는지 확인
            prev_had_tool_use = any(
                isinstance(c, dict) and c.get("type") == "tool_use"
                for c in content
            )

        elif msg_type == "user":
            for c in content:
                if not isinstance(c, dict):
                    continue
                item_type = c.get("type")

                if item_type == "tool_result":
                    _handle_tool_result(c, i, errors)

                elif item_type == "text" and prev_had_tool_use:
                    _handle_user_correction(c, i, corrections)

            # user 메시지 뒤에는 tool_use 상태 초기화
            prev_had_tool_use = False

        processed += 1

    return {
        "errors": errors,
        "corrections": corrections,
        "stats": {
            "total_errors": len(errors),
            "total_corrections": len(corrections),
        },
    }


def _handle_tool_result(c: dict, line_index: int, errors: list[dict]) -> None:
    """is_error=True인 tool_result를 errors 목록에 추가."""
    if c.get("is_error") is not True:
        return
    content_val = c.get("content", "")
    snippet = str(content_val)[:_MAX_SNIPPET] if content_val else ""
    errors.append({"error_snippet": snippet, "line_index": line_index})


def _handle_user_correction(c: dict, line_index: int, corrections: list[dict]) -> None:
    """보수적 3조건 — 어시스턴트 tool_use 직후 + 50자 미만 + 부정어 포함."""
    text = c.get("text", "") or ""
    if len(text) >= 50:
        return
    lower = text.lower()
    if not any(kw in lower for kw in _NEGATION_KW):
        return
    corrections.append({"user_message": text[:200], "line_index": line_index})


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python jsonl_analyzer.py <path.jsonl>")
        sys.exit(1)
    import pprint
    result = analyze_session_signals(Path(sys.argv[1]))
    pprint.pprint(result)
