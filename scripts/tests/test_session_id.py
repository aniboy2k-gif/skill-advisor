"""Unit tests for lib.session_id.extract_session_id (CSR #965 갱신).

우선순위: hook stdin(authoritative) → CLAUDE_CODE_SESSION_ID(platform) → .session-hint(heuristic).
deprecated CLAUDE_SESSION_ID 는 제거됨 (2026-05-01 만료, CWE-613).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.resolve()
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import lib.session_id as sid_mod  # noqa: E402
from lib.session_id import extract_session_id  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """모든 테스트에서 env var + .session-hint 격리 (실 환경 누출 차단)."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setattr(sid_mod, "_read_session_hint", lambda: None)


def test_extract_from_stdin_json():
    """hook stdin JSON 의 session_id 1순위(authoritative)로 반환."""
    assert extract_session_id('{"session_id":"abc123","hook_event_name":"Stop"}') == "abc123"


def test_stdin_json_takes_precedence_over_env(monkeypatch):
    """stdin JSON 이 CLAUDE_CODE_SESSION_ID 보다 우선."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "env-value")
    assert extract_session_id('{"session_id":"stdin-value"}') == "stdin-value"


def test_official_env_var_used(monkeypatch):
    """stdin 없으면 공식 CLAUDE_CODE_SESSION_ID(platform) 사용."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "official-sid")
    assert extract_session_id(None) == "official-sid"


def test_official_env_beats_session_hint(monkeypatch):
    """CSR #965 핵심: CLAUDE_CODE_SESSION_ID(platform) 가 .session-hint(heuristic) 보다 우선.

    동일 cwd 동시 세션이 공유 .session-hint 로 cross-session 오염되는 것을
    process-local 공식 env var 가 차단한다.
    """
    monkeypatch.setattr(sid_mod, "_read_session_hint", lambda: "shared-hint-sid")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "my-process-sid")
    assert extract_session_id(None) == "my-process-sid"


def test_session_hint_used_when_no_official_env(monkeypatch):
    """공식 env 부재 시 .session-hint(heuristic) 폴백."""
    monkeypatch.setattr(sid_mod, "_read_session_hint", lambda: "hint-sid")
    assert extract_session_id(None) == "hint-sid"


def test_deprecated_var_ignored(monkeypatch):
    """deprecated CLAUDE_SESSION_ID 는 제거됨 — 설정돼도 무시되고 None."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "deprecated-value")
    assert extract_session_id(None) is None


def test_returns_none_when_all_sources_empty():
    """stdin + 공식 env + hint 모두 비면 None."""
    assert extract_session_id(None) is None
    assert extract_session_id("") is None


def test_malformed_json_falls_through(monkeypatch):
    """잘못된 JSON 은 조용히 무시하고 공식 env 폴백."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "fallback-sid")
    assert extract_session_id("not-json-at-all") == "fallback-sid"


def test_missing_session_id_field_falls_through(monkeypatch):
    """session_id 필드 없는 JSON 은 공식 env 폴백."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "fallback-sid")
    assert extract_session_id('{"hook_event_name":"Stop"}') == "fallback-sid"


def test_empty_session_id_field_falls_through(monkeypatch):
    """session_id 필드가 빈 문자열이면 공식 env 폴백."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "fallback-sid")
    assert extract_session_id('{"session_id":""}') == "fallback-sid"
