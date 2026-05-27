"""Unit tests for lib.session_id.extract_session_id."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.resolve()
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.session_id import extract_session_id  # noqa: E402


def test_extract_from_stdin_json(capsys):
    """hook stdin JSON의 session_id 필드 1순위로 반환."""
    sid = extract_session_id('{"session_id":"abc123","hook_event_name":"Stop"}')
    assert sid == "abc123"
    assert "DEPRECATION" not in capsys.readouterr().err


def test_stdin_json_takes_precedence_over_env(monkeypatch, capsys):
    """stdin JSON이 env var보다 우선. env var 사용되지 않으므로 경고도 없음."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-value")
    sid = extract_session_id('{"session_id":"stdin-value"}')
    assert sid == "stdin-value"
    assert "DEPRECATION" not in capsys.readouterr().err


def test_env_var_fallback_emits_deprecation(monkeypatch, capsys):
    """stdin JSON이 없으면 env var로 fallback하며 deprecation 경고를 stderr로 출력."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-fallback")
    sid = extract_session_id(None)
    assert sid == "env-fallback"
    assert "DEPRECATION" in capsys.readouterr().err


def test_returns_none_when_both_sources_empty(monkeypatch):
    """stdin JSON + env var 모두 비어있으면 None."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    assert extract_session_id(None) is None
    assert extract_session_id("") is None


def test_malformed_json_falls_through_to_env(monkeypatch, capsys):
    """잘못된 JSON은 조용히 무시하고 env var fallback을 시도."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-fallback")
    sid = extract_session_id("not-json-at-all")
    assert sid == "env-fallback"
    assert "DEPRECATION" in capsys.readouterr().err


def test_missing_session_id_field_falls_through(monkeypatch):
    """session_id 필드가 없는 JSON은 env var fallback."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-fallback")
    sid = extract_session_id('{"hook_event_name":"Stop"}')
    assert sid == "env-fallback"


def test_empty_session_id_field_falls_through(monkeypatch):
    """session_id 필드가 빈 문자열이면 env var fallback."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-fallback")
    sid = extract_session_id('{"session_id":""}')
    assert sid == "env-fallback"
