"""
JSONL 입력 스키마 contract test.
jsonl_analyzer가 올바른 이벤트 구조를 기대하는지 검증.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from jsonl_analyzer import analyze_session_signals, AnalysisError  # noqa: E402


def _make_jsonl(events: list[dict], tmp_path: Path) -> Path:
    f = tmp_path / "session.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return f


def _user_msg(content: list[dict]) -> dict:
    return {"type": "user", "message": {"role": "user", "content": content}}


def _tool_result(is_error: bool | None = None, content: str = "ok") -> dict:
    r = {"type": "tool_result", "tool_use_id": "x", "content": content}
    if is_error is not None:
        r["is_error"] = is_error
    return r


def _asst_msg(tool_name: str = "Bash") -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "x", "name": tool_name, "input": {}}],
        },
    }


# ── 기본 구조 계약 ──────────────────────────────────────────────────────────────

def test_returns_dict_with_required_keys(tmp_path):
    jsonl = _make_jsonl([_user_msg([_tool_result()])], tmp_path)
    result = analyze_session_signals(jsonl)
    assert isinstance(result, dict)
    for key in ("errors", "corrections", "stats"):
        assert key in result, f"결과에 '{key}' 키 없음"


def test_errors_is_list(tmp_path):
    jsonl = _make_jsonl([_user_msg([_tool_result()])], tmp_path)
    result = analyze_session_signals(jsonl)
    assert isinstance(result["errors"], list)


def test_corrections_is_list(tmp_path):
    jsonl = _make_jsonl([_user_msg([_tool_result()])], tmp_path)
    result = analyze_session_signals(jsonl)
    assert isinstance(result["corrections"], list)


def test_stats_has_counts(tmp_path):
    jsonl = _make_jsonl([_user_msg([_tool_result()])], tmp_path)
    result = analyze_session_signals(jsonl)
    assert "total_errors" in result["stats"]
    assert "total_corrections" in result["stats"]


# ── 오류 감지 계약 ──────────────────────────────────────────────────────────────

def test_detects_is_error_true(tmp_path):
    jsonl = _make_jsonl([_user_msg([_tool_result(is_error=True, content="FAILED")])], tmp_path)
    result = analyze_session_signals(jsonl)
    assert len(result["errors"]) == 1, f"오류 1건 기대, 실제: {result['errors']}"


def test_ignores_is_error_false(tmp_path):
    jsonl = _make_jsonl([_user_msg([_tool_result(is_error=False)])], tmp_path)
    result = analyze_session_signals(jsonl)
    assert len(result["errors"]) == 0


def test_ignores_missing_is_error(tmp_path):
    jsonl = _make_jsonl([_user_msg([_tool_result(is_error=None)])], tmp_path)
    result = analyze_session_signals(jsonl)
    assert len(result["errors"]) == 0


def test_error_item_has_required_fields(tmp_path):
    jsonl = _make_jsonl(
        [_user_msg([_tool_result(is_error=True, content="AssertionError")])], tmp_path
    )
    result = analyze_session_signals(jsonl)
    assert result["errors"]
    err = result["errors"][0]
    assert "error_snippet" in err
    assert "line_index" in err


# ── 수정 감지 계약 (보수적 3조건) ────────────────────────────────────────────────

def test_detects_correction_after_tool_use(tmp_path):
    events = [
        _asst_msg("Bash"),
        _user_msg([{"type": "text", "text": "아니 틀렸어"}]),
    ]
    jsonl = _make_jsonl(events, tmp_path)
    result = analyze_session_signals(jsonl)
    assert len(result["corrections"]) == 1


def test_no_correction_without_prior_tool_use(tmp_path):
    events = [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "안녕"}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "아니 틀렸어"}]}},
    ]
    jsonl = _make_jsonl(events, tmp_path)
    result = analyze_session_signals(jsonl)
    assert len(result["corrections"]) == 0


def test_no_correction_for_long_message(tmp_path):
    long_msg = "아니 " + "x" * 100
    events = [
        _asst_msg("Bash"),
        _user_msg([{"type": "text", "text": long_msg}]),
    ]
    jsonl = _make_jsonl(events, tmp_path)
    result = analyze_session_signals(jsonl)
    assert len(result["corrections"]) == 0


# ── fail-closed 계약 ─────────────────────────────────────────────────────────

def test_empty_file_returns_empty_signals(tmp_path):
    jsonl = tmp_path / "empty.jsonl"
    jsonl.write_text("")
    result = analyze_session_signals(jsonl)
    assert result["errors"] == []
    assert result["corrections"] == []


def test_nonexistent_file_raises(tmp_path):
    import pytest
    with pytest.raises((FileNotFoundError, AnalysisError)):
        analyze_session_signals(tmp_path / "no_such_file.jsonl")
