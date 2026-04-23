---
name: skill-advisor
description: 설치된 스킬의 커버리지를 진단하고 활용법을 안내하는 도구. --scan으로 전체 스킬 상태를 점검하고, --enrich로 특정 스킬의 트리거 개선 제안을 dry-run 출력한다. SKILL.md를 직접 수정하지 않으며, 제안만 출력한다 (read-only 원칙). 스킬 점검, 스킬 진단, 스킬 활용법 확인, 설치된 스킬 분석, 스킬 커버리지 검토 시 활용.
---

<!--trigger_conditions
schema_version: "0.1"
utterance_patterns:
  ko: ["스킬 점검", "스킬 진단", "스킬 활용법", "스킬 커버리지", "스킬 분석", "스킬 상태", "설치된 스킬", "스킬 추천", "어떤 스킬", "스킬 리뷰", "스킬 확인", "스킬 현황"]
  en: ["skill check", "skill coverage", "skill audit", "skill usage", "skill advisor", "installed skills", "skill recommendation", "skill review"]
file_path_globs: []
tool_events: []
risk_level: "low"
pinned: false
conflicts_with: []
-->

# /skill-advisor

> 설치된 스킬 커버리지 진단 + 활용법 안내 도구. **read-only 원칙** — SKILL.md를 직접 수정하지 않는다.

## 사용법

```
/skill-advisor              → 전체 스킬 현황 보고 (--scan 기본)
/skill-advisor --scan       → 커버리지 진단 (severity 분류)
/skill-advisor --scan --json → JSON 형식으로 출력
/skill-advisor --enrich [스킬명]  → 특정 스킬 분석 + SkillPatchProposal dry-run 출력
```

## 역할 경계

| 역할 | 스킬 | 설명 |
|------|------|------|
| 생성·편집 | skill-creator | SKILL.md 신규 작성·수정 |
| 일괄 생성 | skill-factory | 템플릿 기반 스킬 생성 |
| 목록·CRUD | manage-skills | 스킬 설치·삭제·관리 |
| **진단·안내** | **skill-advisor** | **커버리지 분석 + 활용법 제안 (read-only)** |

## I/O 계약

| 항목 | 정의 |
|------|------|
| stdin | 없음 |
| stdout | 텍스트 보고서 (--json 시 JSON array) |
| stderr | 실행 오류 메시지 |
| exit 0 | 성공 (이슈 없음) |
| exit 1 | 이슈/경고 발견 (CRITICAL·HIGH·MEDIUM 포함) |
| exit 2 | 실행 실패 (파일 접근 오류, 파싱 오류 등) |

---

## --scan 모드

설치된 전체 스킬의 트리거 커버리지를 진단한다.

### Phase 1 검출 범위

**검출 가능:**
- C1: 절대 경로 glob이 존재하지 않는 파일 참조
- H0: 모든 트리거 없음 (유령 스킬) — globs + events + utterances 모두 비어있음
- H1: file_path_globs=0, tool_events=0 — 파일 기반 자동 트리거 없음 (utterance 있는 경우)
- M1: 동일 glob 문자열을 2개 이상 스킬이 선언 (문자열 완전 일치만 감지)
- I1: description 비어있음

**검출 불가 (Phase 2 예정):**
- fnmatch 기반 실제 경로 중첩 충돌 (예: `*.ts` vs `src/**/*.ts`)
- confidence 캐시 기반 신선도 검증
- source_type 외부 신뢰 검증 (사칭 감지)

> ⚠ M1 주의: 동일 문자열 완전 일치만 감지하며, fnmatch 경로 중첩 충돌은 감지하지 않습니다. "M1 없음 = 충돌 없음"이 아닙니다.

### 실행 단계

**1단계 — 스킬 인덱스 로드**

```bash
SKILL_INDEX="/tmp/skill-index.json"
FALLBACK_MODE=false

if [ ! -f "$SKILL_INDEX" ]; then
  echo "⚠ skill-index.json 없음 — skill-index.sh 재실행 시도..."
  if ! zsh ~/.claude/hooks/skill-index.sh 2>/dev/null; then
    echo "⚠ skill-index.sh 실패 — ~/.claude/skills/** 직접 스캔으로 fallback"
    FALLBACK_MODE=true
  fi
fi
```

fallback 모드: `~/.claude/skills/*/SKILL.md` 직접 glob 스캔으로 인덱스 없이 분석 진행. 이 경우 보고서 상단에 `[인덱스 없음 — 직접 스캔]` 경고 표시.

**2단계 — 스킬 분류 + 체크리스트 실행**

```python
import json, os
from pathlib import Path

with open("/tmp/skill-index.json") as f:
    skills = json.load(f)

results = []
for item in skills:
    skill_name  = item.get("skill", "?")
    globs       = item.get("file_path_globs", [])
    events      = item.get("tool_events", [])
    desc        = item.get("description", "")
    utterances  = item.get("utterance_patterns", {})
    has_utterances = bool(
        utterances.get("ko") or utterances.get("en")
    )

    issues = []

    # C1: 깨진 절대 경로 참조
    for g in globs:
        if g.startswith("/") and not Path(g).exists():
            issues.append({"severity": "critical", "code": "C1",
                           "msg": f"깨진 참조: {g}"})

    # 트리거 분류
    if len(globs) == 0 and len(events) == 0:
        if not has_utterances:
            # H0: 유령 스킬 — 어떤 트리거도 없음
            issues.append({"severity": "high", "code": "H0",
                           "msg": "모든 트리거 없음 (유령 스킬) — 호출 방법이 없습니다"})
        else:
            # 수동 전용 — utterance_patterns만 있음, H1 경고 제외
            issues.append({"severity": "info", "code": "H1-M",
                           "msg": "[수동 전용] utterance 기반 트리거만 존재 — 파일 기반 자동 로드 없음"})
    elif len(globs) == 0:
        # H1: utterance 또는 events가 있지만 globs 없음
        issues.append({"severity": "high", "code": "H1",
                       "msg": "file_path_globs 없음 — 파일 편집 시 자동 로드 불가"})

    # I1: description 비어있음
    if not desc.strip():
        issues.append({"severity": "info", "code": "I1",
                       "msg": "description 비어있음 — 색인 품질 저하"})

    results.append({
        "skill": skill_name,
        "globs": len(globs),
        "events": len(events),
        "has_utterances": has_utterances,
        "issues": issues
    })
```

**3단계 — M1 중복 glob 감지**

모든 스킬의 glob을 비교하여 동일 문자열을 2개 이상 스킬이 선언하면 MEDIUM 경고.

**4단계 — 결과 출력**

severity 순 (critical → high → medium → info):

```
## /skill-advisor --scan 결과 (2026-04-23)
⚠ M1 주의: 동일 문자열 완전 일치만 감지 (fnmatch 중첩 감지는 Phase 2)

### 스킬별 현황
| 스킬 | globs | events | 분류 | 이슈 |
|------|-------|--------|------|------|
| doc-coauthoring  | 8 | 10 | 정상 | — |
| skill-creator    | 7 | 12 | 정상 | — |
| skill-advisor    | 0 |  0 | 수동 전용 | ℹ H1-M |
...

### 이슈 목록
[CRITICAL] skill-name: C1 깨진 참조: /path/to/file
[HIGH]     skill-name: H0 유령 스킬 — 모든 트리거 없음
[HIGH]     skill-name: H1 file_path_globs 없음
[MEDIUM]   skill-a, skill-b: M1 동일 glob "**/SKILL.md" — 2개 스킬 선언
[INFO]     skill-name: I1 description 비어있음
```

### severity 정의

| 코드 | severity | 의미 | 자동 분류 예외 |
|------|----------|------|--------------|
| C1 | critical | 존재하지 않는 절대 경로 참조 | — |
| H0 | high | 모든 트리거 없음 (유령 스킬) | — |
| H1 | high | file_path_globs=0 (events/utterance 있을 때) | — |
| H1-M | info | 수동 전용 (utterance만 있고 globs=events=0) | skill-advisor 자신 포함 |
| M1 | medium | 동일 glob 문자열 중복 선언 | — |
| I1 | info | description 비어있음 | — |

---

## --enrich 모드

특정 스킬을 분석하여 트리거 개선 제안을 SkillPatchProposal JSON으로 출력한다.

### 실행 단계

**1단계 — 스킬 조회**

`--enrich [스킬명]`: 인덱스에서 skill_path 조회.
중복이면 목록 출력 + 선택 요청. absolute skill_path로 직접 지정 가능.

**2단계 — SKILL.md 완독**

인덱스에서 skill_path 획득 후 Read 툴로 전체 읽기.

**3단계 — source_type 판단**

```python
def get_source_type(skill_path: str, skill_meta: dict) -> str:
    # 1순위: frontmatter source 필드
    if skill_meta.get("source") == "anthropic":
        return "official"
    # 2순위: 경로 휴리스틱 (fallback)
    if "anthropics/skills" in skill_path:
        return "official"
    elif ".claude/skills" in skill_path or "claude-forge/skills" in skill_path:
        return "local"
    return "third_party"
```

> ⚠ Phase 1 한계: source_type 판별은 경로 패턴 기반이며, official 사칭을 감지하지 못합니다.

| source_type | 웹 검색 | 설명 |
|-------------|---------|------|
| official | 허용 | anthropics/skills GitHub README 검색 |
| local | 불허 | 로컬 SKILL.md 분석만 |
| third_party | 불허 | 분석 제외 (신뢰성 불명) |

**4단계 — 웹 검색 (official 한정)**

```
WebSearch: "anthropics/skills {스킬명} github trigger conditions"
WebSearch: "anthropics/skills {스킬명} site:github.com"
```

**5단계 — 개선 제안 생성 + confidence 산출**

confidence 기준:
- `high`: official README에서 직접 인용한 패턴
- `medium`: 웹 검색 결과 추론 / 로컬 SKILL.md 내용 기반
- `low`: 파일 구조·경로명에서 추론

Phase 1: 캐시 없이 매번 검색. fetched_at은 현재 실행 시각으로 채움.

**6단계 — SkillPatchProposal JSON 출력**

```json
[
  {
    "schema_version": "1.0",
    "skill": "doc-coauthoring",
    "target_field": "file_path_globs",
    "proposal_type": "add_glob",
    "value": "**/*.mdx",
    "current_value": ["**/*.md", "**/*-spec.md"],
    "source": "official_readme",
    "source_url": "https://github.com/anthropics/skills/...",
    "fetched_at": "2026-04-23T10:00:00+0900",
    "confidence": "high",
    "reason": "GitHub README에서 MDX 파일 처리 명시"
  }
]
```

**Phase 1 지원 proposal_type (4개):**
- `add_glob`: file_path_globs에 패턴 추가
- `update_description`: description 텍스트 개선
- `fix_path`: 깨진 경로 수정
- `update_utterance`: utterance_patterns ko/en 업데이트

**Phase 2 예정 (3개):** `remove_glob`, `add_event`, `update_risk_level`

미지원 제안 표시: `"status": "unsupported_in_phase1"`

**스키마 버전 정책 (v1.0):**
- 마이너 변경(1.x → 1.y): 하위 호환 (신규 필드 optional)
- 메이저 변경(1.x → 2.x): breaking — skill-creator --apply-proposal 업데이트 필요

> **승인 게이트**: SkillPatchProposal 출력 후 사용자에게 "이 제안을 skill-creator를 통해 적용할까요?"를 묻는다. 직접 SKILL.md를 수정하지 않는다.

---

## Phase 2 진입 조건 (--apply 활성화 조건)

현재 --apply는 비활성화 상태. 아래 체크리스트가 모두 완료되면 Phase 2 진입:

- [ ] flock 기반 SKILL.md 파일 잠금 프로토콜 구현
- [ ] SKILL.md frontmatter에 `who_last_modified` 메타데이터 추가
- [ ] skill-creator에 `--apply-proposal [JSON파일]` 서브커맨드 구현
- [ ] 최소 테스트 케이스 각 proposal_type별 1개 이상 (`pytest ~/.claude/skills/skill-advisor/tests/`)
- [ ] 사용자 명시 승인 (ai-role-assignment-core.md §1 HIL 수락 기준)

---

## 실패 모드

| 상황 | 처리 | exit code |
|------|------|-----------|
| skill-index.json 없음 + skill-index.sh 성공 | 계속 진행 | 0 또는 1 |
| skill-index.json 없음 + skill-index.sh 실패 | 직접 스캔 fallback + 경고 | 1 |
| SKILL.md 읽기 실패 | 해당 스킬 skip + `[읽기 실패]` | 1 |
| 웹 검색 실패 | 로컬 분석만 + `[웹 검색 실패]` 표시 | 1 |
| JSON 파싱 오류 | 오류 메시지 stderr + 즉시 종료 | 2 |
| 파일 접근 권한 오류 | 오류 메시지 stderr + 즉시 종료 | 2 |

---

## 설계 결정 기록

- **명칭**: `/skill-advisor` — DA 2회 Finalized (2026-04-23)
- **read-only 원칙**: SKILL.md 직접 수정 불가 — Phase 2 체크리스트 완료 후에만 --apply 활성화
- **수동 전용 분류**: file_path_globs=[] + tool_events=[] + utterance_patterns 있음 → H1-M(info). 세 필드 모두 비어있으면 H0(high).
- **skill-index.json fallback**: 파일 없거나 재생성 실패 시 직접 스캔으로 진행
- **Phase 1 M1 한계**: 동일 문자열 완전 일치만 감지. fnmatch 중첩 감지는 Phase 2.
- **exit code**: 기존 도구 관례 준수 (0=성공, 1=이슈/경고, 2=실행 실패)
- **OCP 허용**: file_path_globs=[] — 수동 호출 전용 도구
