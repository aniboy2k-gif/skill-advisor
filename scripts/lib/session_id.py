"""session_id.py — Claude Code hook stdin JSON에서 session_id 추출 공통 유틸.

배경: CLAUDE_SESSION_ID 환경변수는 Anthropic 공식 API가 아니다
(GitHub issues #25642 / #13733 / #17188 모두 OPEN feature request).
Anthropic 공식 경로는 hook stdin JSON의 .session_id 필드.

사용법:
    from lib.session_id import extract_session_id
    session_id = extract_session_id()               # .session-hint fallback + env var
    session_id = extract_session_id(stdin_json)     # hook stdin 캡처본 전달

우선순위 (CSR #815, bash session-id.sh 대칭):
    1) stdin JSON .session_id (hook 전용)
    2) .session-hint 파일 (scope 격리, 1시간 TTL — standalone CLI 용)
    3) CLAUDE_SESSION_ID env var (deprecation, 2026-05-01까지 유효)
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

_UUID_RE = re.compile(r"^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$")
_SESSION_HINT_TTL_SECONDS = 3600


def _is_valid_uuid(sid: str) -> bool:
    """bash _is_valid_uuid 대칭."""
    return bool(_UUID_RE.match(sid))


def _get_project_hash(cwd: Optional[str] = None) -> str:
    """pwd md5 첫 8자 — bash _get_project_hash 대칭."""
    raw = cwd if cwd is not None else os.getcwd()
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def _read_session_hint() -> Optional[str]:
    """bash session-id.sh:102-127 대칭 fallback — .session-hint 파일에서 SID 읽기.

    Returns:
        Valid UUID session_id 또는 None (파일 없음·stale·UUID 형식 오류).
    """
    project_hash = _get_project_hash()
    hint_file = Path.home() / ".claude" / "gate-artifacts" / project_hash / ".session-hint"
    if not hint_file.exists():
        return None
    try:
        data = json.loads(hint_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    sid = (data.get("sid") or "").strip()
    if not _is_valid_uuid(sid):
        return None

    try:
        ts = int(data.get("created_at", 0))
    except (TypeError, ValueError):
        return None

    if time.time() - ts >= _SESSION_HINT_TTL_SECONDS:
        return None

    return sid


def extract_session_id(hook_input: Optional[str] = None) -> Optional[str]:
    """session_id를 우선순위에 따라 반환.

    Args:
        hook_input: hook stdin에서 읽은 JSON 문자열. 없으면 .session-hint + env var.

    Returns:
        session_id 문자열 또는 None (모든 source 비어있을 때).
    """
    # 1순위: hook stdin JSON
    if hook_input:
        try:
            data = json.loads(hook_input)
            sid = (data.get("session_id") or "").strip()
            if sid:
                return sid
        except (json.JSONDecodeError, AttributeError):
            pass

    # 2순위 (CSR #815): .session-hint 파일 — standalone CLI 지원
    sid = _read_session_hint()
    if sid:
        return sid

    # 3순위: CLAUDE_SESSION_ID env var (deprecation)
    sid = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if sid:
        sys.stderr.write(
            "[DEPRECATION] CLAUDE_SESSION_ID env var 의존은 2026-05-01까지 유효. "
            "hook stdin JSON .session_id 또는 .session-hint 사용 권장.\n"
        )
        return sid

    return None
