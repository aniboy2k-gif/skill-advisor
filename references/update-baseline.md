# --update 기준 판(baseline) 비교와 --apply 거부 규칙 (CSR #2415)

## Contents
1. 기준 판 — 무엇을 저장하나 · 2. 정규화와 두 종류의 해시 · 3. check 판정 · 4. 작업 트리 적용과 대기 기준 판 · 5. 패치 세트 스킬 · 6. --apply 거부 규칙 · 7. 실행 순서 · 8. 한계

## 1. 기준 판 — 무엇을 저장하나

`~/.claude/skill-sources.json` 스킬 항목의 `baseline` = `{sha256, ref, recorded_at, note, local_sha256}`.

- `sha256` = 정규화한 상류 원문의 해시 · `ref` = 그 바이트의 커밋(모르면 null) · `local_sha256` = 기록 순간 로컬 SKILL.md 의 정규화 해시.
- 뜻 = **로컬과 대조해 검토한 마지막 상류 판**. 3-way merge 기준이 아니다 — 병합은 claude-forge `vendor-patches/resync-skill.sh`.
- 기준 판 = 쓴 상류 원문이지 로컬 병합 결과가 아니다.

## 2. 정규화와 두 종류의 해시

- 정규화 = `re.sub(r"\n+(<!--trigger_conditions.*?-->)\n", "\n", text, flags=re.DOTALL).strip()`, 엄격한 UTF-8 — `resync-skill.sh` 와 같은 함수 본문이고 코드는 `scripts/channels/github_raw.py` `normalize()` 하나.
- `upstream_hash` = 받은 원문 그대로의 해시 — `resync-skill.sh --expect-upstream-hash` 와 memory-health 루틴이 쓰는 값.
- `upstream_norm_hash` = 정규화 해시 — 기준 판·apply 결박·`--set-baseline --hash` 가 쓰는 값. 두 값을 섞지 않는다.

## 3. check 판정 (읽기 전용)

| 조건 | status | 부가 필드 |
|---|---|---|
| 기준 판 있음, 로컬 ≠ `baseline.local_sha256` | `baseline-unconfirmed` (종료 1) | `local_state: changed-since-baseline` — 복원된 파일·병합 안 된 PR·새 로컬 수정. 검토 뒤 `--set-baseline` |
| 상류 = 기준 판 | `up-to-date` | `local_state: same` 또는 `local-modified`(검토된 로컬 수정 — 업데이트 아님) |
| 상류 ≠ 기준 판 | `update-available` | `changed_lines` = 기준 판→상류 줄 수. 기준 판 원문을 `ref` 로 받아 해시가 맞을 때만 — 아니면 `baseline_content: unverifiable`, `changed_lines: null` |
| 기준 판 없음 | 예전 동작 (로컬 vs 상류) | `diff_basis: "local-vs-upstream (cannot tell which side changed)"` |

모든 행에 `patched`(세 값: true · false · null=확인 불가 — 없다고 단정하지 않는다)·`missing_refs_upstream`·`new_missing_refs`.
로컬이 UTF-8 이 아니면 `fetch-error`(같다고 보지 않는다).

## 4. 작업 트리 적용과 대기 기준 판

`--worktree` 적용은 `baseline` 이 아니라 `pending_baseline` 을 쓴다.

- 운영 파일이 `pending_baseline.local_sha256` 과 같아지면(PR 병합 + 운영 트리 `git pull --ff-only`) check 가 그것을 유효 기준 판으로 쓴다(`baseline_source: pending`). 다음 apply·`--set-baseline` 때 `baseline` 으로 승격된다.
- PR 을 버리면 운영 파일이 그대로라 옛 기준 판으로 판정되고, 같은 상류 판을 JSON 손질 없이 다시 적용할 수 있다.

## 5. 패치 세트 스킬

`vendor-patches/*-upstream-files.txt` 에 `skills/<skill>/SKILL.md` 가 있는 스킬은 apply (a) 가 늘 거부한다. 기준 판은 감지용이다.
`resync-skill.sh` 는 이 기준 판을 읽지도 고치지도 않는다 — resync 로 상류를 채택한 뒤 `update.py --set-baseline <skill> --hash <upstream_norm_hash>` 를 실행한다. 그 전까지 check 는 `upstream-changed` 를 계속 보인다.

## 6. --apply 거부 규칙

차단된 스킬은 통째로 건너뛰고(부분 적용 없음) 다른 스킬은 진행한다. 종료 코드 2. 각 옵션은 자기 검사만 푼다.

| 검사 | 거부 조건 | 푸는 옵션 |
|---|---|---|
| (a) | 패치 세트 등재, 또는 `patched: null` | 없음 — `resync-skill.sh` |
| 서브모듈 | 쓰기 대상이 git 서브모듈 안 | 없음 — 서브모듈 저장소 PR → 병합 → claude-forge 포인터 PR |
| (d) | 쓰기 대상의 저장소 최상위 = 운영 트리 `dirname(realpath ~/.claude/skills)` | `--allow-main`(.bak 보존) |
| (e) | ls-remote 커밋으로 고정해 다시 받은 상류(또는 ref 미해석 시 다시 받은 브랜치 바이트) ≠ check 의 `upstream_norm_hash` | 없음 — 다시 실행. 거부 문구의 커밋으로 `--set-baseline --ref` 가능 |
| (c) | 쓰기 대상 기준으로 새로 끊어지는 참조(마크다운 링크·역따옴표 경로 .md .py .sh .js .json .txt .yaml .yml) | `--allow-missing-refs` |
| (g) | 확인(y/N) 뒤 쓰기 직전에 다시 읽은 대상 ≠ check 의 `local_norm_hash` | 없음 — 다시 실행 |
| (b) | 기준 판이 있고 다시 읽은 로컬 ≠ 기준 판 (로컬 수정 소실) | `--force-overwrite`(.bak 보존) |
| (f) | 기준 판이 없고 로컬 ≠ 상류 | `--force-overwrite`(경고 줄) — 또는 검토 뒤 `--set-baseline` |

`--worktree <path>` 는 `<path>` 가 그 작업 트리의 최상위이고, 운영 트리 자신이 아니며, `--git-common-dir` 이 운영 트리와 같을 때(운영 저장소의 연결 작업 트리)만 받는다 — 아니면 아무것도 받기 전에 종료 2.

## 7. 실행 순서

```bash
# 일상 적용: 작업 트리 → apply → 커밋 + PR → 병합 → 운영 트리 git pull --ff-only
git -C "$OP" worktree add <wt> -b <branch> origin/main
python3 scripts/update.py <skill> --apply --worktree <wt> [--yes] [--keep-backup]
#   기준 판이 없는 스킬은 (f) 로 거부(종료 2) — 차이를 검토한 뒤 같은 명령에 --force-overwrite (경고 줄 · .bak 보존)

# 기준 판 기록: --hash 없이 먼저 돌려 해시·ref·줄 수를 보고(아무것도 쓰지 않음), 검토 뒤 같은 해시로
python3 scripts/update.py --set-baseline <skill> [--ref <commit>] [--note "<왜>"]
python3 scripts/update.py --set-baseline <skill> --hash sha256:<64hex> [--ref <commit>] [--note "<왜>"] [--yes]
```

## 8. 한계

- trigger_conditions 블록만 건드린 상류 변경은 보이지 않는다(정규화가 걷어 낸다 — `resync-skill.sh` 와 같은 한계).
- 브랜치 이름에 `/` 가 든 raw 주소는 ref 미해석(`ref: null`)으로 떨어지고 해시 결박은 유지된다(2026-11-13 실측 0건).
- `skill-sources.json` 은 git 밖이라 기준 판 자체는 버전 관리되지 않는다 — 파일과 어긋나면 `baseline-unconfirmed` 로 드러날 뿐 막지 않는다. 쓰기는 `skill-sources.json.lock` 의 `fcntl` 잠금 안에서 바뀐 스킬 키만 병합한다.
- raw 호스트가 낡은 브랜치 객체를 주면 (e) 가 캐시가 풀릴 때까지 거부한다(가용성만).
- 이력 대조로 「로컬이 예전 상류 판이었나」를 찾는 기능은 없다 — 기준 판이 앞으로 같은 답을 준다.
