"""
jsonl_analyzer.py 유닛 테스트.
TDD RED: jsonl_analyzer.py 구현 전에 작성.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from jsonl_analyzer import analyze_session_signals  # noqa: E402


def _make_jsonl(events: list[dict], tmp_path: Path) -> Path:
    f = tmp_path / "session.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return f


def _user_tool_result(is_error: bool, content: str = "") -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "abc",
                    "is_error": is_error,
                    "content": content,
                }
            ],
        },
    }


def _asst_with_tool(name: str = "Bash") -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "abc", "name": name, "input": {}}
            ],
        },
    }


def _user_text(text: str) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


# ── 오류 이벤트 감지 ────────────────────────────────────────────────────────────

def test_single_error_detected(tmp_path):
    jsonl = _make_jsonl([_user_tool_result(True, "AssertionError: expected 1")], tmp_path)
    r = analyze_session_signals(jsonl)
    assert r["stats"]["total_errors"] == 1
    assert r["errors"][0]["error_snippet"].startswith("AssertionError")


def test_multiple_errors_detected(tmp_path):
    events = [
        _user_tool_result(True, "Error A"),
        _user_tool_result(True, "Error B"),
    ]
    jsonl = _make_jsonl(events, tmp_path)
    r = analyze_session_signals(jsonl)
    assert r["stats"]["total_errors"] == 2


def test_success_result_not_counted_as_error(tmp_path):
    jsonl = _make_jsonl([_user_tool_result(False, "OK")], tmp_path)
    r = analyze_session_signals(jsonl)
    assert r["stats"]["total_errors"] == 0


def test_error_snippet_truncated(tmp_path):
    long_err = "E" * 500
    jsonl = _make_jsonl([_user_tool_result(True, long_err)], tmp_path)
    r = analyze_session_signals(jsonl)
    assert len(r["errors"][0]["error_snippet"]) <= 300


# ── 수정 이벤트 감지 (3조건 AND) ───────────────────────────────────────────────

def test_correction_after_tool_use_short_negation(tmp_path):
    events = [_asst_with_tool(), _user_text("아니 틀렸어")]
    jsonl = _make_jsonl(events, tmp_path)
    r = analyze_session_signals(jsonl)
    assert r["stats"]["total_corrections"] >= 1


def test_no_correction_positive_short_msg(tmp_path):
    events = [_asst_with_tool(), _user_text("좋아요 감사합니다")]
    jsonl = _make_jsonl(events, tmp_path)
    r = analyze_session_signals(jsonl)
    assert r["stats"]["total_corrections"] == 0


def test_no_correction_no_prior_tool(tmp_path):
    events = [_user_text("처음 메시지"), _user_text("아니 틀렸어")]
    jsonl = _make_jsonl(events, tmp_path)
    r = analyze_session_signals(jsonl)
    assert r["stats"]["total_corrections"] == 0


# ── max_events 제한 ─────────────────────────────────────────────────────────────

def test_max_events_limits_analysis(tmp_path):
    events = [_user_tool_result(True, f"err {i}") for i in range(300)]
    jsonl = _make_jsonl(events, tmp_path)
    r = analyze_session_signals(jsonl, max_events=10)
    assert len(r["errors"]) <= 10


# ── unknown field 경고 (침묵 없음) ─────────────────────────────────────────────

def test_unknown_field_does_not_crash(tmp_path):
    events = [
        {
            "type": "user",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "x", "content": "ok",
                 "is_error": True, "future_unknown_field": "value"}
            ]},
        }
    ]
    jsonl = _make_jsonl(events, tmp_path)
    r = analyze_session_signals(jsonl)
    assert r["stats"]["total_errors"] == 1
