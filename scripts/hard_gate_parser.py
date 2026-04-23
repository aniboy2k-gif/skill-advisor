"""hard_gate_parser.py — Hard Gate 정의 로더 + CLAUDE.md 합집합 병합."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from constants import DATA_DIR

HARD_GATES_JSON = DATA_DIR / "hard-gates.json"
CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"
STALE_DAYS = 60


def load_hard_gates() -> tuple[list[dict], list[str]]:
    """(gates, warnings) 반환.

    1차: data/hard-gates.json (구조화된 기계 판독 형식)
    2차: ~/.claude/CLAUDE.md (사용자 커스텀 게이트 보완)
    합집합 dedup: 정규화된 스킬명 기준, CLAUDE.md는 custom_claude_md 표시.
    """
    warnings: list[str] = []
    json_gates = _load_json_gates(warnings)

    _check_stale(warnings)

    claude_gates = _parse_claude_md(warnings)
    return _merge_gates(json_gates, claude_gates), warnings


def _load_json_gates(warnings: list[str]) -> list[dict]:
    try:
        return json.loads(HARD_GATES_JSON.read_text(encoding="utf-8")).get("gates", [])
    except Exception as e:
        warnings.append(f"[WARN] hard-gates.json 로드 실패: {e}")
        return []


def _check_stale(warnings: list[str]) -> None:
    try:
        meta = json.loads(HARD_GATES_JSON.read_text(encoding="utf-8"))
        lu_str = meta.get("last_updated", "2020-01-01")
        lu = datetime.fromisoformat(lu_str)
        age = (datetime.now() - lu).days
        if age > STALE_DAYS:
            warnings.append(
                f"[⚠ STALE BUNDLE] hard-gates.json이 {age}일 경과 — CLAUDE.md를 직접 확인하세요"
            )
    except Exception:
        pass


def _parse_claude_md(warnings: list[str]) -> list[dict]:
    """CLAUDE.md 스킬 우선 활용 테이블에서 ★ 게이트 추출.

    CLAUDE.md 형식에 의존하므로 실패 시 warning만 내고 빈 목록 반환.
    """
    if not CLAUDE_MD.exists():
        return []
    try:
        text = CLAUDE_MD.read_text(encoding="utf-8")
        section_m = re.search(
            r"# 스킬 우선 활용.*?(?=^#\s|\Z)",
            text,
            re.DOTALL | re.MULTILINE,
        )
        if not section_m:
            return []
        # | 요청 패턴 | `스킬명` | 안전도 | ★ | 패턴 행 매칭
        rows = re.findall(
            r"\|\s*(.+?)\s*\|\s*`/?([^`]+)`\s*\|.*?★",
            section_m.group(0),
        )
        return [
            {
                "skill": r[1].strip().lstrip("/"),
                "trigger_pattern": r[0].strip(),
                "source": "custom_claude_md",
            }
            for r in rows
        ]
    except Exception as e:
        warnings.append(f"[WARN] CLAUDE.md 파싱 실패 (커스텀 게이트 누락 가능): {e}")
        return []


def _normalize(name: str) -> str:
    return name.lower().replace(" ", "-").replace("/", "-")


def _merge_gates(json_gates: list[dict], claude_gates: list[dict]) -> list[dict]:
    """정규화된 스킬명 기준 dedup.

    hard-gates.json 항목이 우선. CLAUDE.md에만 있는 게이트는 source='custom_claude_md'로 추가.
    CLAUDE.md에도 있는 항목은 custom_trigger_pattern 필드를 보강한다.
    """
    merged: dict[str, dict] = {_normalize(g["skill"]): dict(g) for g in json_gates}
    for g in claude_gates:
        key = _normalize(g["skill"])
        if key not in merged:
            merged[key] = dict(g)
        else:
            merged[key]["custom_trigger_pattern"] = g.get("trigger_pattern")
    return list(merged.values())
