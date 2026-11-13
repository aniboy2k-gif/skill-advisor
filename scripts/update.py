#!/usr/bin/env python3
"""skill-advisor --update 모드 오케스트레이터 (Layer 1).

사용법:
  python3 update.py [<skill>] [--apply] [--yes] [--dry-run] [--json]
                    [--keep-backup] [--refresh-sources]
                    [--worktree <linked worktree>] [--force-overwrite] [--allow-missing-refs] [--allow-main]
  python3 update.py --set-baseline <skill> [--hash sha256:<64hex>] [--ref <commit>] [--note "<text>"] [--yes]
"""
import argparse
import builtins
import datetime
import fcntl
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# sys.path 부트스트랩
_SCRIPTS_DIR = str(Path(__file__).parent.resolve())
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from channels import github_raw, npm, pip as pip_channel

SOURCES_PATH = Path.home() / ".claude" / "skill-sources.json"
LOCK_PATH = Path.home() / ".claude" / "skill-sources.json.lock"
DELETE = object()  # save_skill_keys: 키 삭제 표지
# CSR #1260: da-tools primary SSOT. constants.SKILL_INDEX가 primary(da-tools, 영속) →
# /tmp legacy fallback 순으로 해석한다 (DRY — constants.py 단일 정의 재사용).
from constants import SKILL_INDEX as SKILL_INDEX_PATH
SKILL_INDEX_SH = Path.home() / ".claude/hooks/skill-index.sh"


def ensure_skill_index() -> bool:
    """skill-index.json이 없으면 skill-index.sh를 자동 실행해 재생성한다.

    CSR #1260: SKILL_INDEX_PATH는 constants.SKILL_INDEX가 da-tools primary(영속)
    → /tmp legacy fallback 순으로 해석한 경로다. primary는 영속이므로 정상 머신에서는
    이미 존재해 이 재생성 분기는 사실상 비활성이며, primary 부재(fresh machine) 시에만
    fallback으로 발동한다.

    Returns:
        True  = 파일이 있음 (기존 또는 재생성 성공)
        False = 재생성 실패 (skill-index.sh 없거나 실행 오류)
    """
    if SKILL_INDEX_PATH.exists():
        return True

    if not SKILL_INDEX_SH.exists():
        print(f"⚠ skill-index.sh 없음: {SKILL_INDEX_SH}", file=sys.stderr)
        return False

    import subprocess
    try:
        result = subprocess.run(
            ["zsh", str(SKILL_INDEX_SH)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and SKILL_INDEX_PATH.exists():
            return True
        print("⚠ skill-index.sh 실행 실패 — local_path 조회가 제한됩니다.", file=sys.stderr)
        return False
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"⚠ skill-index.sh 실행 오류: {e} — local_path 조회가 제한됩니다.", file=sys.stderr)
        return False

CHANNEL_HANDLERS = {
    "anthropic_official": github_raw,
    "microsoft":          github_raw,
    "community":          github_raw,
    "github_raw":         github_raw,  # check()가 반환하는 upstream_type
    "npm":                npm,
    "pip":                pip_channel,
    "local_custom":       None,
}


# ─── 유틸 ────────────────────────────────────────────────────────────────────

def load_sources() -> dict:
    if not SOURCES_PATH.exists():
        print(f"⚠ skill-sources.json 없음: {SOURCES_PATH}", file=sys.stderr)
        return {"schema_version": "1.0", "skills": {}}
    try:
        return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠ skill-sources.json 파싱 오류: {e}", file=sys.stderr)
        return {"schema_version": "1.0", "skills": {}}


def save_skill_keys(updates: dict) -> None:
    """{skill: {key: value | DELETE}} 만 최신 파일에 병합해 원자 교체 (r3 L1 · r4 M2: fcntl 잠금 안에서)."""
    with open(LOCK_PATH, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(SOURCES_PATH.read_text(encoding="utf-8")) if SOURCES_PATH.exists() \
                else {"schema_version": "1.0", "skills": {}}
            skills = data.setdefault("skills", {})
            for name, keys in updates.items():
                ent = skills.setdefault(name, {})
                for k, v in keys.items():
                    if v is DELETE:
                        ent.pop(k, None)
                    else:
                        ent[k] = v
            tmp = SOURCES_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(SOURCES_PATH)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def op_root() -> Path:
    """운영 트리 = dirname(realpath(~/.claude/skills))."""
    return (Path.home() / ".claude" / "skills").resolve().parent


def _git(path: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def validate_worktree(path: Path, op: Path) -> tuple:
    """--worktree 는 운영 저장소의 연결 작업 트리(최상위)여야 한다."""
    p = Path(path).resolve()
    if not p.is_dir():
        return False, f"--worktree {path}: not a directory"
    top = _git(p, "rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() != p:
        return False, f"--worktree {path}: not the top of a git worktree"
    if p == Path(op).resolve():
        return False, f"--worktree {path}: is the operational tree itself"
    common = _git(p, "rev-parse", "--path-format=absolute", "--git-common-dir")
    op_common = _git(Path(op), "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common or Path(common).resolve() != Path(op_common or "/nonexistent").resolve():
        return False, f"--worktree {path}: not a linked worktree of the operational repository"
    return True, ""


def resolve_local_path(skill_name: str, entry: dict) -> Optional[Path]:
    """skill_sources entry 또는 skill-index.json에서 로컬 SKILL.md 경로 조회."""
    meta = entry.get("type_specific_metadata", {})
    lp = entry.get("local_path") or meta.get("local_path")
    if lp:
        p = Path(lp).expanduser()
        return p if p.exists() else None

    if SKILL_INDEX_PATH.exists():
        try:
            idx = json.loads(SKILL_INDEX_PATH.read_text())
            skills = idx.get("skills", [])
            for s in skills:
                if s.get("skill") == skill_name:
                    sp = s.get("skill_path", "")
                    if sp:
                        p = Path(sp)
                        return p if p.exists() else None
        except (json.JSONDecodeError, OSError):
            pass
    return None


def print_plan_table(results: list) -> None:
    """실행 계획 표 출력 (stderr — --json 의 stdout 을 오염시키지 않는다)."""
    print = _stderr_print  # noqa: A001
    print("\n┌─ 실행 계획 ──────────────────────────────────────────────────────")
    header = f"{'스킬':<30} {'채널':<20} {'현재 상태':<22} {'부작용 등급'}"
    print(f"│ {header}")
    print("├" + "─" * 70)
    for r in results:
        name    = r.get("skill", "?")[:28]
        utype   = r.get("upstream_type", r.get("status", "?"))[:18]
        status  = r.get("status", "?")[:20]
        if r.get("blocked"):
            effect = "⛔ 차단됨"
        elif r.get("advisory"):
            effect = "📋 명령어 출력만"
        elif utype in ("github_raw",):
            effect = "📝 파일 변경"
        else:
            effect = "—"
        print(f"│ {name:<30} {utype:<20} {status:<22} {effect}")
    print("└" + "─" * 70 + "\n")


def _stderr_print(*a, **k):
    builtins.print(*a, **k, file=sys.stderr)


def prompt_confirm(message: str) -> bool:
    try:
        ans = input(f"{message} [y/N] ").strip().lower()
        return ans == "y"
    except (EOFError, KeyboardInterrupt):
        return False


# ─── 메인 로직 ────────────────────────────────────────────────────────────────

def run_check(skill_filter: Optional[str], sources: dict) -> list:
    results = []
    skills_data = sources.get("skills", {})

    targets = (
        {skill_filter: skills_data[skill_filter]}
        if skill_filter and skill_filter in skills_data
        else skills_data
    )

    for skill_name, entry in sorted(targets.items()):
        utype = entry.get("upstream_type", "unknown")
        handler = CHANNEL_HANDLERS.get(utype)

        if handler is None:
            results.append({
                "skill": skill_name,
                "status": "local-custom",
                "upstream_type": utype,
                "message": "로컬 커스텀 스킬 — 자동 체크 미지원",
                "applied": False,
                "error": None,
            })
            continue

        local_path = resolve_local_path(skill_name, entry)
        if local_path is None:
            results.append({
                "skill": skill_name,
                "status": "local-missing",
                "upstream_type": utype,
                "error": "로컬 SKILL.md 경로 조회 실패",
                "applied": False,
            })
            continue

        if handler is github_raw:
            result = handler.check(skill_name, entry, local_path, op_root=op_root())
        else:
            result = handler.check(skill_name, entry, local_path)
        result.setdefault("upstream_type", utype)
        results.append(result)

    return results


def write_target(local_path: Path, worktree: Optional[Path]) -> Optional[Path]:
    """기본 = 운영 파일(apply (d) 가 거부) · --worktree = 작업 트리 안 같은 상대 경로."""
    if worktree is None:
        return local_path
    try:
        rel = local_path.resolve().relative_to(op_root())
    except ValueError:
        return None
    return Path(worktree).resolve() / rel


def run_apply(results: list, sources: dict, yes: bool, keep_backup: bool,
              worktree: Optional[Path] = None, force_overwrite: bool = False,
              allow_missing_refs: bool = False, allow_main: bool = False) -> list:
    """적용 결과 행이 같은 스킬의 check 행을 대체한 목록을 돌려준다 (C-1 #9)."""
    needs_apply = [r for r in results
                   if r.get("status") in ("update-available", "update-available-with-vulnerability")
                   and not r.get("blocked")]

    if not needs_apply:
        print("✅ 적용할 업데이트가 없습니다.", file=sys.stderr)
        return results

    print_plan_table(needs_apply)

    if not yes:
        if not prompt_confirm("위 계획을 적용하시겠습니까?"):
            print("⏹ 취소됨.")
            return results

    skills_data = sources.get("skills", {})
    merged = {r.get("skill"): r for r in results}
    updates = {}

    for r in needs_apply:
        skill_name = r["skill"]
        entry = skills_data.get(skill_name, {})
        utype = r.get("upstream_type", entry.get("upstream_type", "unknown"))
        handler = CHANNEL_HANDLERS.get(utype)

        local_path = resolve_local_path(skill_name, entry)
        if local_path is None:
            merged[skill_name] = {**r, "applied": False, "error": "로컬 경로 없음"}
            continue

        if handler is github_raw:
            target = write_target(local_path, worktree)
            if target is None or not target.exists():
                merged[skill_name] = {**r, "applied": False, "blocked": True, "exit_hint": 2,
                                      "status": "local-missing" if target else r["status"],
                                      "reason": f"local-missing in the write target: {target or local_path}"}
                continue
            result = handler.apply(skill_name, entry, target, r, op_root=op_root(),
                                   keep_backup=keep_backup, force_overwrite=force_overwrite,
                                   allow_missing_refs=allow_missing_refs, allow_main=allow_main)
        else:
            result = handler.apply(skill_name, entry, local_path, keep_backup=keep_backup)

        if result.get("applied"):
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            keys = {"last_updated": now, "last_checked": now, "status": "up-to-date"}
            nb = result.get("new_baseline")
            if nb is not None:
                if worktree is not None:
                    if r.get("baseline_source") == "pending":   # 병합·수렴된 대기 판을 먼저 승격
                        keys["baseline"] = entry["pending_baseline"]
                    keys["pending_baseline"] = nb
                else:
                    keys["baseline"] = nb
                    keys["pending_baseline"] = DELETE
            updates[skill_name] = keys
            merged[skill_name] = {**r, **result, "status": "up-to-date", "applied": True}
        else:
            merged[skill_name] = {**r, **result}

    if updates:
        save_skill_keys(updates)
    return list(merged.values())


def set_baseline(skill: str, sources: dict, want_hash: Optional[str], ref: Optional[str],
                 note: Optional[str], yes: bool) -> int:
    """기준 판 수동 기록 — --hash 가 받은 바이트의 정규화 해시와 같을 때만 쓴다."""
    entry = sources.get("skills", {}).get(skill)
    if not entry or not entry.get("upstream_url"):
        print(f"⛔ {skill}: skill-sources.json 에 upstream_url 이 있는 항목이 없습니다.")
        return 2
    url = entry["upstream_url"]
    if ref:
        purl = github_raw.pinned_url(url, ref)
        if purl is None:
            print(f"⛔ {skill}: upstream_url 이 raw 주소가 아니라 --ref 를 쓸 수 없습니다.")
            return 2
        text, unresolved = github_raw.fetch_upstream(purl), None
    else:
        pin = github_raw.resolve_pinned(url)
        text, ref, unresolved = pin["text"], pin["ref"], pin["unresolved"]
    if text is None:
        print(f"⛔ {skill}: upstream fetch failed")
        return 2
    h = github_raw.norm_hash(text)
    ps = github_raw.patch_status(skill, op_root())
    print(f"{skill}: normalized upstream hash = {h}")
    print(f"  ref = {ref or 'null (' + str(unresolved) + ')'}")
    old = entry.get("baseline") or {}
    if old.get("ref") and old.get("sha256"):
        btext = github_raw.fetch_upstream(github_raw.pinned_url(url, old["ref"]) or "")
        if btext is not None and github_raw.norm_hash(btext) == old["sha256"]:
            c = github_raw.changed_lines(btext, text)
            print(f"  baseline -> this: +{c['added']} -{c['removed']} lines")
        else:
            print("  baseline text unverifiable; line counts unavailable")
    if ps.get("patched") is not False:
        print("  note: resync-skill.sh does not read or update this baseline "
              f"(patch status: {ps.get('patch_sets') or ps.get('patch_info')})")
    if not want_hash:
        print(f"  nothing written — review the bytes, then rerun with --hash {h}")
        return 0
    if want_hash != h:
        print(f"⛔ refused: --hash {want_hash} != fetched {h}; nothing written")
        return 2
    local_path = resolve_local_path(skill, entry)
    try:
        local_norm = github_raw.norm_hash(github_raw.read_local_strict(local_path)) if local_path else None
    except (UnicodeDecodeError, OSError):
        local_norm = None
    if local_norm is None:
        print(f"⛔ refused: local SKILL.md of {skill} missing or not valid UTF-8; nothing written")
        return 2
    if not yes and not prompt_confirm(f"{skill} 의 기준 판을 {h[:19]}… 로 기록할까요?"):
        print("⏹ 취소됨.")
        return 0
    save_skill_keys({skill: {
        "baseline": {
            "sha256": h, "ref": ref,
            "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "note": note or ("set-baseline" if ref else f"set-baseline; ref unresolved: {unresolved}"),
            "local_sha256": local_norm,
        },
        "pending_baseline": DELETE,
    }})
    print(f"✅ {skill}: baseline recorded")
    return 0


def build_summary(results: list) -> dict:
    summary = {
        "total": len(results),
        "up_to_date": 0,
        "update_available": 0,
        "local_custom": 0,
        "fetch_error": 0,
        "blocked": 0,
        "applied": 0,
        "advisory": 0,
    }
    for r in results:
        status = r.get("status", "")
        if "up-to-date" in status:
            summary["up_to_date"] += 1
        elif "update-available" in status or status == "baseline-unconfirmed":
            summary["update_available"] += 1
        elif status == "local-custom":
            summary["local_custom"] += 1
        elif status in ("fetch-error", "local-missing", "config-error", "no-url"):
            summary["fetch_error"] += 1
        if r.get("applied"):
            summary["applied"] += 1
        if r.get("advisory"):
            summary["advisory"] += 1
        if r.get("blocked"):
            summary["blocked"] += 1
    return summary


def determine_exit_code(results: list) -> int:
    """0=성공, 1=업데이트 가능, 2=실행 실패, 3=apply 실패(rollback 완료), 4=apply 실패(rollback 실패)"""
    codes = [r.get("exit_hint", 0) for r in results if r.get("exit_hint")]
    if 4 in codes:
        return 4
    if 3 in codes:
        return 3
    if 2 in codes:
        return 2
    if any(r.get("status") in ("update-available", "update-available-with-vulnerability",
                               "baseline-unconfirmed")
           for r in results):
        return 1
    return 0


# ─── CLI 진입점 ────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="skill-advisor --update 오케스트레이터")
    parser.add_argument("skill", nargs="?", default=None, help="특정 스킬 이름")
    parser.add_argument("--apply", action="store_true", help="업데이트 적용")
    parser.add_argument("--yes", action="store_true", help="자동 진행 (확인 생략)")
    parser.add_argument("--dry-run", action="store_true",
                        help="check만 수행 (기본 동작과 동일)")
    parser.add_argument("--json", dest="json_out", action="store_true",
                        help="JSON 출력")
    parser.add_argument("--keep-backup", action="store_true",
                        help="apply 후 .bak 파일 보존")
    parser.add_argument("--refresh-sources", action="store_true",
                        help="skill-sources.json 재생성 (미구현 — skill-index.sh 실행 후 수동 편집)")
    parser.add_argument("--worktree", type=Path, default=None,
                        help="apply 쓰기 대상 = 운영 저장소의 연결 작업 트리 (운영 트리 쓰기는 거부)")
    parser.add_argument("--force-overwrite", action="store_true",
                        help="로컬 수정 소실 검사 (b)(f) 만 푼다")
    parser.add_argument("--allow-missing-refs", action="store_true",
                        help="새로 끊어지는 참조 검사 (c) 만 푼다")
    parser.add_argument("--allow-main", action="store_true",
                        help="운영 트리 쓰기 거부 (d) 만 푼다 (.bak 보존)")
    parser.add_argument("--set-baseline", metavar="SKILL", default=None,
                        help="기준 판 수동 기록 (--hash 없으면 해시만 출력)")
    parser.add_argument("--hash", dest="want_hash", default=None, help="sha256:<64hex> 정규화 해시")
    parser.add_argument("--ref", default=None, help="커밋 sha (--set-baseline)")
    parser.add_argument("--note", default=None, help="기준 판 메모 (--set-baseline)")
    args = parser.parse_args()

    if args.refresh_sources:
        print("ℹ --refresh-sources: skill-sources.json은 초기 생성 스크립트로 재생성하세요.")
        print(f"  현재 경로: {SOURCES_PATH}")
        return 0

    if args.set_baseline:
        ensure_skill_index()
        return set_baseline(args.set_baseline, load_sources(), args.want_hash, args.ref,
                            args.note, args.yes)

    if args.worktree is not None:
        ok, why = validate_worktree(args.worktree, op_root())
        if not ok:
            print(f"⛔ {why} — nothing fetched, nothing written")
            return 2

    ensure_skill_index()
    sources = load_sources()
    results = run_check(args.skill, sources)

    if args.apply and not args.dry_run:
        all_results = run_apply(results, sources, yes=args.yes, keep_backup=args.keep_backup,
                                worktree=args.worktree, force_overwrite=args.force_overwrite,
                                allow_missing_refs=args.allow_missing_refs, allow_main=args.allow_main)
    else:
        all_results = results

    summary = build_summary(all_results)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    output = {
        "checked_at": now,
        "mode": "apply" if (args.apply and not args.dry_run) else "check",
        "results": all_results,
        "summary": summary,
    }

    if args.json_out:
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        # 사람 읽기용 출력
        print(f"\n📦 skill-advisor --update 결과  ({now[:10]})")
        print(f"   총 {summary['total']}개 | ✅ 최신 {summary['up_to_date']} "
              f"| ⬆ 업데이트 가능 {summary['update_available']} "
              f"| 🔒 로컬 커스텀 {summary['local_custom']} "
              f"| ❌ 오류 {summary['fetch_error']}\n")

        for r in all_results:
            icon = {
                "up-to-date": "✅",
                "update-available": "⬆",
                "update-available-with-vulnerability": "🔴",
                "local-custom": "🔒",
                "fetch-error": "❌",
                "local-missing": "❓",
                "baseline-unconfirmed": "⚠",
            }.get(r.get("status", ""), "—")

            name = r.get("skill", "?")
            status = r.get("status", "?")
            if r.get("local_state") == "local-modified" and status == "up-to-date":
                status += " (local-modified)"
            applied = " → 적용됨" if r.get("applied") else ""
            extra = ""
            if r.get("baseline_state") == "upstream-changed":
                c = r.get("changed_lines")
                extra = (f"\n    기준 판 대비 +{c['added']} -{c['removed']} 줄" if c
                         else "\n    baseline text unverifiable; line counts unavailable"
                         if r.get("baseline_content") == "unverifiable" else "")
            elif r.get("diff_basis") and "update-available" in status:
                extra = f"\n    {r['diff_basis']}"
            if r.get("message") and r.get("status") == "baseline-unconfirmed":
                extra += f"\n    {r['message']}"
            if r.get("warning"):
                extra += f"\n    ⚠ {r['warning']}"
            advisory_cmd = f"\n    💡 실행: {r['run_command']}" if r.get("advisory") and r.get("run_command") else ""
            blocked_msg = f"\n    ⛔ {r['reason']}" if r.get("blocked") else ""
            if r.get("backup") and r.get("applied"):
                blocked_msg += f"\n    .bak: {r['backup']}"
            print(f"  {icon} {name:<35} [{status}]{applied}{extra}{advisory_cmd}{blocked_msg}")

        if summary["update_available"] > 0 and not args.apply:
            print(f"\n💡 업데이트 적용: /skill-advisor --update --apply")
            if summary["advisory"] > 0:
                print(f"   (npm/pip는 출력된 명령어를 직접 실행하세요)")

    return determine_exit_code(all_results)


if __name__ == "__main__":
    sys.exit(main())
