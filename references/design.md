# skill-advisor 설계 결정 기록

DA chain 세션 로그: /tmp/da-chain-1776898517 (설계 검증), /tmp/da-chain-1776899602 (명칭 검증)

## 핵심 결정

| 결정 | 내용 | 근거 |
|------|------|------|
| 명칭 | /skill-advisor | 기능 전달력 최우선. /skill-health 탈락(건강 혼동), /skill-guide 탈락(수동 느낌) |
| Phase 1 범위 | --scan + --enrich dry-run | read-only 원칙. --apply는 Blocker 3개 해결 후 |
| SKILL.md 쓰기 권한 | skill-creator 단독 | Split-Brain 방지 |
| 자기 참조 | H1 경고 제외 | 의도적 수동 호출 전용 도구 |

## Phase 1 Blocker (해결 완료)

1. confidence 산출 기준: official README→high, 추론→medium, 로컬→low, 90일+→강등
2. SkillPatchProposal 스키마: schema_version, target_field, current_value, proposal_type 열거형 포함
3. Phase 2 진입 조건: SKILL.md 내 체크리스트 형태로 명시

## SkillPatchProposal 스키마 v1.0

```json
{
  "schema_version": "1.0",
  "skill": "string",
  "target_field": "file_path_globs | tool_events | description | utterance_patterns",
  "proposal_type": "add_glob | update_description | remove_glob | fix_path | add_event",
  "value": "추가/변경할 값",
  "current_value": "현재 값 (롤백 기준)",
  "source": "official_readme | web_search | local_analysis",
  "source_url": "string (optional)",
  "fetched_at": "ISO8601",
  "confidence": "high | medium | low",
  "reason": "근거 설명"
}
```
