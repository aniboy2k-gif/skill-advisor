"""npm 패키지 기반 스킬 업데이트 체크 채널 (v1.0: check only)."""
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

TRIGGER_PATTERN = re.compile(r"\n<!--trigger_conditions.*?-->\n", re.DOTALL)


def _run(cmd: list, cwd: Optional[Path] = None) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -2, "", str(e)


def check(skill_name: str, entry: dict, local_path: Path) -> dict:
    """npm outdated + npm audit 결과 반환 (check only)."""
    meta = entry.get("type_specific_metadata", {})
    pkg = meta.get("npm_package")
    install_dir = meta.get("install_dir")

    if not pkg or not install_dir:
        return {"skill": skill_name, "status": "config-error",
                "error": "npm_package 또는 install_dir 미설정"}

    install_path = Path(install_dir).expanduser()
    if not install_path.exists():
        install_path = Path.home() / install_dir
    if not install_path.exists():
        return {"skill": skill_name, "status": "local-missing",
                "error": f"설치 디렉토리 없음: {install_dir}"}

    # npm outdated
    _, stdout, _ = _run(["npm", "outdated", "--json", pkg], cwd=install_path)
    outdated = {}
    try:
        outdated = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        pass

    pkg_info = outdated.get(pkg, {})
    current = pkg_info.get("current") or meta.get("npm_version", "unknown")
    wanted = pkg_info.get("wanted", current)
    latest = pkg_info.get("latest", current)
    update_available = bool(pkg_info)

    # npm audit
    _, audit_stdout, _ = _run(["npm", "audit", "--json"], cwd=install_path)
    audit_vulns = 0
    try:
        audit_data = json.loads(audit_stdout) if audit_stdout.strip() else {}
        audit_vulns = audit_data.get("metadata", {}).get("vulnerabilities", {})
        if isinstance(audit_vulns, dict):
            audit_vulns = sum(audit_vulns.values())
        else:
            audit_vulns = 0
    except (json.JSONDecodeError, TypeError):
        audit_vulns = 0

    # trigger_conditions 경고 체크
    has_trigger_in_node_modules = False
    nm_skill_mds = list(install_path.glob("node_modules/**/SKILL.md"))
    for md in nm_skill_mds:
        if TRIGGER_PATTERN.search(md.read_text(errors="ignore")):
            has_trigger_in_node_modules = True
            break

    status = "update-available" if update_available else "up-to-date"
    if audit_vulns > 0:
        status = "update-available-with-vulnerability"

    return {
        "skill": skill_name,
        "status": status,
        "upstream_type": "npm",
        "npm_package": pkg,
        "current_version": current,
        "wanted_version": wanted,
        "latest_version": latest,
        "audit_vulnerabilities": audit_vulns,
        "trigger_in_node_modules": has_trigger_in_node_modules,
        "apply_blocked": has_trigger_in_node_modules,
        "apply_command": f"cd {install_dir} && npm install {pkg}@latest",
        "applied": False,
        "error": None,
    }


def apply(skill_name: str, entry: dict, local_path: Path, **kwargs) -> dict:
    """v1.0: npm --apply는 명령어 출력만 수행. 직접 실행 안 함."""
    result = check(skill_name, entry, local_path)
    meta = entry.get("type_specific_metadata", {})
    install_dir = meta.get("install_dir", "")

    if result.get("trigger_in_node_modules"):
        return {
            "skill": skill_name,
            "applied": False,
            "blocked": True,
            "reason": "node_modules 내 SKILL.md에 trigger_conditions 존재 — 업데이트 후 유실됨",
            "action_required": "skill-creator로 trigger_conditions를 기본 SKILL.md로 이전 후 재실행하세요",
            "error": None,
        }

    return {
        "skill": skill_name,
        "applied": False,
        "advisory": True,
        "message": f"npm 채널은 v1.0에서 명령어 출력만 지원합니다",
        "run_command": f"cd {install_dir} && npm install {meta.get('npm_package', '')}@latest",
        "after_update": "zsh ~/.claude/hooks/skill-index.sh  # 인덱스 재생성 필요",
        "error": None,
    }
