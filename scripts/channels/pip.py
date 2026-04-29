"""pip 패키지 기반 스킬 업데이트 체크 채널 (v1.0: check only)."""
import json
import subprocess
from pathlib import Path
from typing import Optional


def _run(cmd: list) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -2, "", str(e)


def check(skill_name: str, entry: dict, local_path: Path) -> dict:
    """pip list --outdated로 패키지 업데이트 여부 확인."""
    meta = entry.get("type_specific_metadata", {})
    packages = meta.get("pip_packages", [])

    if not packages:
        return {"skill": skill_name, "status": "config-error",
                "error": "pip_packages 미설정"}

    _, stdout, _ = _run(["pip", "list", "--outdated", "--format=json"])
    outdated_pkgs = {}
    try:
        outdated_list = json.loads(stdout) if stdout.strip() else []
        pkg_names_lower = {p.split(">=")[0].split("==")[0].lower() for p in packages}
        for item in outdated_list:
            if item.get("name", "").lower() in pkg_names_lower:
                outdated_pkgs[item["name"]] = {
                    "current": item.get("version"),
                    "latest": item.get("latest_version"),
                }
    except (json.JSONDecodeError, TypeError):
        pass

    status = "update-available" if outdated_pkgs else "up-to-date"

    python_path = meta.get("python_path") or "python3"
    install_context = meta.get("install_context", "system")
    pkg_names = [p.split(">=")[0].split("==")[0] for p in packages]
    install_cmd = f"pip install --upgrade {' '.join(pkg_names)}"

    return {
        "skill": skill_name,
        "status": status,
        "upstream_type": "pip",
        "pip_packages": packages,
        "outdated": outdated_pkgs,
        "python_path": python_path,
        "install_context": install_context,
        "apply_command": install_cmd,
        "applied": False,
        "error": None,
    }


def apply(skill_name: str, entry: dict, local_path: Path, **kwargs) -> dict:
    """v1.0: pip --apply는 명령어 출력만 수행. 직접 pip install 실행 금지."""
    result = check(skill_name, entry, local_path)
    meta = entry.get("type_specific_metadata", {})
    packages = meta.get("pip_packages", [])
    pkg_names = [p.split(">=")[0].split("==")[0] for p in packages]

    return {
        "skill": skill_name,
        "applied": False,
        "advisory": True,
        "message": "pip 채널은 v1.0에서 명령어 출력만 지원합니다 (직접 실행 금지)",
        "run_command": f"pip install --upgrade {' '.join(pkg_names)}",
        "warning": "가상환경 활성화 여부를 확인 후 실행하세요",
        "error": None,
    }
