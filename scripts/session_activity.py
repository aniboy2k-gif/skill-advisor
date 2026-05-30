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
    # CSR #832 fallback (constants.py 미import 환경)
    _primary = Path.home() / ".claude" / "da-tools" / "skill-index.json"
    SKILL_INDEX = _primary if _primary.exists() else Path("/tmp/skill-index.json")

# 라인 시작 또는 공백 뒤에 등장하는 슬래시 커맨드만 매칭 (경로 오탐 방지) — mention 스캔용
_SLASH_RE = re.compile(r"(?:^|\s)/[\w][\w-]*", re.MULTILINE)

# CSR #973: 실제 슬래시 호출은 Claude Code가 user entry의 message.content(문자열)에
# <command-name>/foo</command-name> 트리플릿으로 기록한다. 인용/논의 텍스트는 content가
# 리스트(text 블록)거나 tool_result라 이 경로로 들어오지 않는다 (da-chain C-1 해소).
# 콜론 네임스페이스(/sc:analyze, /a:b:c)·점·하이픈 캡처 (da-chain H-1). 다중 호출 finditer (M-2).
# ★ 버전 의존 (da-chain H-2): 본 구조(content=str + <command-name> 트리플릿) 가정은 Claude Code
#   v2.1.157 기준 실측. 향후 Claude Code 버전 변경 시 transcript user entry의 슬래시 호출 표현이
#   바뀌면 본 탐지가 false-negative 될 수 있으므로 content 구조 재확인 필요.
_CMD_NAME_RE = re.compile(r"<command-name>\s*/?([\w][\w:.-]*)\s*</command-name>")

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
                # 메타 turn (요약·시스템 주입)은 실제 사용자 호출이 아님 (da-chain C-1)
                if entry.get("isMeta"):
                    continue
                count += 1
                content = entry.get("message", {}).get("content")
                # CSR #973: 실제 호출만 executed로 인정 — content가 '문자열'이고
                # <command-name> 트리플릿일 때만. 리스트(text 블록)·tool_result에 등장하는
                # <command-name>/cmd 인용은 호출이 아니므로 제외 (da-chain C-1 false-positive 차단).
                if not isinstance(content, str) or "<command-name>" not in content:
                    continue
                for m in _CMD_NAME_RE.finditer(content):
                    cmd = m.group(1)  # 슬래시 없이 캡처됨 (정규식 /? 소비) — 콜론/점/하이픈 보존
                    if cmd in known or any(cmd.startswith(p) for p in _KNOWN_PREFIXES):
                        found.append("/" + cmd)
    except Exception:
        pass
    # dedup, 최초 등장 순서 유지
    return list(dict.fromkeys(found))
