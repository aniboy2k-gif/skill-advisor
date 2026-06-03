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

# CSR #1030: subagent invocation tool names. "Task" was renamed to "Agent" in
# Claude Code v2.1.63; both are matched for backward compatibility (official
# Anthropic subagents doc + local measurement: 541 "Agent" events, 0 "Task").
_SUBAGENT_TOOL_NAMES = frozenset(["Agent", "Task"])


class AnalysisError(Exception):
    """JSONL 파일 접근 또는 스키마 검증 실패."""


def _extract_subagent_invocations(lines: list[str]) -> list[dict]:
    """tool_use 블록 중 name in {Agent, Task} 를 전체 스캔으로 수집한다 (CSR #1030).

    handoff-verify (★B) 의 진짜 신호 = "서브에이전트가 실행됨" 이며, 이는 파일 경로도
    에러 스니펫도 아닌 구조화 JSONL tool_use 이벤트다. 따라서 텍스트 substring 매칭으로는
    잡을 수 없어 전용 구조화 신호로 추출한다.

    - **uncapped**: analyze_session_signals 의 max_events 캡과 독립 — 긴 세션의 최근
      서브에이전트를 silent miss 하지 않는다 (da-chain Gemini CRITICAL / Claude Web M3).
    - **isSidechain 제외**: top-level isSidechain 이 True 인 라인(서브에이전트 자체 내부
      컨텍스트)은 중복 카운트 방지를 위해 제외한다 (da-chain Claude Web H1, 실제 필드).
    - line_index = 파일 절대 라인 인덱스 (truncation 없음 — da-chain ChatGPT L-1).

    Returns: [{"subagent_type": str, "line_index": int}, ...]
    """
    invocations: list[dict] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("isSidechain") is True:
            continue
        content = d.get("message", {}).get("content") or []
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            if c.get("name") in _SUBAGENT_TOOL_NAMES:
                inp = c.get("input", {})
                stype = inp.get("subagent_type", "") if isinstance(inp, dict) else ""
                invocations.append({"subagent_type": stype, "line_index": i})
    return invocations


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
          "subagent_invocations": [{"subagent_type": str, "line_index": int}, ...],
          "stats": {"total_errors": int, "total_corrections": int,
                    "total_subagent_invocations": int},
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
        return {
            "errors": [], "corrections": [], "subagent_invocations": [],
            "stats": {"total_errors": 0, "total_corrections": 0, "total_subagent_invocations": 0},
        }

    # CSR #1030: subagent 추출은 max_events 캡과 독립한 전체 스캔 (이미 읽은 lines 재사용).
    subagent_invocations = _extract_subagent_invocations(lines)

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
        "subagent_invocations": subagent_invocations,
        "stats": {
            "total_errors": len(errors),
            "total_corrections": len(corrections),
            "total_subagent_invocations": len(subagent_invocations),
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
