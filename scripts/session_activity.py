"""session_activity.py — JSONL 세션 활동 추출 (슬래시 커맨드 탐지).

기존 jsonl_analyzer.py는 50자 이하 수정 신호만 읽는다.
이 모듈은 user 메시지 텍스트 전체에서 슬래시 커맨드를 추출하여 보완한다.
false positive 방지: known_skills 화이트리스트 + prefix 필터 적용.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from constants import SKILL_INDEX
except ImportError:
    SKILL_INDEX = Path("/tmp/skill-index.json")

# 라인 시작 또는 공백 뒤에 등장하는 슬래시 커맨드만 매칭 (경로 오탐 방지)
_SLASH_RE = re.compile(r"(?:^|\s)/[\w][\w-]*", re.MULTILINE)

# 스킬명 확인 없이도 허용할 알려진 슬래시 커맨드 prefix
_KNOWN_PREFIXES = (
    "da-", "sc:", "skill-", "session-", "systematic-",
    "verification-", "security-", "feature-", "using-",
    "handoff-", "vercel-", "tailwind-", "plan", "tdd",
    "compact", "strategic-", "memory-", "codex-",
)


def _get_known_skills() -> set[str]:
    """skill-index.json에서 알려진 스킬명 집합 로드."""
    try:
        data = json.loads(SKILL_INDEX.read_text(encoding="utf-8"))
        skills = data.get("skills", data) if isinstance(data, dict) else data
        return {s.get("skill", "") for s in skills if isinstance(s, dict)}
    except Exception:
        return set()


def extract_slash_commands(jsonl: Path, max_events: int = 500) -> list[str]:
    """JSONL user 메시지에서 유효한 슬래시 커맨드만 추출.

    - 화이트리스트 필터: known_skills + _KNOWN_PREFIXES
    - dedup하되 최초 등장 순서 유지
    - max_events: user 메시지 처리 최대 개수
    """
    known = _get_known_skills()
    found: list[str] = []
    count = 0
    try:
        with jsonl.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if count >= max_events:
                    break
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "user":
                    continue
                count += 1
                content = entry.get("message", {}).get("content") or []
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "text":
                        continue
                    text = block.get("text", "")
                    for m in _SLASH_RE.finditer(text):
                        raw = m.group().strip()
                        cmd = raw.lstrip("/")
                        if cmd in known or any(cmd.startswith(p) for p in _KNOWN_PREFIXES):
                            found.append("/" + cmd)
    except Exception:
        pass
    # dedup, 최초 등장 순서 유지
    return list(dict.fromkeys(found))
