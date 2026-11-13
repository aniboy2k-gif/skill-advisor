"""GitHub raw URL 기반 SKILL.md 콘텐츠 동기화 채널.

CSR #2415: 기준 판(baseline) 비교 — 「상류가 실제로 바뀜」과 「로컬에서 고침」을 구분한다.
baseline = skill-sources.json 의 스킬별 객체 {sha256, ref, recorded_at, note, local_sha256}
  sha256       = normalize(상류 원문) 의 해시 (「여기까지 로컬과 대조해 검토한 상류 판」 — 3-way merge base 아님)
  local_sha256 = 그 baseline 을 쓴 순간의 로컬 SKILL.md normalize 해시
pending_baseline = 작업 트리(--worktree) 적용이 남긴 대기 baseline — 운영 파일이 그 local_sha256 과
  같아졌을 때(병합 + pull)만 유효 baseline 이 된다 (r4 H2).
해시는 두 종류이며 섞지 않는다: upstream_hash = 원문(raw) 해시(resync-skill.sh --expect-upstream-hash 가 받는 값),
upstream_norm_hash = normalize(원문) 해시(baseline·apply·--set-baseline 이 쓰는 값).
"""
import datetime
import difflib
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

# resync-skill.sh 와 같은 함수 본문 (`\n+`: 블록 앞 빈 줄까지 걷는다 — CSR #2358).
TRIGGER_PATTERN = re.compile(r"\n+(<!--trigger_conditions.*?-->)\n", re.DOTALL)
FETCH_TIMEOUT = 10
RAW_URL = re.compile(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$")
REF_EXT = r"(?:md|py|sh|js|json|txt|yaml|yml)"
REF_PATTERNS = (
    re.compile(r"\[[^\]]*\]\(([^)\s]+)\)"),
    re.compile(r"`([^`\s]+\." + REF_EXT + r")`"),
)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(text: str) -> str:
    return TRIGGER_PATTERN.sub("\n", text).strip()


def norm_hash(text: str) -> str:
    return sha256_text(normalize(text))


def fetch_upstream(url: str) -> Optional[str]:
    """엄격한 UTF-8 해독 — 해독 불가는 fetch 오류(None)."""
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        return None


def ls_remote(org: str, repo: str, branch: str) -> Optional[str]:
    """git 전송으로 브랜치 머리 커밋 조회 (REST 아님). 실패 = None."""
    try:
        r = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{org}/{repo}", f"refs/heads/{branch}"],
            capture_output=True, text=True, timeout=FETCH_TIMEOUT,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref == f"refs/heads/{branch}" and re.fullmatch(r"[0-9a-f]{40}", sha):
            return sha
    return None


def parse_raw_url(url: str) -> Optional[tuple]:
    m = RAW_URL.match(url or "")
    return m.groups() if m else None


def pinned_url(url: str, ref: str) -> Optional[str]:
    p = parse_raw_url(url)
    return f"https://raw.githubusercontent.com/{p[0]}/{p[1]}/{ref}/{p[3]}" if p else None


def resolve_pinned(url: str) -> dict:
    """ref 해석: ls-remote 로 커밋 C → 커밋 고정 주소에서 받는다(바이트와 ref 가 같은 대상).
    해석 실패 시 브랜치 주소를 다시 받고 ref=None — 호출자가 해시로 결박한다."""
    p = parse_raw_url(url)
    if p is None:
        return {"ref": None, "text": fetch_upstream(url), "unresolved": "upstream_url is not a raw.githubusercontent.com URL"}
    commit = ls_remote(p[0], p[1], p[2])
    if commit is None:
        return {"ref": None, "text": fetch_upstream(url), "unresolved": f"git ls-remote failed for branch {p[2]}"}
    return {"ref": commit, "text": fetch_upstream(pinned_url(url, commit)), "unresolved": None}


def read_local_strict(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


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


def patch_status(skill_name: str, op_root: Optional[Path]) -> dict:
    """vendor-patches/*-upstream-files.txt 등재 여부 — 세 값: True / False / None(확인 불가)."""
    vp = Path(op_root) / "vendor-patches" if op_root else None
    if vp is None or not vp.is_dir():
        return {"patched": None, "patch_info": f"unavailable: {vp} missing or unreadable"}
    want = f"skills/{skill_name}/SKILL.md"
    sets = []
    try:
        for f in sorted(vp.glob("*-upstream-files.txt")):
            lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()]
            if want in (ln for ln in lines if ln and not ln.startswith("#")):
                sets.append(f.name[: -len("-upstream-files.txt")])
    except (OSError, UnicodeDecodeError) as e:
        return {"patched": None, "patch_info": f"unavailable: {vp} unreadable ({e})"}
    return {"patched": bool(sets), "patch_sets": sets}


def missing_refs(text: str, skill_dir: Path, skills_root: Path) -> list:
    """상류 본문이 가리키는 상대 파일 참조 중 파일 시스템에 없는 것 (URL·~/·절대경로 제외)."""
    found = []
    for pat in REF_PATTERNS:
        for m in pat.finditer(text):
            ref = m.group(1).split("#", 1)[0]
            if (not ref or "://" in ref or ref.startswith(("~", "/", "$", "mailto:"))
                    or any(c in ref for c in "<>{}*")
                    or not re.search(r"\." + REF_EXT + r"$", ref)):
                continue
            if ref not in found:
                found.append(ref)
    missing = []
    for ref in found:
        sibling = ref.startswith("../")
        base = Path(skills_root) if sibling else Path(skill_dir)
        rel = ref[3:] if sibling else ref
        cands = [rel, re.sub(r"(^|/)(references?)/",
                             lambda m: m.group(1) + ("reference/" if m.group(2) == "references" else "references/"), rel)]
        if not any(Path(os.path.normpath(base / c)).exists() for c in cands):
            missing.append(ref)
    return sorted(missing)


def changed_lines(old: str, new: str) -> dict:
    added = removed = 0
    for ln in difflib.ndiff(normalize(old).splitlines(), normalize(new).splitlines()):
        if ln.startswith("+ "):
            added += 1
        elif ln.startswith("- "):
            removed += 1
    return {"added": added, "removed": removed}


def effective_baseline(entry: dict, local_norm: str) -> tuple:
    """(baseline, source) — pending 은 운영 파일이 그 local_sha256 과 같을 때만 유효 (r4 H2)."""
    pend = entry.get("pending_baseline")
    if pend and pend.get("local_sha256") == local_norm:
        return pend, "pending"
    if entry.get("baseline"):
        return entry["baseline"], "committed"
    return None, None


def check(skill_name: str, entry: dict, local_path: Path, op_root: Optional[Path] = None) -> dict:
    """상류 vs 로컬(+기준 판) 비교. 결과 dict 반환 — 읽기 전용."""
    url = entry.get("upstream_url")
    if not url:
        return {"skill": skill_name, "status": "no-url", "error": "upstream_url 없음"}

    if not local_path.exists():
        return {"skill": skill_name, "status": "local-missing", "error": str(local_path)}

    try:
        local = read_local_strict(local_path)
    except (UnicodeDecodeError, OSError) as e:
        return {"skill": skill_name, "status": "fetch-error", "upstream_url": url,
                "error": f"local SKILL.md is not valid UTF-8 or unreadable: {e}"}

    upstream = fetch_upstream(url)
    if upstream is None:
        return {"skill": skill_name, "status": "fetch-error",
                "upstream_url": url, "error": "HTTP fetch 실패"}

    u_norm, l_norm = norm_hash(upstream), norm_hash(local)
    trigger_block = extract_trigger_conditions(local)
    result = {
        "skill": skill_name,
        "upstream_type": "github_raw",
        "upstream_url": url,
        "upstream_hash": sha256_text(upstream),
        "upstream_norm_hash": u_norm,
        "local_hash": sha256_text(local),
        "local_norm_hash": l_norm,
        "local_lines": len(local.splitlines()),
        "upstream_lines": len(upstream.splitlines()),
        "local_overrides": ["trigger_conditions"] if trigger_block else [],
        "applied": False,
        "error": None,
        **patch_status(skill_name, op_root),
    }
    miss_u = missing_refs(upstream, local_path.parent, local_path.parent.parent)
    miss_l = missing_refs(local, local_path.parent, local_path.parent.parent)
    result["missing_refs_upstream"] = miss_u
    result["new_missing_refs"] = [r for r in miss_u if r not in miss_l]

    base, source = effective_baseline(entry, l_norm)
    result["baseline_source"] = source
    if base is None:
        result["status"] = "up-to-date" if u_norm == l_norm else "update-available"
        result["diff_basis"] = "local-vs-upstream (cannot tell which side changed)"
        return result

    result["local_state"] = "same" if l_norm == u_norm else "local-modified"
    if u_norm == base.get("sha256"):
        result["status"], result["baseline_state"] = "up-to-date", "matched"
    else:
        result["status"], result["baseline_state"] = "update-available", "upstream-changed"
        result["changed_lines"] = None
        bref = base.get("ref")
        if not bref:
            result["baseline_content"] = "no-ref"
        else:
            btext = fetch_upstream(pinned_url(url, bref) or "")
            if btext is None or norm_hash(btext) != base.get("sha256"):
                result["baseline_content"] = "unverifiable"
            else:
                result["baseline_content"] = "verified"
                result["changed_lines"] = changed_lines(btext, upstream)

    if source == "committed" and base.get("local_sha256") != l_norm:
        result["status"] = "baseline-unconfirmed"
        result["local_state"] = "changed-since-baseline"
        result["message"] = ("local file differs from the state recorded with the baseline (restored file, "
                             "unmerged PR, or a new local edit); review and run --set-baseline")
    return result


def _git(path: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _blocked(skill_name: str, reason: str) -> dict:
    return {"skill": skill_name, "applied": False, "blocked": True, "reason": reason,
            "exit_hint": 2, "error": None}


def apply(skill_name: str, entry: dict, local_path: Path, check_result: dict, *,
          op_root: Optional[Path] = None, keep_backup: bool = False, force_overwrite: bool = False,
          allow_missing_refs: bool = False, allow_main: bool = False) -> dict:
    """상류 내용으로 local_path(쓰기 대상) 교체. 각 우회 플래그는 자기 검사만 푼다.
    성공 시 new_baseline 반환 — 저장은 호출자(update.py)가 한다."""
    url = entry.get("upstream_url")
    if not url:
        return {"skill": skill_name, "applied": False, "error": "upstream_url 없음"}
    if check_result.get("status") not in ("update-available", "update-available-with-vulnerability"):
        return _blocked(skill_name, f"check status is {check_result.get('status')}; nothing to apply")

    # (a) 패치 세트 등재 스킬 — 우회 없음
    patched = check_result.get("patched")
    if patched is None:
        return _blocked(skill_name, "patch status unavailable; restore vendor-patches or use vendor-patches/resync-skill.sh "
                        f"({check_result.get('patch_info', '')})")
    if patched:
        return _blocked(skill_name, "listed in vendor-patches " + ",".join(check_result.get("patch_sets", []))
                        + " — use vendor-patches/resync-skill.sh")

    target_dir = local_path.parent
    if not target_dir.is_dir() or not local_path.exists():
        return _blocked(skill_name, f"local-missing: {local_path}")
    # (r4 H3) git 서브모듈 안의 스킬 — 우회 없음
    if _git(target_dir, "rev-parse", "--show-superproject-working-tree"):
        return _blocked(skill_name, "target lies inside a git submodule — edit it in the submodule's own repository, "
                        "open its PR, merge, then open the claude-forge pointer PR")
    # (d) 운영 트리 — --allow-main 만 푼다
    if op_root is not None:
        top = _git(target_dir, "rev-parse", "--show-toplevel")
        if top and Path(top).resolve() == Path(op_root).resolve() and not allow_main:
            return _blocked(skill_name, "target is in the operational tree — use --worktree <linked worktree> "
                            "(escape: --allow-main, keeps the .bak)")

    # (e) 커밋 고정 바이트 = check() 가 본 상류
    pin = resolve_pinned(url)
    upstream = pin["text"]
    if upstream is None:
        return _blocked(skill_name, "upstream fetch failed during apply")
    if norm_hash(upstream) != check_result.get("upstream_norm_hash"):
        where = f" (pinned commit {pin['ref']})" if pin["ref"] else ""
        return _blocked(skill_name, f"upstream moved since check; re-run{where}")

    # (c) 참조 무결성 — 쓰기 대상 기준 (r4 M1)
    try:
        current = read_local_strict(local_path)
    except (UnicodeDecodeError, OSError) as e:
        return _blocked(skill_name, f"local changed since check; re-run (unreadable: {e})")
    miss_u = missing_refs(upstream, target_dir, target_dir.parent)
    miss_l = missing_refs(current, target_dir, target_dir.parent)
    new_miss = [r for r in miss_u if r not in miss_l]
    if new_miss and not allow_missing_refs:
        return _blocked(skill_name, "new missing references: " + ", ".join(new_miss) + " (override: --allow-missing-refs)")

    # (g) 쓰기 직전 재읽기 = check() 가 본 로컬 (프롬프트 뒤)
    if norm_hash(current) != check_result.get("local_norm_hash"):
        return _blocked(skill_name, "local changed since check; re-run")
    base, _ = effective_baseline(entry, norm_hash(current))
    warning = None
    if base is not None:
        # (b) 로컬 수정 소실 방지
        if norm_hash(current) != base.get("sha256") and not force_overwrite:
            return _blocked(skill_name, "local edit since the baseline would be dropped (override: --force-overwrite)")
    elif normalize(current) != normalize(upstream):
        # (f) 기준 판 없음 — 로컬 수정과 상류 변경을 구분할 수 없다
        if not force_overwrite:
            return _blocked(skill_name, "no baseline — cannot tell a local edit from an upstream change (vendor-patches "
                            "lists only recorded patches); review and run --set-baseline, or pass --force-overwrite")
    if force_overwrite:
        warning = f"--force-overwrite: local content of {skill_name} replaced by upstream"

    trigger_block = extract_trigger_conditions(current)
    final_content = reinsert_trigger_conditions(upstream, trigger_block) if trigger_block else upstream
    if "---" not in final_content:
        return _blocked(skill_name, "유효하지 않은 SKILL.md: frontmatter 없음")
    keep = keep_backup or force_overwrite or allow_main
    bak_path = local_path.with_suffix(".md.bak")
    tmp_path = None
    try:
        shutil.copy2(local_path, bak_path)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target_dir,
                                         delete=False, suffix=".tmp") as tmp:
            tmp.write(final_content)
            tmp_path = Path(tmp.name)
        tmp_path.replace(local_path)
        if not keep and bak_path.exists():
            bak_path.unlink()
    except Exception as e:
        try:
            shutil.copy2(bak_path, local_path)
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
            return {"skill": skill_name, "applied": False, "error": f"apply 실패 (rollback 완료): {e}", "exit_hint": 3}
        except Exception as rb_err:
            return {"skill": skill_name, "applied": False, "backup": str(bak_path), "exit_hint": 4,
                    "error": f"apply 실패 + rollback 실패 (데이터 손실 위험): {e} / {rb_err}"}

    note = "apply" if pin["ref"] else f"apply; ref unresolved: {pin['unresolved']}"
    res = {
        "skill": skill_name,
        "applied": True,
        "local_overrides_preserved": ["trigger_conditions"] if trigger_block else [],
        "backup": str(bak_path) if keep else None,
        "new_baseline": {
            "sha256": norm_hash(upstream),
            "ref": pin["ref"],
            "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "note": note,
            "local_sha256": norm_hash(final_content),
        },
        "error": None,
    }
    if warning:
        res["warning"] = warning
    return res
