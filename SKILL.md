---
name: skill-advisor
description: "(hook)"
argument-hint: '[--scan] | --scan --json | --enrich <skill-name> | --session-review [--confirm | --json | --jsonl <path>] | --update [<skill>] [--apply] [--yes] [--dry-run] [--json] [--keep-backup] [--no-listing-audit] | --listing-audit [--apply] [--json]'
---

<!--trigger_conditions
schema_version: "0.1"
utterance_patterns:
  ko: ["스킬 점검", "스킬 진단", "스킬 활용법", "스킬 커버리지", "스킬 분석", "스킬 상태", "설치된 스킬", "스킬 추천", "어떤 스킬", "스킬 리뷰", "스킬 확인", "스킬 현황", "작업 후 스킬", "세션 리뷰", "로드되지 않은 스킬", "Hard Gate 누락", "Hard Gate 확인", "게이트 점검", "세션 회고", "스킬 게이트"]
  en: ["skill check", "skill coverage", "skill audit", "skill usage", "skill advisor", "installed skills", "skill recommendation", "skill review", "session review", "missed skill", "post-work skill check", "hard gate", "hard gate missed", "hard gate check", "gate compliance", "session retrospective"]
file_path_globs:
  - "**/skill-advisor/scripts/**"
tool_events: []
risk_level: "low"
pinned: false
conflicts_with: []
-->

# /skill-advisor

> 설치된 스킬 커버리지 진단 + 활용법 안내 도구. **read-only 원칙** — SKILL.md를 직접 수정하지 않는다.

---

## ARGUMENTS 없이 호출된 경우

ARGUMENTS가 비어 있으면 아래 메시지를 출력한 후 **기본 동작(--scan)을 실행**한다.

```
/skill-advisor  [--scan] | --scan --json | --enrich <skill-name> | --session-review [--confirm | --json | --jsonl <path>] | --update [<skill>] [--apply] [--yes] [--json]

Options:
  (없음 / --scan)                    설치된 전체 스킬 커버리지 진단 (기본)
  --scan --json                      JSON 형식으로 진단 결과 출력 (CI/자동화용)
  --enrich <skill-name>              특정 스킬 심층 분석 + SkillPatchProposal JSON 출력
  --session-review                   작업 후 편집 파일 기반 관련 스킬 후보 추천
  --session-review --confirm         JSONL 세션 직접 선택 (⚠ 대화형 터미널 전용)
  --session-review --json            JSON 형식으로 session-review 결과 출력
  --session-review --jsonl <path>    특정 JSONL 파일 분석 (절대 우선순위 — Track1 자동 detection skip)
  --session-scan                     alias for --session-review (CSR #829 #2, 2026-05-24)
  --update [<skill>]                 업스트림 URL 기반 업데이트 체크 (전체 또는 지정 스킬)
  --update --apply [<skill>]         업데이트 실제 적용 (trigger_conditions 자동 보존)
  --update --apply --yes             자동 진행 모드 (y/N 확인 생략, CI 전용)
  --update --json                    JSON 출력 (CI/자동화용)
  --update --keep-backup             apply 후 .bak 파일 보존
  --update --refresh-sources         skill-sources.json 재생성 안내
  --update --no-listing-audit        apply 후 자동 listing-audit 실행 억제
  --listing-audit                    skillListing 예산 진단 (shortened 예측 + hook 최적화 후보)
  --listing-audit --apply            hook 스킬 description "(hook)"으로 원자적 수정
  --listing-audit --json             JSON 형식으로 진단 결과 출력
```

---

## 모드 진입 헤더 (각 모드 실행 전 출력)

ARGUMENTS가 있으면 해당 모드에 맞는 헤더를 한 줄 출력한 뒤 실행한다:

| ARGUMENTS | 헤더 출력 |
|-----------|---------|
| 없음 / `--scan` | `▶ /skill-advisor --scan  (전체 스킬 커버리지 진단)` |
| `--scan --json` | `▶ /skill-advisor --scan --json  (JSON 출력)` |
| `--enrich <name>` | `▶ /skill-advisor --enrich <name>  (심층 분석 + SkillPatchProposal)` |
| `--session-review` | `▶ /skill-advisor --session-review  (편집 파일 기반 스킬 후보 추천)` |
| `--session-review --confirm` | `▶ /skill-advisor --session-review --confirm  (세션 선택 후 분석)` |
| `--session-review --json` | `▶ /skill-advisor --session-review --json  (JSON 출력)` |
| `--session-review --jsonl <path>` | `▶ /skill-advisor --session-review --jsonl <path>  (지정 세션 분석)` |
| `--update [<skill>]` | `▶ /skill-advisor --update  (업스트림 업데이트 체크 및 적용)` |
| `--update --apply` | `▶ /skill-advisor --update --apply  (업데이트 적용 — y/N 확인, 완료 후 listing-audit --apply 자동 실행)` |
| `--update --apply --yes` | `▶ /skill-advisor --update --apply --yes  (자동 진행 모드, 완료 후 listing-audit --apply 자동 실행)` |
| `--listing-audit` | `▶ /skill-advisor --listing-audit  (skillListing 예산 진단)` |
| `--listing-audit --apply` | `▶ /skill-advisor --listing-audit --apply  (hook 스킬 description 최적화 — y/N 확인)` |

---

## 사용법

```
/skill-advisor              → 전체 스킬 현황 보고 (--scan 기본)
/skill-advisor --scan       → 커버리지 진단 (severity 분류)
/skill-advisor --scan --json → JSON 형식으로 출력
/skill-advisor --enrich [스킬명]  → 특정 스킬 분석 + SkillPatchProposal dry-run 출력
/skill-advisor --session-review   → 작업 후 편집 파일 기반 관련 스킬 후보 추천
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
- C1-b: `hard-gates.json`에 선언된 Hard Gate의 file_path가 미설치 상태 (SSOT ↔ 설치 불일치)
- C2: Hard Gate(Tier A/B/C) 스킬이 `source_kind=yaml_frontmatter`로만 존재 — 자동 로드 트리거 없음
- H0: 모든 트리거 없음 (유령 스킬) — globs + events + utterances 모두 비어있음
- H1: file_path_globs=0, tool_events=0 — 파일 기반 자동 트리거 없음 (utterance 있는 경우)
- H1-Y: `source_kind=yaml_frontmatter` — YAML frontmatter만 있는 수동 전용 스킬 (INFO)
- M1: 동일 glob 문자열을 2개 이상 스킬이 선언 (문자열 완전 일치만 감지)
- I1: description 비어있음
- OPT-1: `trigger_block` + `file_path_globs>0` + `description>100자` — hook 스킬 description 단축 권장 (`"(hook)"` 최적화 후보)

**검출 불가 (Phase 2 예정):**
- fnmatch 기반 실제 경로 중첩 충돌 (예: `*.ts` vs `src/**/*.ts`)
- confidence 캐시 기반 신선도 검증
- source_type 외부 신뢰 검증 (사칭 감지)

> ⚠ M1 주의: 동일 문자열 완전 일치만 감지하며, fnmatch 경로 중첩 충돌은 감지하지 않습니다. "M1 없음 = 충돌 없음"이 아닙니다.

### 실행 단계

**1단계 — 스킬 인덱스 로드**

```bash
SKILL_INDEX="$HOME/.claude/da-tools/skill-index.json"   # CSR #1260: da-tools primary SSOT
[ -f "$SKILL_INDEX" ] || SKILL_INDEX="/tmp/skill-index.json"   # legacy /tmp fallback
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

# CSR #1260: da-tools primary SSOT → /tmp legacy fallback
_idx = Path.home() / ".claude" / "da-tools" / "skill-index.json"
if not _idx.exists():
    _idx = Path("/tmp/skill-index.json")
data = json.load(open(_idx))
# v1/v2 하위 호환
if isinstance(data, list):
    skills = data
elif isinstance(data, dict):
    skills = data.get("skills", [])
else:
    skills = []

# hard-gates.json 로드 (C2·C1-b 판정용 SSOT). 없거나 스키마 미지원이면 빈 셋 fallback.
hard_gate_map = {}   # id → gate dict
hard_gate_ids_critical = set()  # Tier A/B/C id set
hg_path = Path(os.path.expanduser("~/.claude/hard-gates.json"))
if hg_path.exists():
    try:
        hg = json.loads(hg_path.read_text(encoding="utf-8"))
        for g in hg.get("gates", []):
            gid = g.get("id")
            if gid:
                hard_gate_map[gid] = g
                if g.get("tier") in ("A", "B", "C"):
                    hard_gate_ids_critical.add(gid)
    except (json.JSONDecodeError, OSError):
        pass

results = []
for item in skills:
    skill_name  = item.get("skill", "?")
    globs       = item.get("file_path_globs", [])
    events      = item.get("tool_events", [])
    desc        = item.get("description", "")
    utterances  = item.get("utterance_patterns", {})
    source_kind = item.get("source_kind", "trigger_block")
    has_utterances = bool(
        utterances.get("ko") or utterances.get("en")
    )

    issues = []

    # C1: 깨진 절대 경로 참조
    # glob 메타문자(* ? [)가 있으면 리터럴 경로가 아니라 패턴 — glob-expand 후
    # "매칭 0건일 때만" 경고한다. transient 패턴(/tmp/csr-*.md 등)은 현재 매칭이
    # 없어도 정상 트리거이므로 경고 제외 (CSR #969: C1 glob false-positive 수정).
    import glob as _glob
    for g in globs:
        if not g.startswith("/"):
            continue
        if any(ch in g for ch in "*?["):
            # 패턴: 디렉토리(부모)가 실재하고 transient(/tmp, /var/folders 등)면 정상
            parent = os.path.dirname(g.split("*")[0].rstrip("/")) or "/"
            is_transient = g.startswith("/tmp/") or "/T/" in g or g.startswith("/var/folders/")
            if not is_transient and not _glob.glob(g) and not Path(parent).exists():
                issues.append({"severity": "critical", "code": "C1",
                               "msg": f"깨진 glob (부모 경로 부재, 매칭 0): {g}"})
        elif not Path(g).exists():
            issues.append({"severity": "critical", "code": "C1",
                           "msg": f"깨진 참조: {g}"})

    # C2: Hard Gate 스킬이면서 source_kind=yaml_frontmatter — 자동 로드 불가
    if skill_name in hard_gate_ids_critical and source_kind == "yaml_frontmatter":
        gate = hard_gate_map.get(skill_name, {})
        tier = gate.get("tier", "?")
        issues.append({"severity": "critical", "code": "C2",
                       "msg": f"Hard Gate(Tier {tier}) 스킬이 yaml_frontmatter 전용 — 자동 로드 트리거 없음, 유명무실"})

    # H1-Y: yaml_frontmatter 스킬 — 수동 전용 (자동 로드 불가)
    if source_kind == "yaml_frontmatter":
        issues.append({"severity": "info", "code": "H1-Y",
                       "msg": "[YAML 수동 전용] trigger_conditions 없음 — /skill-creator로 추가 권장"})
    else:
        # 트리거 분류 (trigger_block 스킬만 해당)
        if len(globs) == 0 and len(events) == 0:
            if not has_utterances:
                issues.append({"severity": "high", "code": "H0",
                               "msg": "모든 트리거 없음 (유령 스킬) — 호출 방법이 없습니다"})
            else:
                issues.append({"severity": "info", "code": "H1-M",
                               "msg": "[수동 전용] utterance 기반 트리거만 존재 — 파일 기반 자동 로드 없음"})
        elif len(globs) == 0 and len(events) > 0:
            issues.append({"severity": "info", "code": "H1-E",
                           "msg": "[이벤트 전용] tool_events 기반 트리거만 존재 — 파일 경로 기반 자동 로드 없음"})

    # I1: description 비어있음 ("(hook)"은 valid placeholder — 제외)
    if not desc.strip() and desc != "(hook)":
        issues.append({"severity": "info", "code": "I1",
                       "msg": "description 비어있음 — 색인 품질 저하"})

    # OPT-1: trigger_block + file_path_globs>0 + description>100자 → "(hook)" 단축 권장
    # opt-out: SKILL.md YAML에 hook_no_opt: true 플래그 시 억제
    # CSR #969: utterance 보유 OR critical-tier(A/B/C) Hard Gate 는 제외 —
    #   이런 스킬의 description 은 invocation 라우팅 신호(파일 glob 자동 트리거가
    #   아니라 utterance/수동 호출 의존)라 "(hook)" 단축 시 discoverability 손상.
    #   (auto-loader 는 critical 미주입 → glob 자동 트리거도 불확실, #966 참조)
    skill_meta = item  # item이 곧 meta dict
    if (source_kind == "trigger_block"
            and len(globs) > 0
            and len(desc) > 100
            and desc != "(hook)"
            and not has_utterances
            and skill_name not in hard_gate_ids_critical
            and not skill_meta.get("hook_no_opt", False)):
        issues.append({"severity": "info", "code": "OPT-1",
                       "msg": f"[listing 최적화] hook 스킬이지만 description {len(desc)}자 — "
                              f"'(hook)' 단축 시 예산 절약. 억제: YAML에 hook_no_opt: true 추가"})

    results.append({
        "skill": skill_name,
        "source_kind": source_kind,
        "globs": len(globs),
        "events": len(events),
        "has_utterances": has_utterances,
        "issues": issues
    })

# C1-b: SSOT ↔ 설치 불일치 (스킬별이 아닌 전역 단계)
# hook 구현 게이트 제외 (CSR #969: C1-b hook-gate false-positive 수정).
# tool_events_bash_if 있음(=hook 강제) 또는 tier=D advisory면 SKILL.md file_path는
# 인벤토리 placeholder일 수 있음 — 미설치를 critical로 오탐하지 않는다.
installed_skill_ids = {item.get("skill") for item in skills}
for gate_id, gate in hard_gate_map.items():
    fp_raw = gate.get("file_path", "")
    fp = Path(os.path.expanduser(fp_raw)) if fp_raw else None
    is_hook_impl = bool(gate.get("tool_events_bash_if"))
    is_advisory = gate.get("tier") == "D"
    if fp and not fp.exists():
        if is_hook_impl or is_advisory:
            # hook/advisory 게이트 — file_path는 placeholder, INFO로 강등
            results.append({
                "skill": f"<SSOT:{gate_id}>", "source_kind": "ssot_only",
                "globs": 0, "events": 0, "has_utterances": False,
                "issues": [{"severity": "info", "code": "C1-b-hook",
                            "msg": f"SSOT file_path placeholder (hook/advisory 구현): {gate_id} → {fp_raw}"}]
            })
        else:
            # 진짜 critical: A/B/C tier + 비-hook 게이트가 미설치
            results.append({
                "skill": f"<SSOT:{gate_id}>", "source_kind": "ssot_only",
                "globs": 0, "events": 0, "has_utterances": False,
                "issues": [{"severity": "critical", "code": "C1-b",
                            "msg": f"SSOT 선언 Hard Gate 미설치: {gate_id} → {fp_raw}"}]
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
| C1-b | critical | SSOT(hard-gates.json) 선언 Hard Gate가 파일 시스템에 미설치 | — |
| C2 | critical | Hard Gate(Tier A/B/C) 스킬이 source_kind=yaml_frontmatter 전용 — 자동 로드 트리거 없음 | — |
| H0 | high | 모든 트리거 없음 (유령 스킬) | — |
| H1-E | info | 이벤트 전용 (tool_events>0, globs=0) | 의도적 설계로 간주, H1-M과 동일 처리 |
| H1-M | info | 수동 전용 (utterance만 있고 globs=events=0) | skill-advisor 자신 포함 |
| H1-Y | info | YAML frontmatter 수동 전용 (source_kind=yaml_frontmatter) | 커뮤니티 스킬 기본값 — /skill-creator로 trigger_conditions 추가 권장 |
| M1 | medium | 동일 glob 문자열 중복 선언 | — |
| I1 | info | description 비어있음 | `"(hook)"` placeholder는 제외 |
| OPT-1 | info | hook 스킬(trigger_block+globs) description > 100자 — `"(hook)"` 단축 권장 | YAML `hook_no_opt: true` 시 억제 |

---

## --listing-audit 모드

`skillListingMaxDescChars`·`skillListingBudgetFraction` 설정 상태와 실제 스킬 description 분포를 진단하여 "N skill descriptions shortened" 문제를 사전 탐지하고 최적화 후보를 제안한다.

### 배경 지식 (바이너리 검증)

Claude Code의 스킬 목록 예산 공식 (v2.1.142 바이너리 확인):
```
char_budget = (contextTokens ?? 200_000) × 4 × skillListingBudgetFraction
```
- 기본값: `skillListingMaxDescChars=1536`, `skillListingBudgetFraction=0.01`
- `"N descriptions shortened"`: description이 `skillListingMaxDescChars`를 초과 시 발생
- `"N descriptions dropped"`: 총 description 합이 `char_budget`을 초과 시 발생 (더 심각)

**hook 스킬 description 규약** (`"(hook)"` 패턴):
- `trigger_block` + `file_path_globs > 0` 스킬은 파일 경로 기반으로 자동 트리거
- 이런 스킬의 description은 시스템 목록에 불필요 → `"(hook)"` (6자) 사용 권장
- **주의**: `description: ""` (빈 문자열)은 사용 금지 — Claude Code가 SKILL.md body 첫 줄을 description으로 fallback하여 `<!--trigger_conditions` 노출 버그 발생

### 실행 단계

**1단계 — settings.json 읽기**

```python
import json, os, math
from pathlib import Path

settings_path = Path(os.path.expanduser("~/.claude/settings.json"))
settings = {}
if settings_path.exists():
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

max_desc_chars = settings.get("skillListingMaxDescChars", 1536)
budget_fraction = settings.get("skillListingBudgetFraction", 0.01)

# char_budget 공식 (200K 고정 기준, × 4 multiplier)
char_budget = 200_000 * 4 * budget_fraction
```

**2단계 — 스킬 인덱스 로드 + 분석**

```python
# CSR #1260: da-tools primary SSOT → /tmp legacy fallback
from pathlib import Path
_idx = Path.home() / ".claude" / "da-tools" / "skill-index.json"
if not _idx.exists():
    _idx = Path("/tmp/skill-index.json")
data = json.load(open(_idx))
skills = data.get("skills", data) if isinstance(data, dict) else data

desc_map = [(s.get("skill","?"), s.get("description",""), s.get("source_kind",""),
             s.get("file_path_globs",[]), s.get("skill_path",""),
             s.get("hook_no_opt", False))
            for s in skills]

total_chars = sum(len(d) for _,d,*_ in desc_map)
shortened_count = sum(1 for _,d,*_ in desc_map if len(d) > max_desc_chars)

# OPT-1 후보: trigger_block + globs>0 + desc>100 + desc!="(hook)" + not hook_no_opt
opt1_candidates = [
    (name, len(desc), path)
    for name, desc, src, globs, path, no_opt in desc_map
    if src == "trigger_block" and len(globs) > 0
    and len(desc) > 100 and desc != "(hook)" and not no_opt
]

# 예산 상태
budget_used_pct = (total_chars / char_budget * 100) if char_budget > 0 else 999
```

**3단계 — 결과 출력**

```
▶ /skill-advisor --listing-audit  (skillListing 예산 진단)

## skillListing 예산 진단 결과

### 현재 설정
| 항목 | 현재값 | 기본값 | 권장 범위 | 상태 |
|------|--------|--------|-----------|------|
| skillListingMaxDescChars | 2000 | 1536 | 1536~2000 | ✅ |
| skillListingBudgetFraction | 0.05 | 0.01 | 0.03~0.05 | ✅ |
| char_budget | 40,000자 | — | — | — |

### description 분포
| 항목 | 값 |
|------|-----|
| 전체 스킬 수 | 68개 |
| 전체 description 합계 | 16,137자 |
| 예산 사용률 | 40% (16,137 / 40,000자) |
| shortened 예상 | 0개 (max_desc_chars=2000 기준) |
| dropped 예상 | 없음 (예산 충분) |

### OPT-1 최적화 후보 (hook 스킬 description 단축 권장)
| 스킬 | description 길이 | 절약 가능 |
|------|----------------|---------|
| (없음) | — | — |

✅ 현재 설정 최적 상태 — 조치 불필요

---
💡 적용하려면: /skill-advisor --listing-audit --apply
```

**4단계 — settings 권장값 제안 출력**

```
### settings.json 권장값 (참고용 — 적용은 /update-config 사용)
{
  "skillListingMaxDescChars": 2000,   // 현재: 2000 ✅ (변경 불필요)
  "skillListingBudgetFraction": 0.05  // 현재: 0.05 ✅ (변경 불필요)
}
```

> settings.json 직접 수정은 `/update-config` 스킬을 사용한다. skill-advisor는 제안만 출력.

### --listing-audit --apply (OPT-1 후보 자동 수정)

OPT-1 후보가 있을 때만 활성화. 없으면 "최적화 대상 없음" 출력 후 종료.

```python
# 후보 목록 표시 + y/N 확인
print("다음 스킬의 description을 '(hook)'으로 수정합니다:")
for name, dlen, path in opt1_candidates:
    print(f"  {name}: {dlen}자 → '(hook)' (6자, {dlen-6}자 절약)")
print("\n계속하시겠습니까? (y/N): ", end="")

# 사용자 확인 후 원자적 수정 (write-temp → fsync → atomic rename)
import shutil, tempfile
for name, dlen, path in opt1_candidates:
    skill_path = Path(path)
    content = skill_path.read_text(encoding="utf-8")
    # description 필드만 교체 (정규식으로 YAML frontmatter 내 description 라인만 수정)
    import re
    new_content = re.sub(
        r'^(description:\s*)".{101,}"',
        'description: "(hook)"',
        content, flags=re.MULTILINE
    )
    # atomic write
    tmp = skill_path.with_suffix(".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    tmp.replace(skill_path)  # atomic rename (POSIX)
    print(f"✅ {name}: description → '(hook)'")
```

**원자성 보장**: write-temp → replace (atomic rename) 패턴. 중간 실패 시 .tmp 파일만 남고 원본 유지.

### --listing-audit --json

JSON 형식 출력:

```json
{
  "settings": {
    "skillListingMaxDescChars": 2000,
    "skillListingBudgetFraction": 0.05,
    "char_budget": 40000
  },
  "stats": {
    "total_skills": 68,
    "total_desc_chars": 16137,
    "budget_used_pct": 40.3,
    "shortened_count": 0,
    "dropped_count": 0
  },
  "opt1_candidates": [],
  "settings_recommendations": {
    "skillListingMaxDescChars": {"current": 2000, "recommended": 2000, "action": "ok"},
    "skillListingBudgetFraction": {"current": 0.05, "recommended": 0.05, "action": "ok"}
  }
}
```

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

## --session-review 모드

작업 완료 후 현재 Claude Code 세션의 활동을 분석하여 스킬 활용 현황을 진단한다.
Hard Gate 준수 여부(추정), 파일 편집 기반 스킬 후보, 도움이 됐을 스킬을 함께 보고한다.

```
/skill-advisor --session-review                      → 즉시 실행 (기본)
/skill-advisor --session-review --confirm            → JSONL 세션 선택 후 실행
/skill-advisor --session-review --max-edits 500      → 파일 변경 이벤트 최대 500개 분석
/skill-advisor --session-review --json               → JSON 출력 (Layer 1 원시 데이터)
/skill-advisor --session-review --jsonl [경로]       → 특정 JSONL 파일 분석
```

**핵심 원칙**: 확정 진단 금지 — 추정 기반 후보 탐지만 허용.
로드 이력은 직접 확인 불가 (Phase 1.5 로드 로그 완료 전).

### 두 트랙 동작

| | Track 1 | Track 2 |
|---|---|---|
| 조건 | `session-retrospective` 스킬 설치 + session_id 획득 가능 (hook stdin JSON 1순위 / env var fallback) | 자동 fallback |
| JSONL 소스 | `get-session.sh` (세션 ID 기반, 정확) | cwd 해시 기반 탐색 |
| 분석 내용 | **동일** | **동일** |
| 출력 | `[Track 1: session-retrospective]` | `[Track 2: built-in]` |

Track 1은 session-retrospective 설치 후 session_id 획득 가능한 세션에서 자동 활성화된다. `CLAUDE_SESSION_ID` 환경변수는 2026-05-01까지 deprecation fallback으로만 유효.

### 실행 방법

Bash 툴로 아래를 실행한다:

```bash
python3 ~/.claude/skills/skill-advisor/scripts/session-review.py
```

`--confirm` 플래그가 있으면 분석 전 JSONL 후보 목록을 표시하고 사용자 선택을 받는다.

### Layer 2: Claude 해석 지시

`session-review.py`가 출력한 JSON을 받아 다음 섹션을 생성한다:

**섹션 3 — 트리거되었어야 할 스킬:**
- `hard_gate_candidates` 중 `detected=false`이고 `triggered_by`가 비어 있지 않은 항목
- Hard Gate(★) 기준 조건 감지됨 → 실행 미확인 상태를 표로 표시
- "이번 작업 상황": `edited_files` + `slash_commands_found` + `triggered_by`로 맥락 생성

```
⚠ Hard Gate (CLAUDE.md 기준, 트리거 감지됨 — 실행 미확인 [ESTIMATED])

| 스킬 | 트리거 조건 | 이번 작업 상황 | 결과 |
|------|-----------|--------------|------|
| verification-before-completion | ★ 완료 선언 전 필수 | SKILL.md 편집, /plan 실행 | 미확인 |
```

**섹션 4 — 도움이 됐을 스킬:**
- `skill_candidates` (file-glob 매칭 기반)
- `hard_gate_candidates` 중 `triggered_by` 있는 항목
- `signal_recommendations` (에러 신호 기반)

> ⚠ `hard_gate_candidates`는 JSONL 슬래시 커맨드 탐지 + 파일 신호 기반 추정 `[ESTIMATED]`.
> Phase 1.5 로드 로그 완료 전까지 신뢰도가 제한적이다.

### Known Limitations

- "이번 작업 상황" 컬럼은 Claude LLM 해석 — JSONL 데이터 품질에 의존
- Hard Gate 탐지는 JSONL user 텍스트 슬래시 커맨드 + 편집 파일 신호 기반 `[ESTIMATED]`
- Track 2: 프로젝트 경로 이동 시 JSONL 매칭 실패 가능
- CLAUDE.md 파싱은 특정 마크다운 형식(한글 ★ 게이트 표)에만 작동 — 다른 형식 사용자는 커스텀 게이트 누락 가능
- `--jsonl` 경로는 `~/.claude/projects/` 또는 `/tmp` 하위만 허용 (보안 제한)

### Phase 1.5 의존성

`--session-review`의 "로드 이력 직접 대조" 기능은 `skill-auto-loader.sh`에 로드 로그 기록이
추가되어야 한다. Phase 1.5 구현 시 아래 두 파일을 동시에 업데이트해야 한다:
- `~/.claude/hooks/skill-auto-loader.sh` (로드 이벤트 기록 추가)
- 이 SKILL.md (로그 경로 및 형식 명시)

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

---

## --update 모드

> `--scan/--enrich/--session-review`는 **read-only 진단 도구** — SKILL.md 수정 절대 금지.
> `--update --apply`는 **업데이트 도구** — 사용자 확인 후 upstream 내용 적용 허용.
> skill-advisor 자신의 SKILL.md 업데이트는 자기 참조 방지를 위해 항상 금지.

### 채널별 동작 매트릭스

| 채널 (`upstream_type`) | check (기본) | apply |
|----------------------|-------------|-------|
| `github_raw` / `anthropic_official` / `microsoft` / `community` | SHA256 비교 + diff 요약 | backup→apply→verify→atomic rename |
| `npm` | npm outdated + npm audit | v1.0: 명령어 출력만 (직접 설치 안 함) |
| `pip` | pip list --outdated | v1.0: 명령어 출력만 (직접 설치 안 함) |
| `local_custom` | 체크 없음 (항상 local-custom) | 해당 없음 |

### 실행 단계

```bash
SKILL_DIR="<skill-advisor scripts 경로>"

# 1. check (기본)
python3 "$SKILL_DIR/update.py" [<skill>] [--json]

# 2. apply (github_raw 채널만 자동 적용; npm/pip는 명령어 출력)
python3 "$SKILL_DIR/update.py" [<skill>] --apply [--yes] [--keep-backup]
```

**실행 전 계획 출력**: `--apply` 전 채널별 동작·부작용 등급을 항상 표로 출력한 후 `y/N` 확인. `--yes` 플래그 시 확인 생략 (CI 모드).

### Post-apply 자동 listing-audit (기본 활성)

`--apply` 완료 후 github_raw 채널에서 1개 이상 적용됐으면 **자동으로 `--listing-audit --apply`를 실행**한다.

**이유**: 업스트림 업데이트는 로컬에서 `"(hook)"`으로 최적화한 description을 원래 값으로 복구할 수 있다. 자동 실행으로 OPT-1 후보를 즉시 재적용한다.

```bash
# --apply 완료 후 적용 수 확인
APPLIED_COUNT=$(결과에서 "→ 적용됨" 라인 수)
NO_LISTING_AUDIT_FLAG=false  # --no-listing-audit 플래그 여부

if [ "$APPLIED_COUNT" -ge 1 ] && [ "$NO_LISTING_AUDIT_FLAG" = "false" ]; then
  echo ""
  echo "━━━ 자동 실행: --listing-audit --apply ━━━"
  # --listing-audit --apply 모드 실행 (OPT-1 후보가 없으면 "최적화 대상 없음" 출력 후 종료)
fi
```

**억제**: `--no-listing-audit` 플래그 명시 시 자동 실행 건너뜀.

### exit code contract

| 코드 | 의미 |
|------|------|
| 0 | 성공 (최신 상태) |
| 1 | 업데이트 가능 항목 있음 |
| 2 | 실행 실패 (fetch 오류 등) |
| 3 | apply 실패, rollback 완료 |
| 4 | apply 실패 + rollback 실패 (데이터 손실 위험 — .bak 경로 출력) |

### local_overrides 보존 (github_raw 채널)

1. 로컬 SKILL.md에서 `<!--trigger_conditions...-->` 블록 추출
2. upstream 내용으로 교체 (atomic rename)
3. trigger_conditions 블록을 YAML frontmatter 직후 재삽입

**npm 채널 주의**: node_modules 내 SKILL.md에 trigger_conditions가 있으면 `--apply` 차단.
`skill-creator`로 trigger_conditions를 기본 SKILL.md로 이전 후 재실행 필요.

### SSOT

`~/.claude/skill-sources.json` — 65개+ 스킬의 upstream URL·채널·상태 정보.
`scripts/update.py` 오케스트레이터, `scripts/channels/{github_raw,npm,pip}.py` 채널별 핸들러.

### Known Limitations (v1.0)

- npm/pip --apply: 명령어 출력만 (직접 실행 없음) → v2.0에서 지원 예정
- trigger_conditions SKILL.md 분리: skill-index.sh 리팩터링 후 v2.0에서 지원
- 동시 실행 락: v2.0 예정 (현재 atomic write로 최소 보호)

---

## 설계 결정 기록

- **명칭**: `/skill-advisor` — DA 2회 Finalized (2026-04-23)
- **read-only 원칙**: SKILL.md 직접 수정 불가 — Phase 2 체크리스트 완료 후에만 --apply 활성화
- **수동 전용 분류**: file_path_globs=[] + tool_events=[] + utterance_patterns 있음 → H1-M(info). 세 필드 모두 비어있으면 H0(high).
- **이벤트 전용 분류**: file_path_globs=[] + tool_events>0 → H1-E(info). 의도적 설계로 간주, H1 경고 제외.
- **skill-index.json fallback**: 파일 없거나 재생성 실패 시 직접 스캔으로 진행
- **Phase 1 M1 한계**: 동일 문자열 완전 일치만 감지. fnmatch 중첩 감지는 Phase 2.
- **exit code**: 기존 도구 관례 준수 (0=성공, 1=이슈/경고, 2=실행 실패)
- **OCP 허용**: file_path_globs=[] — 수동 호출 전용 도구
- **OPT-1 opt-out 방식**: whitelist 대신 opt-out(hook_no_opt: true) 채택 — 새 hook 스킬 추가 시 자동 감지, 예외만 명시 (ChatGPT DA H-1 반영, 2026-05)
- **"(hook)" placeholder 규약**: trigger_block + file_path_globs>0 스킬에 적용. `""` 사용 금지 (body fallback 버그). hook_no_opt: true로 억제 가능 (2026-05 세션 검증)
- **--listing-audit 범위**: settings.json 읽기(진단) + SKILL.md 수정(--apply). settings.json 수정은 제안만 — 적용은 /update-config 위임 (DA H-1 SRP 반영)
- **char_budget 공식**: 200K × 4 × fraction = 문자 예산 (바이너리 v2.1.142 검증, 2026-05)
- **post-apply 자동 listing-audit**: `--update --apply` 완료 후 github_raw 1개+ 적용 시 `--listing-audit --apply` 자동 실행 (기본 ON). 억제: `--no-listing-audit` 플래그. 이유: 업스트림 업데이트가 로컬 "(hook)" 최적화를 덮어쓸 수 있음 (2026-05 실증)

---

## CSR #829 변경 (2026-05-24, P1 채택 — 6 보강 실증 완료)

본 SKILL.md + scripts/session-review.py 첫 사용자 실증 (session 33cb50b0) 발견 6 문제 보강. CSR #784·#808·#809·#827·#828 G-13 carry-forward에서 발견.

### 적용 변경
1. **`--session-scan` alias 추가** (#2): 사용자 typo 보호 — `--session-review` 동일 효과. argparse `dest="session_scan_alias"`. SKILL.md 사용법 섹션 명시.
2. **`--jsonl <path>` 절대 우선순위 보장** (#3): Track1 자동 detection skip 명시. stderr `[INFO] --jsonl 명시 사용` 가시성 로그.
3. **Phase 1.5 가속** (#1): `~/.claude/hooks/skill-auto-loader.sh` 로드 로그 추가 → `~/.claude/da-tools/skill-load.jsonl` JSONL (3-SID schema 포함, CSR #831 통합).
4. **UserPromptSubmit hook keyword detection** (#4): `~/.claude/hooks/skill-keyword-injector.sh` 신설 — csr-task utterance miss 회피 (paddo.dev Controllability Problem). Issue #38 opencode-skills 답습.
5. **wrapper command 트리거** (#5): `~/.claude/hooks/guide-board-detector.sh` 신설 (PreToolUse:Bash) + `hard-gates.json` `tool_events_bash_if` schema 확장. Bash:matches 정규식 미지원 발견 → Plan #11 정정 (Permission rule syntax 와일드카드).
6. **operator skip 자동 audit** (#6): `~/.claude/hooks/plan-skip-audit.sh` 신설 — plan 면제 키워드 + transcript edit count cross-check → `~/.claude/da-tools/plan-skip.jsonl` event `plan_skip_invalid|justified`.

### 인터넷 학습 근거
- [paddo.dev Controllability Problem](https://paddo.dev/blog/claude-skills-controllability-problem/) — utterance/wrapper miss 회피 근거
- [Issue #38 opencode-skills](https://github.com/malhashemi/opencode-skills/issues/38) — UserPromptSubmit hook 강제 evaluation 패턴
- [Anthropic Hooks reference](https://code.claude.com/docs/en/hooks) — `if: Bash(...)` Permission rule syntax 와일드카드 (Plan #11 정정 근거)

### cross-ref
- CSR #830: #4·#5·#6 직접 연계
- CSR #831: #1 skill-load.jsonl 3-SID schema 통합 (Anthropic Issue #26964 대응)

---

## CSR #825 G3' 축소 변경 (2026-05-24, DA chain Tier 1 N → 옵션 B 채택)

본 SKILL.md 및 `scripts/session-review.py` 의 G 통합 6 변경 중 3 변경만 채택 (A·E·F 축소). DA chain Tier 1 (4-AI 순차) 결과 N + 옵션 B (Layer 4 폐기) 적용.

### A — Detection 4 status + schema_version: 2

`build_hard_gate_candidates()` 출력 `detected` 필드를 4 string status 로 분리:

| Status | 정의 | 기존 (v1) |
|--------|------|----------|
| `"executed"` | slash_command_found 매칭 (실행 evidence) | `true` |
| `"triggered"` | triggered_by 비어있지 않음 (조건 매칭, 실행 미확인) | `false` (false negative) |
| `"artifact_confirmed"` | gate-artifacts/.done 마커 확인 | `"artifact"` |
| `"miss"` | 모든 조건 미매칭 | `false` |

**Backward compat**: `legacy_detected` 필드 보존 (60일 deprecation, drop 2026-07-23). `schema_version: 2` 필드 신규.

**핵심 회피**: CSR #823 본 세션 csr-task false negative 사례 (triggered_by 있는데 detected=false) — CSR #825 C-A1 해소.

### E — unified_skill_view + thresholds.json 외부화

`build_unified_skill_view()` 신규 함수 — Hard Gate + slash_command + file-glob + signal 통합 view.

**Ordering rule**:
1. Hard Gate (Tier A → B → C → D → ?)
2. slash_command (Hard Gate 미포함)
3. file-glob (skill_candidates)
4. signal_recommendations

**Top-N cap**: 기본 10 (CW-HIGH-2 visual complexity 회피).

**Thresholds 외부화**: `~/.claude/skill-advisor/thresholds.json` — signal_thresholds (large_change / refactor / tdd / da_chain) + default_mode: conservative.

User override: `--threshold-config <path>` flag.

### F (축소) — DA chain Tier 분리 + Composition reference

본 SKILL.md 변경 시 DA chain Tier 분리:

| 분류 | 기준 | DA chain Tier |
|------|------|:-------------:|
| **major** | frontmatter 변경 / ★ Hard Gate line 추가/삭제/수정 / tool 목록 변경 / trigger pattern 변경 | **Tier 1** (4-AI 순차) 의무 |
| **minor** | 본문 prose only / typo / formatting / CHANGELOG entry 추가 | **Tier 3 skip** (Claude 단독) |

**Semantic prose evasion warning** (DS-HIGH-3 carry-forward): 본문 prose 가 implicit trigger pattern 추가 시 minor 분류 위험 — reviewer 수동 격상 (Tier 2+) 권장.

**Composition reference (frontmatter metadata)**: CLAUDE.md anchor 회피 (CW-MED-3) — Composition 규칙 reference 는 SKILL.md frontmatter 또는 별도 metadata 박제. CLAUDE.md 직접 anchor 사용 금지.

### REJECT 4건 (삭제됨)

DA chain 결과 본 변경에서 제외된 항목:

| 안 | REJECT 이유 | 별건 carry-forward |
|----|-----------|-------------------|
| **B Phase 1.5 load log** | r2 ChatGPT — hook side effect catastrophic risk (skill-auto-loader.sh 변경) | `--analyze-recent-jsonl` subcommand 별건 (read-only post-hoc) |
| **C read-only redefine** | r2 ChatGPT — semantic drift, 기존 사용자 mental model 침해 | 본 원칙 유지 (트리거 immutable 의미) |
| **D Tool path validation** | r2 ChatGPT — scope creep (god-object risk) | `~/.claude/scripts/validate-skill-tools.sh` 별도 도구 |
| **Layer 4 skill-creator hard-block** | **r4 DeepSeek CRIT-1·2 — frontmatter flag self-referential guard violation** ("guard inside the guarded system") | External integrity store (별건 CSR — signed manifest 또는 OS permission 보호) |

**보호 mechanism (CSR #823 답습 procedural enforcement)**:
- Layer 1: 사용자 명시 검토 (Tier S, CSR #716 옵션 D) — 본 CSR #825 진행 시 적용
- Layer 2: DA chain Tier 1 통과 (현재 적용 완료)
- Layer 3: 본 변경 후 첫 `--session-review` self-application 사용자 검토 — 변경 후 의무

**삭제 (DA chain 결과)**: self-reference guard frontmatter flag · 4-layer hard enforcement · skill-creator hard-block · `skill_name == "skill-advisor"` 하드코드.

### 회귀 fixture (`tests/`)

- `fixture-A-detection-3-status.json` — 4 status 검증
- `fixture-E-unified-view.json` — ordering + top-10 cap
- `fixture-F-tier-classification.json` — major/minor 명시 기준

자동 검증: `bash tests/g-integrated-test.sh` (13/13 PASS Green)

## 변경 이력 (CHANGELOG)

| 일자 | 변경 |
|------|------|
| **2026-05-24** | **CSR #825 G3' 축소 — DA chain Tier 1 Conditional Y (옵션 B 채택)**. detection 4 status (executed/triggered/artifact_confirmed/miss) + schema_version: 2 + legacy_detected 60일 deprecation (drop 2026-07-23). unified_skill_view 신규 (ordering + top-10 cap). thresholds.json 외부화 (signal_thresholds + conservative mode). major/minor Tier 분리 명시 기준. **REJECT 4건**: B Phase 1.5 load log (hook side effect) / C read-only redefine (semantic drift) / D tool path validation (scope creep) / **Layer 4 skill-creator hard-block (DeepSeek r4 self-referential guard violation)**. **삭제**: self-reference guard frontmatter flag · 4-layer hard enforcement. 보호 mechanism = CSR #823 답습 procedural (사용자 검토 + DA chain + first self-application 검토). 신규 도구: `tests/g-integrated-test.sh` (13/13 PASS Green). 별건 carry-forward 6건 (External integrity store / DS-HIGH-1·2·3 / `--analyze-recent-jsonl` / `validate-skill-tools.sh`). claude_learn 3 글 박제 (self-referential guard violation / Monotonic MODIFY meta-pattern / Procedural vs Hard enforcement). DA session: `/tmp/da-chain-csr825-1779578551/` |
