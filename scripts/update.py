#!/usr/bin/env python3
"""skill-advisor --update 모드 오케스트레이터 (Layer 1).

사용법:
  python3 update.py [<skill>] [--apply] [--yes] [--dry-run] [--json]
                    [--keep-backup] [--refresh-sources]
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

# sys.path 부트스트랩
_SCRIPTS_DIR = str(Path(__file__).parent.resolve())
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from channels import github_raw, npm, pip as pip_channel

SOURCES_PATH = Path.home() / ".claude" / "skill-sources.json"
SKILL_INDEX_PATH = Path("/tmp/skill-index.json")

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


def save_sources(data: dict) -> None:
    tmp = SOURCES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SOURCES_PATH)


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
    """실행 계획 표 출력."""
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

        result = handler.check(skill_name, entry, local_path)
        result.setdefault("upstream_type", utype)
        results.append(result)

    return results


def run_apply(results: list, sources: dict, yes: bool, keep_backup: bool) -> list:
    apply_results = []
    needs_apply = [r for r in results
                   if r.get("status") in ("update-available", "update-available-with-vulnerability")
                   and not r.get("blocked")]

    if not needs_apply:
        print("✅ 적용할 업데이트가 없습니다.")
        return results

    print_plan_table(needs_apply)

    if not yes:
        if not prompt_confirm("위 계획을 적용하시겠습니까?"):
            print("⏹ 취소됨.")
            return results

    skills_data = sources.get("skills", {})

    for r in needs_apply:
        skill_name = r["skill"]
        entry = skills_data.get(skill_name, {})
        utype = r.get("upstream_type", entry.get("upstream_type", "unknown"))
        handler = CHANNEL_HANDLERS.get(utype)

        local_path = resolve_local_path(skill_name, entry)
        if local_path is None:
            apply_results.append({**r, "applied": False, "error": "로컬 경로 없음"})
            continue

        result = handler.apply(skill_name, entry, local_path, keep_backup=keep_backup)
        apply_results.append(result)

        # skill-sources.json 상태 갱신
        if result.get("applied"):
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            skills_data[skill_name]["last_updated"] = now
            skills_data[skill_name]["last_checked"] = now
            skills_data[skill_name]["status"] = "up-to-date"

    save_sources(sources)
    return apply_results


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
        elif "update-available" in status:
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
    if any(r.get("status") in ("update-available", "update-available-with-vulnerability")
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
    args = parser.parse_args()

    if args.refresh_sources:
        print("ℹ --refresh-sources: skill-sources.json은 초기 생성 스크립트로 재생성하세요.")
        print(f"  현재 경로: {SOURCES_PATH}")
        return 0

    sources = load_sources()
    results = run_check(args.skill, sources)

    apply_results = []
    if args.apply and not args.dry_run:
        apply_results = run_apply(results, sources, yes=args.yes,
                                  keep_backup=args.keep_backup)
        all_results = results + [r for r in apply_results if r.get("applied")]
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
            }.get(r.get("status", ""), "—")

            name = r.get("skill", "?")
            status = r.get("status", "?")
            applied = " → 적용됨" if r.get("applied") else ""
            advisory_cmd = f"\n    💡 실행: {r['run_command']}" if r.get("advisory") and r.get("run_command") else ""
            blocked_msg = f"\n    ⛔ {r['reason']}" if r.get("blocked") else ""
            print(f"  {icon} {name:<35} [{status}]{applied}{advisory_cmd}{blocked_msg}")

        if summary["update_available"] > 0 and not args.apply:
            print(f"\n💡 업데이트 적용: /skill-advisor --update --apply")
            if summary["advisory"] > 0:
                print(f"   (npm/pip는 출력된 명령어를 직접 실행하세요)")

    return determine_exit_code(all_results)


if __name__ == "__main__":
    sys.exit(main())
