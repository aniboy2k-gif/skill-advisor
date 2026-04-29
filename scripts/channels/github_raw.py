"""GitHub raw URL 기반 SKILL.md 콘텐츠 동기화 채널."""
import hashlib
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

TRIGGER_PATTERN = re.compile(r"\n(<!--trigger_conditions.*?-->)\n", re.DOTALL)
FETCH_TIMEOUT = 10


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_upstream(url: str) -> Optional[str]:
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        return None


def extract_trigger_conditions(text: str) -> Optional[str]:
    m = TRIGGER_PATTERN.search(text)
    return m.group(1) if m else None


def reinsert_trigger_conditions(upstream_text: str, trigger_block: str) -> str:
    """YAML frontmatter 직후(두 번째 --- 뒤)에 trigger_conditions 삽입."""
    try:
        first = upstream_text.index("---")
        second = upstream_text.index("---", first + 3) + 3
        return upstream_text[:second] + "\n\n" + trigger_block + upstream_text[second:]
    except ValueError:
        return upstream_text


def check(skill_name: str, entry: dict, local_path: Path) -> dict:
    """upstream vs local SHA256 비교. 결과 dict 반환."""
    url = entry.get("upstream_url")
    if not url:
        return {"skill": skill_name, "status": "no-url", "error": "upstream_url 없음"}

    if not local_path.exists():
        return {"skill": skill_name, "status": "local-missing", "error": str(local_path)}

    upstream = fetch_upstream(url)
    if upstream is None:
        return {"skill": skill_name, "status": "fetch-error",
                "upstream_url": url, "error": "HTTP fetch 실패"}

    local = local_path.read_text(errors="ignore")
    up_hash = sha256_text(upstream)
    lc_hash = sha256_text(local)
    up_lines = len(upstream.splitlines())
    lc_lines = len(local.splitlines())

    # trigger_conditions 제거 후 비교 (로컬 추가 블록 무시)
    lc_no_tc = TRIGGER_PATTERN.sub("\n", local)
    up_no_tc = TRIGGER_PATTERN.sub("\n", upstream)
    effective_same = lc_no_tc.strip() == up_no_tc.strip()

    status = "up-to-date" if effective_same else "update-available"
    diff_added = max(0, up_lines - lc_lines)
    diff_removed = max(0, lc_lines - up_lines)

    trigger_block = extract_trigger_conditions(local)
    local_overrides = ["trigger_conditions"] if trigger_block else []

    return {
        "skill": skill_name,
        "status": status,
        "upstream_type": "github_raw",
        "upstream_url": url,
        "upstream_hash": up_hash,
        "local_hash": lc_hash,
        "local_lines": lc_lines,
        "upstream_lines": up_lines,
        "diff_lines_added": diff_added,
        "diff_lines_removed": diff_removed,
        "local_overrides": local_overrides,
        "applied": False,
        "error": None,
    }


def apply(skill_name: str, entry: dict, local_path: Path,
          keep_backup: bool = False) -> dict:
    """upstream 내용으로 SKILL.md 교체 (원자성 보장)."""
    url = entry.get("upstream_url")
    if not url:
        return {"skill": skill_name, "applied": False, "error": "upstream_url 없음"}

    upstream = fetch_upstream(url)
    if upstream is None:
        return {"skill": skill_name, "applied": False, "error": "HTTP fetch 실패"}

    local = local_path.read_text(errors="ignore") if local_path.exists() else ""
    trigger_block = extract_trigger_conditions(local)

    # trigger_conditions가 있으면 upstream에 재삽입
    final_content = reinsert_trigger_conditions(upstream, trigger_block) if trigger_block else upstream

    # 원자성: backup → 임시 파일 → 검증 → atomic rename
    bak_path = local_path.with_suffix(".md.bak")
    tmp_path = None
    try:
        if local_path.exists():
            shutil.copy2(local_path, bak_path)

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8",
            dir=local_path.parent, delete=False, suffix=".tmp"
        ) as tmp:
            tmp.write(final_content)
            tmp_path = Path(tmp.name)

        # 기본 검증: YAML frontmatter 파싱 가능 여부
        if "---" not in final_content:
            raise ValueError("유효하지 않은 SKILL.md: frontmatter 없음")

        tmp_path.replace(local_path)

        if not keep_backup and bak_path.exists():
            bak_path.unlink()

        return {
            "skill": skill_name,
            "applied": True,
            "local_overrides_preserved": ["trigger_conditions"] if trigger_block else [],
            "backup": str(bak_path) if keep_backup else None,
            "error": None,
        }

    except Exception as e:
        # 롤백
        if bak_path.exists():
            try:
                shutil.copy2(bak_path, local_path)
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()
                return {"skill": skill_name, "applied": False,
                        "error": f"apply 실패 (rollback 완료): {e}",
                        "exit_hint": 3}
            except Exception as rb_err:
                return {"skill": skill_name, "applied": False,
                        "error": f"apply 실패 + rollback 실패 (데이터 손실 위험): {e} / {rb_err}",
                        "backup": str(bak_path),
                        "exit_hint": 4}
        return {"skill": skill_name, "applied": False, "error": str(e), "exit_hint": 2}
