#!/usr/bin/env python3
"""
skill-advisor --session-review
Recommend related skills based on files edited in the current Claude Code session.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Ensure scripts/ dir is on sys.path for sibling imports (constants, jsonl_analyzer, etc.)
_SCRIPTS_DIR = str(Path(__file__).parent.resolve())
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from constants import (  # noqa: E402
    DATA_DIR,
    EXCLUDE_PREFIXES,
    FILE_WRITE_TOOLS,
    PROJECTS_BASE,
    SKILL_INDEX,
)
from jsonl_analyzer import AnalysisError, analyze_session_signals  # noqa: E402
from signal_to_skill import map_signals_to_skills  # noqa: E402
from hard_gate_parser import load_hard_gates  # noqa: E402
from session_activity import extract_slash_commands  # noqa: E402
from lib.session_id import extract_session_id, _is_valid_uuid  # noqa: E402

_RETRO_SKILL_NAME = "session-retrospective"
_RETRO_REPO_URL = "https://github.com/accidentalrebel/claude-skill-session-retrospective"


def is_retro_available(skills_dir: Path | None = None) -> tuple[bool, str | None]:
    """Detect session-retrospective and retrieve session JSONL via get-session.sh.

    Returns:
        (True, tmp_jsonl_path) on Track 1 success.
        (False, None) on Track 2 fallback — always safe to ignore second element.

    Track 1 requirements:
        1. session-retrospective skill installed (SKILL.md + get-session.sh present)
        2. session_id 획득 가능 (hook stdin .session_id 1순위 / CLAUDE_SESSION_ID env var 2순위·deprecation)
        3. get-session.sh exits 0

    Args:
        skills_dir: Inject for testing. When None, checks CLAUDE_SKILLS_DIR env var then default.
    """
    env_path = os.environ.get("CLAUDE_SKILLS_DIR")
    base = skills_dir or (Path(env_path) if env_path else None) or (Path.home() / ".claude" / "skills")
    if base != (Path.home() / ".claude" / "skills"):
        print(f"[INFO] skill-advisor: using CLAUDE_SKILLS_DIR: {base}", file=sys.stderr)

    retro = base / _RETRO_SKILL_NAME
    script = retro / "scripts" / "get-session.sh"

    # 파일 존재 확인
    if not (retro.exists() and (retro / "SKILL.md").exists() and script.exists()):
        return False, None

    # 심볼릭 링크 거부 (보안)
    if script.is_symlink():
        print("[WARN] skill-advisor: get-session.sh가 심볼릭 링크 — Track 2로 전환", file=sys.stderr)
        return False, None

    # session_id 획득 (1순위: hook stdin JSON — 지원 시 / 2순위: env var deprecation fallback)
    session_id = extract_session_id() or ""
    if not session_id:
        return False, None

    # get-session.sh 실행
    try:
        result = subprocess.run(
            [str(script), session_id],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return False, None
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.write(result.stdout)
        tmp.close()
        return True, tmp.name
    except subprocess.TimeoutExpired as e:
        if hasattr(e, "process") and e.process:
            e.process.kill()
        return False, None
    except Exception:
        return False, None


def find_jsonl_by_session_id(session_id: str | None) -> Path | None:
    """session_id 로 JSONL 을 cwd_hash scope 내에서 직접 해석 (CSR #965 PRIMARY).

    Claude Code 는 세션 transcript 를 PROJECTS_BASE/<cwd_hash>/<session_id>.jsonl
    (UUID 명명) 으로 저장한다. (cwd_hash, session_id) 튜플은 PROJECTS_BASE 내에서
    유일하다고 가정 — 이 불변량 덕에 global 검색 없이 직접 경로 해석이 가능하다.
    cwd_hash scope 를 벗어난 global rglob 은 하지 않는다 (다른 cwd 세션 오선택 차단).

    Returns:
        해당 파일 Path (존재 시) 또는 None (부재 시 — caller 가 다음 우선순위로 폴백).
    """
    if not session_id:
        return None
    cwd_hash = str(Path(os.getcwd()).resolve()).replace("/", "-")
    candidate = PROJECTS_BASE / cwd_hash / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None


def find_jsonl(confirm: bool = False) -> Path | None:
    """cwd_hash scope 내 JSONL 후보 해석 — session_id 미가용 시 last-resort.

    CSR #965: 비대화형 + 후보 ≥2 시 silent most-recent 추측을 금지 (fail-closed).
    단일 후보는 그대로 사용 (정상 단일 세션 무회귀). global rglob 폴백 제거.
    """
    cwd_hash = str(Path(os.getcwd()).resolve()).replace("/", "-")
    project_dir = PROJECTS_BASE / cwd_hash

    if project_dir.exists():
        candidates = sorted(
            project_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    else:
        candidates = []

    if not candidates:
        print("❌ No JSONL session files found.", file=sys.stderr)
        return None

    # 단일 후보 — 모호성 없음, 그대로 사용 (무회귀)
    if len(candidates) == 1:
        return candidates[0]

    # 후보 ≥2 + 대화형 — 사용자 선택
    if confirm:
        print("Available sessions (most recent first):")
        for i, p in enumerate(candidates[:5], 1):
            import datetime
            mt = datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"  {i}. {p.name}  ({mt}, {p.stat().st_size // 1024} KB)")
        try:
            choice = input("Select [1]: ").strip() or "1"
            return candidates[int(choice) - 1]
        except EOFError:
            pass  # 비대화형 → 아래 fail-closed 로 진행 (CSR #965: 추측 금지)
        except (IndexError, ValueError):
            return candidates[0]

    # 후보 ≥2 + 비대화형 → 추측 금지 (cross-session 오탐 차단, CSR #965)
    print(
        f"⚠ {len(candidates)}개 세션 후보 발견 — session_id 미확보 상태에서 "
        "자동 선택을 거부합니다 (CSR #965). --jsonl <경로> 명시 또는 "
        "--confirm 대화형 선택을 사용하세요.",
        file=sys.stderr,
    )
    for p in candidates[:5]:
        print(f"  - {p.name}", file=sys.stderr)
    return None


def _emit_coherence_mismatch_audit(stem: str, live: str, jsonl_source: str) -> None:
    """Best-effort append-only audit emit for a coherence mismatch (CSR #1061, sparse).

    Fail-open BY POLICY: ALL failures — non-zero exit from the helper, timeout, flock
    contention, transport errors — are intentionally ignored. The reason is NOT that the
    payload is valid by construction (json.dumps validity only guards serialization, a
    different layer than subprocess execution success); it is that this audit is a
    best-effort side-channel that must never alter the read-only diagnostic's behavior or
    exit code (ChatGPT/Claude-Web DA, CSR #1061). Drops under lock contention are accepted
    and NOT retried (hook-troubleshooting.md §4: restricted-write can fail silently).
    """
    try:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = json.dumps({
            "event": "session_coherence_mismatch",
            "producer": "session-review.py",
            "schema_version": "1",
            "stem": stem,
            "live": live,
            "jsonl_source": jsonl_source,
            "ts": ts,
        })
        helper = Path.home() / ".claude" / "scripts" / "append-audit-event.sh"
        subprocess.run(
            [str(helper)], input=payload, text=True,
            timeout=2, capture_output=True,
        )
    except Exception:
        pass  # fail-open: see docstring


def check_session_coherence(jsonl: Path | None, jsonl_source: str) -> str | None:
    """P1-c (CSR #971): defense-in-depth coherence check.

    Warn when the chosen transcript may NOT belong to the live session — a tertiary
    advisory net on top of #965 P1-a (session_id-direct resolution) + P1-b (fail-closed).
    Returns a warning string, or None when coherent OR unverifiable (no false alarm).

    Boundary (L-1, CSR #971 DA): this validates *selection coherence* (does the chosen
    file's identity match the live session), NOT transcript content integrity.

    Side-channel (CSR #1061): on mismatch ONLY, emits one best-effort append-only audit
    event (session_coherence_mismatch) via append-audit-event.sh. This does NOT mutate the
    diagnosed session/transcript — the read-only contract is "no target mutation", not "no
    writes anywhere". Emission is best-effort/fail-open (see _emit_coherence_mismatch_audit).

    The live signal is read DIRECTLY from the per-process env var CLAUDE_CODE_SESSION_ID,
    NOT from extract_session_id() / _current_session_id (CSR #971 CRITICAL C-1): those
    degrade to the shared per-cwd .session-hint — the exact cross-session contamination
    vector #965 fixed — which would make the check certify coherence against the same
    poisoned well (false silence), and a stem-derived live id would be tautological.
    Per-process env absent/invalid -> return None (unverifiable; accepted residual gap).
    """
    # session_id_direct is coherent by construction (stem == resolved sid). Invariant:
    # find_jsonl_by_session_id builds <cwd_hash>/<session_id>.jsonl, so stem IS the sid.
    if jsonl_source == "session_id_direct":
        return None
    # Only the per-process env is a trustworthy, non-circular live oracle (C-1).
    live = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if not _is_valid_uuid(live):
        return None  # unverifiable: no trustworthy live signal
    stem = jsonl.stem if jsonl else ""
    if not _is_valid_uuid(stem):
        return None  # non-UUID stem (e.g. track1 temp file) -> cannot compare
    if stem != live:
        _emit_coherence_mismatch_audit(stem, live, jsonl_source)
        return (
            f"⚠ selected transcript session_id {stem} != live session {live} "
            "— possible cross-session pickup; use --jsonl to override (CSR #971)"
        )
    return None


_MAX_JSONL_SIZE = 100 * 1024 * 1024  # 100MB


def extract_edits(jsonl: Path, max_edits: int = 200) -> tuple[list[dict], dict]:
    # JSONL 크기 제한 — 100MB 초과 시 최근 부분만 읽음
    try:
        size = jsonl.stat().st_size
    except OSError:
        size = 0
    if size > _MAX_JSONL_SIZE:
        print(
            f"[WARN] JSONL {size // 1024 // 1024}MB > 100MB — 최근 부분만 분석합니다.",
            file=sys.stderr,
        )
        with jsonl.open("rb") as fh:
            fh.seek(-_MAX_JSONL_SIZE, 2)
            raw = fh.read()
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    else:
        try:
            text = jsonl.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            text = jsonl.read_text(encoding="utf-8", errors="replace")
            print("[WARN] Encoding issues detected — using replace mode", file=sys.stderr)

    all_lines = text.splitlines()
    tool_uses_seen = 0
    parse_errors = 0
    edits: list[dict] = []

    for line in reversed(all_lines):
        if len(edits) >= max_edits:
            break
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue

        for c in d.get("message", {}).get("content", []) or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            tool_uses_seen += 1
            name = c.get("name", "")
            if name in FILE_WRITE_TOOLS:
                inp = c.get("input", {})
                path = inp.get("file_path") or inp.get("path")
                if path:
                    edits.append({"file": path, "tool": name})
                    if len(edits) >= max_edits:
                        break

    stats = {
        "total_lines": len(all_lines),
        "tool_uses": tool_uses_seen,
        "edits_found": len(edits),
        "parse_errors": parse_errors,
    }
    return edits, stats


def glob_confidence(g: str) -> str:
    depth = g.count("/")
    has_double_star = "**" in g
    is_simple_ext = has_double_star and depth <= 1 and g.count(".") == 1
    if is_simple_ext:
        return "low"
    if has_double_star and depth >= 2:
        return "medium"
    if depth >= 2:
        return "high"
    return "medium"


def load_skill_index() -> list[dict]:
    if not SKILL_INDEX.exists():
        try:
            hook = Path.home() / ".claude" / "hooks" / "skill-index.sh"
            # 심볼릭 링크 거부 (보안)
            if not hook.is_symlink() and hook.is_file():
                try:
                    subprocess.run(["zsh", str(hook)], capture_output=True, timeout=10)
                except subprocess.TimeoutExpired as e:
                    if hasattr(e, "process") and e.process:
                        e.process.kill()
        except Exception:
            pass
    if not SKILL_INDEX.exists():
        return []
    try:
        data = json.loads(SKILL_INDEX.read_text(encoding="utf-8"))
        # v1/v2 하위 호환
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return data.get("skills", [])
        return []
    except Exception:
        return []


def build_candidates(edits: list[dict], skills: list[dict]) -> dict[str, dict]:
    order = {"high": 3, "medium": 2, "low": 1}
    seen: set[tuple] = set()
    per_skill: dict[str, dict] = {}

    for skill in skills:
        name = skill.get("skill", "?")
        for g in skill.get("file_path_globs", []):
            for edit in edits:
                f = edit["file"]
                if any(f.startswith(p) for p in EXCLUDE_PREFIXES):
                    continue
                key = (name, f)
                if key in seen:
                    continue
                if fnmatch.fnmatch(f, g):
                    seen.add(key)
                    conf = glob_confidence(g)
                    cur = per_skill.get(name)
                    if not cur:
                        per_skill[name] = {
                            "skill": name,
                            "file": Path(f).name,
                            "_full_path": f,
                            "glob": g,
                            "confidence": conf,
                            "matched_files": 1,
                            "matched_paths": [f],
                        }
                    elif order[conf] > order[cur["confidence"]]:
                        prev_paths = cur["matched_paths"]
                        prev_paths.append(f)
                        per_skill[name] = {
                            "skill": name,
                            "file": Path(f).name,
                            "_full_path": f,
                            "glob": g,
                            "confidence": conf,
                            "matched_files": len(prev_paths),
                            "matched_paths": prev_paths,
                        }
                    else:
                        cur["matched_files"] += 1
                        cur["matched_paths"].append(f)

    return per_skill


def build_proposals(edits: list[dict], candidates: dict[str, dict]) -> list[dict]:
    from datetime import datetime, timezone
    matched_paths: set[str] = set()
    for c in candidates.values():
        for p in c.get("matched_paths", []):
            matched_paths.add(p)
        if "_full_path" in c:
            matched_paths.add(c["_full_path"])
    unmatched = [
        e["file"] for e in edits
        if e["file"] not in matched_paths
        and not any(e["file"].startswith(p) for p in EXCLUDE_PREFIXES)
    ]

    proposals = []
    for f in unmatched[:5]:
        p = Path(f)
        proposals.append({
            "schema_version": "1.0",
            "skill": "(unknown — no matching skill)",
            "target_field": "file_path_globs",
            "proposal_type": "add_glob",
            "value": f"**/{p.name}",
            "current_value": [],
            "confidence": "low",
            "reason": f"Edited file '{p.name}' matched no skill glob",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
    return proposals


def _load_ssot_tier_map() -> dict[str, str]:
    """SSOT(~/.claude/hard-gates.json)에서 id → tier 매핑을 로드한다.

    CSR #561 S2에서 도입된 SSOT와 skill-advisor/data/hard-gates.json은 별개 파일이다.
    Tier coverage 요약을 위해 SSOT의 id·tier 쌍만 참조하며, 파싱 실패 시 빈 dict.
    """
    ssot = Path.home() / ".claude" / "hard-gates.json"
    if not ssot.exists():
        return {}
    try:
        data = json.loads(ssot.read_text(encoding="utf-8"))
        return {g["id"]: g.get("tier", "?") for g in data.get("gates", []) if g.get("id")}
    except (json.JSONDecodeError, OSError):
        return {}


# CSR #1030: structured-signal channel — a detection axis ORTHOGONAL to the text
# session_signals (which match file paths / error snippets). A structured signal is a
# ground-truth JSONL event presence (e.g. a subagent tool_use), not a text token. Each
# handler takes the structured context and returns a list of triggered_by labels (empty =
# not triggered). The dispatch map keeps this extensible — a sibling gate (e.g. CSR #1039
# completion_context) registers a new handler with zero changes to the per-gate loop.
def _detect_subagent_invoked(ctx: dict) -> list[str]:
    """handoff-verify 구조화 신호: 세션에서 서브에이전트(Agent/Task)가 실행됐는가.

    triggered_by 라벨에 distinct subagent_type 을 박제 (투명성 — da-chain Gemini Q3 /
    Claude Web). type 미상이면 일반 'subagent:Agent' 라벨로 표기.
    """
    if ctx.get("subagent_count", 0) <= 0:
        return []
    types = ctx.get("subagent_types", [])
    if not types:
        return ["subagent:Agent"]
    return [f"subagent:{t or 'Agent'}" for t in types]


# CSR #1039: completion-context structured signal for verification-before-completion.
# TAXONOMY OWNERSHIP (ChatGPT DA M3): this consumer constant MUST track the set of completion
# events emitted by the PRODUCER hook `~/.claude/hooks/completion-claim-detector.sh`. If that hook
# adds a new completion-claim event, this constant must be updated or recall silently degrades.
# test_completion_claim_events_pinned guards the known names. The hook emits one of these only AFTER
# it detects a completion declaration (COMPLETION_PATTERNS) that survives its negative filter — so
# presence of any such event for a session is a producer-attached structured signal that a completion
# was declared. NO assistant-text matching here (avoids CSR #1027 substring false positives).
COMPLETION_CLAIM_EVENTS = frozenset([
    "completion_claim_detected",
    "completion_coverage_gap",
    "completion_claim_skipped_evidence_present",
    "completion_coverage_gap_unclassified_no_marker",
    "completion_claim_coverage_satisfied",
    "completion_claim_blocked",
    "completion_claim_detected_skip_override",
    "completion_claim_coverage_satisfied_unclassified_minmarker",
])


def _detect_completion_context_state(session_id: str | None) -> str:
    """CSR #1039: did the hook record a completion claim for this session?

    Returns one of (ChatGPT DA H2 — distinct operational states, NOT a collapsed bool):
        "present"          : a COMPLETION_CLAIM_EVENTS event for session_id exists in the audit log
        "absent"           : full scan found no matching event
        "audit_missing"    : the audit log file does not exist
        "audit_unreadable" : the audit log could not be read (permission/OS error)

    This is a PRESENCE-ONLY boolean-grade API (ChatGPT DA M4) — it early-returns on the first match
    and intentionally does NOT compute first/last/count/proximity. Temporal-proximity correlation
    (the M2 residual) would need a different API; do not overload this one.

    Reads `~/.claude/da-tools/hard-gate-audit.jsonl` line by line with a PER-LINE parse guard
    (Claude Web DA M3): malformed/torn lines (the restricted-write torn-last-line norm + concurrent
    appends) are SKIPPED, not fatal — scanning continues. Only a missing/unreadable file yields a
    non-scan state.
    """
    if not session_id:
        return "absent"
    audit_path = Path.home() / ".claude" / "da-tools" / "hard-gate-audit.jsonl"
    if not audit_path.exists():
        return "audit_missing"
    try:
        with audit_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # torn/concurrent-append line — skip, keep scanning
                if not isinstance(rec, dict):
                    continue
                if rec.get("session_id") == session_id and rec.get("event") in COMPLETION_CLAIM_EVENTS:
                    return "present"
    except (PermissionError, OSError):
        return "audit_unreadable"
    return "absent"


def _detect_completion_context(ctx: dict) -> list[str]:
    """CSR #1039 structured-signal handler — PURE ADDITIVE detector (Claude Web DA H1).

    Obeys the #1030 dispatch contract exactly: returns labels to APPEND, never strips. The actual
    AND-gating (stripping error: outcomes when no completion context) lives in the separate post-pass
    `_apply_completion_context_gate`, so the dispatch map stays additive/monotonic.
    """
    return ["completion_context"] if ctx.get("completion_context_present") else []


def _apply_completion_context_gate(
    triggered_by: list[str], gate: dict, completion_context_present: bool
) -> tuple[list[str], list[str]]:
    """CSR #1039 AND-combination post-pass — PURE (returns NEW lists, no in-place mutation —
    coding-style immutability rule, Claude Web DA L2).

    For a gate declaring `require_completion_context: true`, a failure-OUTCOME trigger (an `error:`
    label) only "counts" when a completion was actually declared in the session. When the completion
    context is absent, the `error:` labels are stripped so the gate does not fire on pure-debugging
    failures (DoD #3). When present, they are kept (DoD #2) and the dispatch loop's appended
    `completion_context` label provides transparency.

    Returns (new_triggered_by, suppressed_signals). `file:` labels are intentionally left untouched
    (surgical scope — editing a test file remains an independent trigger, consistent with CSR #1027).

    The `completion_context` label is TRANSPARENCY ONLY — a companion to a real trigger (error: or
    file:), NEVER an independent trigger. A bare completion claim with no test signal must NOT fire
    the gate (that would flag verification on virtually every completion-claiming session — a
    precision regression and outside the #1039 DoD, which scopes to the failure-OUTCOME class).
    """
    if not gate.get("require_completion_context"):
        return list(triggered_by), []
    if not completion_context_present:
        # DoD #3: strip failure-OUTCOME triggers (no completion declared). Also drop any bare
        # completion_context label (defensive — handler emits it only when present, but be safe).
        kept = [t for t in triggered_by
                if not t.startswith("error:") and t != "completion_context"]
        suppressed = [t for t in triggered_by if t.startswith("error:")]
        return kept, suppressed
    # present: keep failure-OUTCOME triggers (DoD #2). completion_context is transparency-only —
    # retain it only as a companion to a real trigger; drop it if it would be the SOLE trigger.
    real_triggers = [t for t in triggered_by if t != "completion_context"]
    if real_triggers:
        return list(triggered_by), []
    return [], []


# signal token -> handler(ctx) -> list[str] (triggered_by labels)
STRUCTURED_SIGNAL_HANDLERS = {
    "subagent_invoked": _detect_subagent_invoked,
    "completion_context": _detect_completion_context,
}


# CSR #1093: per-token signal_match_mode (substring | word). Sibling to signal_match_targets
# (#1037). "substring" is the default → byte-identical to pre-#1093 behavior. "word" wraps the token
# in ASCII-identifier boundaries to drop concatenation FPs (auth↛author). Honest limits (DA-grounded):
#  - underscore is an identifier char → "word" will NOT match auth in "auth_token" (intended FN tradeoff).
#  - boundary class is ASCII-only → any non-ASCII (Korean/CJK) token degenerates to substring (no
#    tightening); the caller warns once per gate when such a token opts into "word".
#  - delimiter-adjacent FPs are NOT fixed by "word" (ARIA still matches "aria-label"; "-" is a boundary).
# Evolution path (CSR #1093 M3, ChatGPT DA): only "substring" (default) and "word" are foreseen;
# further modes (Unicode-aware boundary, path-segment) are deferred (YAGNI) — no strategy-pattern
# indirection until a concrete need arises. Unknown modes already fall back to substring + warn.
_WORD_LB = r"(?<![A-Za-z0-9_])"
_WORD_LA = r"(?![A-Za-z0-9_])"


def _token_has_non_ascii(token: str) -> bool:
    """True if any char is outside ASCII — such tokens get no tightening from "word" mode."""
    return any(ord(ch) > 127 for ch in token)


def _signal_matches(token: str, text: str, mode: str) -> bool:
    """Match `token` against `text` per mode. Default "substring" = case-insensitive containment
    (identical to the pre-#1093 `token.lower() in text.lower()`). "word" adds ASCII-identifier
    boundaries via lookbehind/lookahead. Any mode other than "word" is treated as substring."""
    if mode == "word":
        return re.search(_WORD_LB + re.escape(token) + _WORD_LA, text, re.IGNORECASE) is not None
    return token.lower() in text.lower()


def build_hard_gate_candidates(
    edits: list[dict],
    slash_commands: list[str],
    error_signals: list[dict],
    session_id: str | None = None,
    subagent_invocations: list[dict] | None = None,
    completion_context_state: str = "absent",
) -> tuple[list[dict], list[str]]:
    """Hard Gate 트리거 후보 탐지 (CSR #825 schema_version 2).

    Returns:
        (candidates, warnings)

    detected (v2, 4 string status):
        "executed"           : slash_command_found 매칭 (실행 evidence)
        "triggered"          : triggered_by 비어있지 않음 (조건 매칭, 실행 미확인 — CSR #825 C-A1 회피)
        "artifact_confirmed" : gate-artifacts/.done 마커 확인
        "miss"               : 모든 조건 미매칭

    legacy_detected (v1, deprecation 60일 → 2026-07-23):
        bool | "artifact" (기존 schema 호환)

    schema_version: 2
    """
    gates, warnings = load_hard_gates()
    ssot_tier_map = _load_ssot_tier_map()
    invoked = {cmd.lstrip("/") for cmd in slash_commands}

    # CSR #1030: structured-signal context (subagent presence). Count is session-wide and
    # uncapped (jsonl_analyzer full-scan); distinct types are deduped, order-preserved.
    _subagent_invs = subagent_invocations or []
    _subagent_count = len(_subagent_invs)
    _subagent_types: list[str] = []
    for _inv in _subagent_invs:
        _t = _inv.get("subagent_type", "")
        if _t and _t not in _subagent_types:
            _subagent_types.append(_t)
    # CSR #1039: completion-context presence (producer-attached, from hard-gate-audit.jsonl).
    # All non-"present" states (absent / audit_missing / audit_unreadable) gate as absent —
    # fail-toward-absent (conservative for an advisory: prefer a false negative over a false alarm).
    _completion_context_present = completion_context_state == "present"
    struct_ctx = {
        "subagent_count": _subagent_count,
        "subagent_types": _subagent_types,
        "completion_context_present": _completion_context_present,
    }

    # gate-artifacts 디렉토리에서 .done 마커 확인 (JSONL 기반 — stale 마커 방지)
    _gate_dir = Path.home() / ".claude" / "gate-artifacts"
    _done_suffix = f".{session_id}" if session_id else ""

    results = []
    for gate in gates:
        skill = gate.get("skill", "")
        slash_matched = skill in invoked

        # v1 legacy_detected (60일 deprecation)
        legacy_detected: bool | str = slash_matched
        detection_basis = "slash_command_found" if slash_matched else "JSONL keyword match [ESTIMATED]"

        # hook 방식 게이트: gate-artifacts/<skill>.done.<session_id> 마커 탐지
        artifact_confirmed = False
        if not slash_matched and session_id:
            done_file = _gate_dir / f"{skill}.done{_done_suffix}"
            if done_file.exists():
                legacy_detected = "artifact"
                detection_basis = "gate-artifact .done 마커 확인 (hook 방식 처리)"
                artifact_confirmed = True

        triggered_by: list[str] = []
        # CSR #1037: per-signal match_target (hard-gates.json `signal_match_targets` sibling object,
        # schema 1.1). A token maps to "file" (match edited paths only), "error" (match error
        # snippets only), or "both". Tokens absent from the map — and every gate without the field —
        # default to "both", so this is fully backward-compatible. This lets verification's path
        # tokens (/tests/ etc.) be file-only (removing the /tests/-in-error-text FP) while its
        # OUTCOME tokens (AssertionError, --- FAIL, ...) are error-only (criterion #2 via failure
        # outcome, not path presence).
        match_targets = gate.get("signal_match_targets", {})
        # CSR #1093: per-token match mode (substring | word). Keys are the RAW case-sensitive token,
        # identical to signal_match_targets (case is handled by re.IGNORECASE, never by lowercasing
        # the key). Config warnings are emitted ONCE per gate here (not per match attempt).
        mode_map = gate.get("signal_match_mode", {})
        if mode_map:
            _sigset = set(gate.get("session_signals", []))
            for _mk, _mv in mode_map.items():
                if _mk not in _sigset:
                    warnings.append(
                        f"gate '{skill}' signal_match_mode key '{_mk}' is not in session_signals "
                        f"(orphaned — token renamed? entry falls back to substring)"
                    )
                if _mv not in ("substring", "word"):
                    warnings.append(
                        f"gate '{skill}' signal_match_mode['{_mk}']='{_mv}' is an unknown mode "
                        f"(treated as substring)"
                    )
                elif _mv == "word" and _token_has_non_ascii(_mk):
                    warnings.append(
                        f"gate '{skill}' signal_match_mode['{_mk}']='word' but the token is non-ASCII "
                        f"(ASCII-only boundary → degenerates to substring; no tightening)"
                    )
        for sig in gate.get("session_signals", []):
            target = match_targets.get(sig, "both")
            mode = mode_map.get(sig, "substring")
            if mode not in ("substring", "word"):
                mode = "substring"  # unknown mode → substring (warned once per gate above)
            if target in ("file", "both"):
                for edit in edits:
                    if _signal_matches(sig, edit["file"], mode):
                        name = Path(edit["file"]).name
                        if f"file:{name}" not in triggered_by:
                            triggered_by.append(f"file:{name}")
                        break
            if target in ("error", "both"):
                for err in error_signals:
                    snippet = err.get("snippet", "")
                    if _signal_matches(sig, snippet, mode):
                        label = f"error:{sig}"
                        if label not in triggered_by:
                            triggered_by.append(label)
                        break

        # CSR #1030: structured-signal channel (orthogonal to text session_signals).
        # Unknown declared signals warn (no silent gate disable — da-chain ChatGPT M-1).
        for sig in gate.get("structured_signals", []):
            handler = STRUCTURED_SIGNAL_HANDLERS.get(sig)
            if handler is None:
                warnings.append(
                    f"gate '{skill}' declares unknown structured_signal '{sig}' "
                    f"(no registered handler)"
                )
                continue
            for label in handler(struct_ctx):
                if label not in triggered_by:
                    triggered_by.append(label)

        # CSR #1039: AND-combination post-pass (runs BEFORE detected_v2 so a stripped gate demotes
        # to "miss"). For a gate requiring completion context, error: outcome triggers only count
        # when a completion was declared (DoD #3 strip / DoD #2 keep). Pure; file: untouched.
        triggered_by, _suppressed_signals = _apply_completion_context_gate(
            triggered_by, gate, _completion_context_present
        )

        # v2 detected (4 string status — CSR #825 C-A1 회피, triggered_by 비어있지 않으면 격상)
        if slash_matched:
            detected_v2 = "executed"
        elif artifact_confirmed:
            detected_v2 = "artifact_confirmed"
        elif triggered_by:
            detected_v2 = "triggered"   # CSR #825 핵심 변경 — false negative 차단
        else:
            detected_v2 = "miss"

        results.append({
            "skill": skill,
            "tier": ssot_tier_map.get(skill, "?"),
            "trigger_pattern": gate.get("trigger_pattern", ""),
            "source": gate.get("source", "hard-gates.json"),
            "detected": detected_v2,           # v2 (4 string status, CSR #825)
            "legacy_detected": legacy_detected, # v1 (60일 deprecation 2026-07-23)
            "triggered_by": triggered_by[:3],
            "detection_basis": detection_basis,
            "schema_version": 2,
            # CSR #1030: session-wide subagent count (audit — "N subagents delegated,
            # handoff-verify not run"). Only meaningful for gates with structured_signals.
            "subagent_count": _subagent_count,
            # CSR #1039: completion-context observability (ChatGPT DA H2 — distinguish
            # "no failure" from "suppressed (no completion claim)" from "audit infra failed").
            # state ∈ {present, absent, audit_missing, audit_unreadable}; suppressed_signals lists
            # the error: outcome labels stripped by the require_completion_context gate.
            "completion_context_state": completion_context_state,
            "suppressed_signals": _suppressed_signals,
        })
    return results, warnings


def build_unified_skill_view(
    hard_gate_candidates: list[dict],
    slash_commands: list[str],
    skill_candidates: list[dict],
    signal_recommendations: list[dict],
    top_n: int = 10,
) -> dict:
    """unified_skill_view — Hard Gate + slash_command + file-glob + signal 통합 view.

    Ordering rule (CSR #825 E):
        1. Hard Gate (Tier A → B → C → D → ?)
        2. slash_command (Hard Gate에 미포함된 명령)
        3. file-glob (skill_candidates)
        4. signal_recommendations

    top_n cap: 기본 10 (CW-HIGH-2 visual complexity 회피)
    """
    seen_skills: set[str] = set()
    view: list[dict] = []

    # 1. Hard Gate (Tier 순서)
    tier_order = ["A", "B", "C", "D", "?"]
    for tier in tier_order:
        for hgc in hard_gate_candidates:
            if hgc.get("tier") == tier and hgc["skill"] not in seen_skills:
                view.append({
                    "rank": len(view) + 1,
                    "skill": hgc["skill"],
                    "source": "hard_gate",
                    "tier": tier,
                    "status": hgc.get("detected", "miss"),
                })
                seen_skills.add(hgc["skill"])

    # 2. slash_command (Hard Gate에 미포함)
    for cmd in slash_commands:
        skill = cmd.lstrip("/")
        if skill not in seen_skills:
            view.append({
                "rank": len(view) + 1,
                "skill": skill,
                "source": "slash_command",
            })
            seen_skills.add(skill)

    # 3. skill_candidates (file-glob)
    for sc in skill_candidates:
        skill = sc.get("skill", "")
        if skill and skill not in seen_skills:
            view.append({
                "rank": len(view) + 1,
                "skill": skill,
                "source": "file_glob",
                "matched_pattern": sc.get("matched_pattern", ""),
            })
            seen_skills.add(skill)

    # 4. signal_recommendations
    for sr in signal_recommendations:
        skill = sr.get("skill", "")
        if skill and skill not in seen_skills:
            view.append({
                "rank": len(view) + 1,
                "skill": skill,
                "source": "signal",
                "signal": sr.get("signal", ""),
            })
            seen_skills.add(skill)

    total = len(view)
    truncated = total > top_n
    return {
        "unified_skill_view": view[:top_n],
        "total_candidates": total,
        "top_n_cap": top_n,
        "truncated": truncated,
        "truncation_note": f"Total {total} candidates, showing top {top_n}" if truncated else None,
    }


def build_tier_coverage_summary(candidates: list[dict]) -> dict[str, dict]:
    """Tier별 coverage 집계 (CSR #965 — v2 4-status 구분).

    v2 detected status: "executed" | "triggered" | "artifact_confirmed" | "miss".
    - confirmed(=detected) = executed + artifact_confirmed (실제 실행 증거)
    - signal_only = triggered (파일/에러 신호만 — 실행 증거 아님)
    - miss 는 어느 confirmed 카운트에도 포함 안 됨

    이전 버그(CSR #965): `if detected_val:` 가 v2 문자열("miss" 포함)을 모두
    truthy 로 집계 → 전부 detected 로 오집계. v1 bool/"artifact" 입력 호환 유지.

    Returns:
        {'A': {'total': N, 'detected': C, 'executed': X, 'artifact': Y,
               'signal_only': Z, 'miss': W, 'skills': [{skill, status}, ...]}, ...}
        ('detected' = executed+artifact — v1 JSON 소비자 back-compat 유지)
    """
    tiers: dict[str, dict] = {}
    for c in candidates:
        tier = c.get("tier", "?")
        entry = tiers.setdefault(
            tier,
            {"total": 0, "detected": 0, "executed": 0,
             "artifact": 0, "signal_only": 0, "miss": 0, "skills": []},
        )
        entry["total"] += 1
        status = c.get("detected")
        # v1 호환 정규화: True→executed, "artifact"→artifact_confirmed,
        # False/None→ triggered(신호 있으면) | miss
        if status is True:
            status = "executed"
        elif status == "artifact":
            status = "artifact_confirmed"
        elif status is False or status is None:
            status = "triggered" if c.get("triggered_by") else "miss"
        if status == "executed":
            entry["executed"] += 1
            entry["detected"] += 1
        elif status == "artifact_confirmed":
            entry["artifact"] += 1
            entry["detected"] += 1
        elif status == "triggered":
            entry["signal_only"] += 1
        else:  # miss
            entry["miss"] += 1
        entry["skills"].append({"skill": c.get("skill", ""), "status": status})
    return tiers


def print_report(
    jsonl: Path,
    stats: dict,
    candidates: dict,
    proposals: list,
    signal_recs: list | None = None,
    has_retro: bool = False,
    hard_gate_candidates: list | None = None,
    hard_gate_warnings: list | None = None,
    slash_commands: list | None = None,
) -> None:
    import datetime
    mt = datetime.datetime.fromtimestamp(jsonl.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    track_label = "[Track 1: session-retrospective]" if has_retro else "[Track 2: built-in]"
    print(f"\n## /skill-advisor --session-review\n")
    print(f"Track: {track_label}")
    print(
        "⚠ Candidate recommendations only — load history not directly verified.\n"
        "  (Phase 1.5 load log required for direct comparison)\n"
    )
    print(f"Session: {jsonl.name}  ({mt}, {jsonl.stat().st_size // 1024} KB)")
    print(
        f"Parsed: {stats['edits_found']} file edit events "
        f"/ {stats['tool_uses']} tool_uses"
        + (f" / ⚠ {stats['parse_errors']} parse errors" if stats['parse_errors'] else "")
    )
    if slash_commands:
        print(f"Slash commands detected: {', '.join(slash_commands[:10])}")

    print("\n---\n### Related Skill Candidates (file-change based)\n")
    if candidates:
        print(f"{'Skill':<22} {'Matched file':<35} {'Glob':<30} {'Confidence'}")
        print("-" * 100)
        for c in sorted(candidates.values(), key=lambda x: -{"high": 3, "medium": 2, "low": 1}[x["confidence"]]):
            n = c.get("matched_files", 1)
            suffix = f" (+{n-1} more)" if n > 1 else ""
            print(f"{c['skill']:<22} {c['file'] + suffix:<35} {c['glob']:<30} {c['confidence']}")
    else:
        print("No related skills found for edited files.")
        print("→ Run `/skill-advisor --scan` to check skill coverage.")

    if signal_recs:
        err_recs = [r for r in signal_recs if r["source"] == "error_signal"]
        cor_recs = [r for r in signal_recs if r["source"] == "correction_signal"]
        if err_recs:
            print("\n---\n### Error-driven Recommendations\n")
            print(f"{'Skill':<22} {'Signal':<35} {'Confidence':<12} {'Evidence'}")
            print("-" * 80)
            for r in sorted(err_recs, key=lambda x: -{"high": 3, "medium": 2, "low": 1}[x["confidence"]]):
                print(
                    f"{r['skill']:<22} {r['signal'][:34]:<35} "
                    f"{r['confidence']:<12} {r['evidence_count']} detected"
                )
        if cor_recs:
            print("\n---\n### Correction-driven Recommendations\n")
            for r in cor_recs:
                print(f"  → {r['skill']} ({r['signal']}, {r['evidence_count']} corrections detected)")

    if proposals:
        print("\n---\n### Improvement Proposals (SkillPatchProposal)\n")
        print("Files edited with no matching skill glob — consider adding globs:\n")
        print(json.dumps(proposals, indent=2, ensure_ascii=False))
        print("\nApply via `skill-creator`. See: /skill-advisor --enrich <skill-name>")

    # Tier Coverage 요약 (SSOT 기반)
    if hard_gate_candidates:
        tier_coverage = build_tier_coverage_summary(hard_gate_candidates)
        if tier_coverage:
            print("\n---\n### Tier Coverage (SSOT ~/.claude/hard-gates.json 기준)\n")
            for tier in ("A", "B", "C", "D", "?"):
                info = tier_coverage.get(tier)
                if not info:
                    continue
                def _skill_badge(s: dict) -> str:
                    # CSR #965 — v2 4-status 뱃지 (이전: d is True/"artifact" 가 v2 문자열과 미매칭)
                    mark = {"executed": "✅", "triggered": "⚠",
                            "artifact_confirmed": "🔶", "miss": "✗"}.get(s.get("status"), "")
                    return f"{s['skill']}{mark}"

                skills_brief = ", ".join(_skill_badge(s) for s in info["skills"])
                print(
                    f"- Tier {tier}: executed {info['executed']} / "
                    f"signal-only {info['signal_only']} / artifact {info['artifact']} / "
                    f"miss {info['miss']} (total {info['total']}) — {skills_brief}"
                )
            print("  ℹ executed ✅ = slash 실행 / signal-only ⚠ = 파일·에러 신호만(실행 아님) "
                  "/ artifact 🔶 = .done 마커 / miss ✗ = 미매칭")

    print()
    if has_retro:
        print(f"🔗 session-retrospective detected — run /session-retrospective for a full retrospective")
    else:
        print(f"💡 TIP: install session-retrospective for a full narrative session retrospective")
        print(f"   {_RETRO_REPO_URL}")


def print_json(
    jsonl: Path,
    stats: dict,
    candidates: dict,
    proposals: list,
    signal_recs: list | None = None,
    has_retro: bool = False,
    hard_gate_candidates: list | None = None,
    hard_gate_warnings: list | None = None,
    slash_commands: list | None = None,
    edits: list | None = None,
) -> None:
    tier_coverage = build_tier_coverage_summary(hard_gate_candidates or [])
    print(json.dumps({
        "session": str(jsonl),
        "track": "track1" if has_retro else "track2",
        "track_info": "session-retrospective" if has_retro else "built-in",
        "edited_files": [e["file"] for e in (edits or [])],
        "slash_commands_found": slash_commands or [],
        "skill_candidates": [
            {k: v for k, v in c.items() if k != "_full_path"}
            for c in candidates.values()
        ],
        "hard_gate_candidates": hard_gate_candidates or [],
        "hard_gate_warnings": hard_gate_warnings or [],
        "tier_coverage": tier_coverage,
        "signal_recommendations": signal_recs or [],
        "proposals": proposals,
        "session_stats": stats,
    }, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="skill-advisor --session-review")
    parser.add_argument("--confirm", action="store_true", help="Choose session interactively")
    parser.add_argument("--max-edits", type=int, default=200, help="Max file edit events to analyze")
    parser.add_argument("--jsonl", type=str, default=None, help="Explicit JSONL path (절대 우선순위)")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    # CSR #829 #2 — --session-scan alias 추가 (사용자 typo 보호)
    parser.add_argument("--session-scan", action="store_true", dest="session_scan_alias",
                        help="alias for --session-review (CSR #829 #2)")
    args = parser.parse_args()

    # 트랙 감지 (JSONL 결정 전 수행 — Track 1은 JSONL을 직접 제공)
    has_retro, retro_jsonl_path = is_retro_available()

    # JSONL 결정 우선순위 (CSR #965 — session_id-direct 추가):
    #   --jsonl > session_id-direct > Track1 > find_jsonl
    # session_id-direct 가 동시 세션 공유 cwd 에서 cross-session 오탐을 근본 차단.
    _resolved_sid: str | None = None
    _jsonl_source = ""  # explicit | session_id_direct | track1 | find_jsonl
    if args.jsonl:
        # --jsonl 경로 검증 (PROJECTS_BASE 또는 /tmp 하위만 허용)
        import tempfile as _tf
        requested = Path(args.jsonl).resolve()
        projects_base = PROJECTS_BASE.resolve()
        tmpdir = Path(_tf.gettempdir()).resolve()
        if not (
            str(requested).startswith(str(projects_base))
            or str(requested).startswith(str(tmpdir))
        ):
            print(
                f"[ERROR] --jsonl 경로는 {projects_base} 또는 {tmpdir} 하위여야 합니다.",
                file=sys.stderr,
            )
            return 2
        # CSR #829 #3 — 명시 사용 가시성 로그 (Track1 자동 detection 회피 확인)
        print(f"[INFO] --jsonl 명시 사용: {requested.name} (Track1·자동 detection skip)",
              file=sys.stderr)
        jsonl: Path | None = requested
        _jsonl_source = "explicit"
    else:
        # session_id-direct (CSR #965 PRIMARY): 현재 세션 session_id 로 정확 해석
        _resolved_sid = extract_session_id() or None
        _sid_jsonl = find_jsonl_by_session_id(_resolved_sid) if _resolved_sid else None
        if _sid_jsonl:
            jsonl = _sid_jsonl
            _jsonl_source = "session_id_direct"
            print(f"[INFO] session_id-direct 해석: {jsonl.name} (CSR #965)", file=sys.stderr)
        elif retro_jsonl_path:
            # Track1 (get-session.sh) legacy fallback. session_id-direct(위) 가
            # 동일 결과를 subprocess/tempfile 없이 더 직접적으로 산출하므로 Track1 은
            # 점진 폐기 대상.
            # 폐기 기준 (CSR #970 항목 B): 다음 둘 다 충족 시 Track1 제거 + is_retro_available
            #   호출 자체 제거 검토 — (1) session_id-direct 해석률(_jsonl_source=session_id_direct)
            #   누적 ≥ 95% (csr-task-skill-audit 등 로그 기반 N주 관측), (2) get-session.sh 미설치
            #   환경에서도 CLAUDE_CODE_SESSION_ID 가용성 확인. 그 전까지는 fallback 유지.
            jsonl = Path(retro_jsonl_path)
            _jsonl_source = "track1"
        else:
            jsonl = find_jsonl(confirm=args.confirm)
            _jsonl_source = "find_jsonl"

    if not jsonl:
        return 2

    edits, stats = extract_edits(jsonl, max_edits=args.max_edits)
    skills = load_skill_index()
    if not skills:
        print("[WARN] skill-index.json unavailable — run: zsh ~/.claude/hooks/skill-index.sh", file=sys.stderr)

    candidates = build_candidates(edits, skills)
    proposals = build_proposals(edits, candidates)

    # 시그널 분석 (두 트랙 공통)
    # CSR #812: edits 전달로 domain_globs 컨텍스트 매칭 활성화 (build-fix false positive 방지)
    signal_recs: list = []
    _subagent_invocations: list = []
    try:
        signals = analyze_session_signals(jsonl, max_events=args.max_edits)
        signal_recs = map_signals_to_skills(signals, edits=edits)
        # CSR #1030: structured subagent signal (uncapped full-scan) for handoff-verify.
        _subagent_invocations = signals.get("subagent_invocations", [])
    except Exception as e:
        print(f"[WARN] skill-advisor: signal analysis failed — {e}", file=sys.stderr)

    # 슬래시 커맨드 추출 + Hard Gate 후보 탐지
    slash_commands = extract_slash_commands(jsonl, max_events=args.max_edits * 2)
    error_signals = [r for r in signal_recs if r.get("source") == "error_signal"]
    # session_id 단일 진실원 (CSR #965 H-2): session_id-direct 로 해석된 경우
    # 그 session_id 가 authoritative — stem 역도출로 재계산하지 않는다.
    # --jsonl 명시 / track1 / find_jsonl 경로는 기존 stem→extract 폴백 유지.
    if _jsonl_source == "session_id_direct":
        _current_session_id = _resolved_sid
    else:
        _jsonl_stem = jsonl.stem if jsonl else ""
        # CSR #971 H-2: single UUID predicate (strict _is_valid_uuid), not the loose
        # len>30 heuristic — avoids minting a bogus session_id from a non-UUID stem.
        _session_id_from_jsonl = _jsonl_stem if _is_valid_uuid(_jsonl_stem) else None
        _current_session_id = _session_id_from_jsonl or extract_session_id() or None

    # P1-c (CSR #971): chosen-JSONL ↔ live-session coherence warning (defense-in-depth).
    _coherence_warning = check_session_coherence(jsonl, _jsonl_source)
    if _coherence_warning:
        print(_coherence_warning, file=sys.stderr)

    # CSR #1039: producer-attached completion-context state (hard-gate-audit.jsonl, SID-filtered).
    _completion_context_state = _detect_completion_context_state(_current_session_id)
    hard_gate_candidates, gate_warnings = build_hard_gate_candidates(
        edits, slash_commands, error_signals, session_id=_current_session_id,
        subagent_invocations=_subagent_invocations,
        completion_context_state=_completion_context_state,
    )

    if args.json_out:
        print_json(
            jsonl, stats, candidates, proposals,
            signal_recs, has_retro,
            hard_gate_candidates, gate_warnings, slash_commands,
            edits=edits,
        )
    else:
        print_report(
            jsonl, stats, candidates, proposals,
            signal_recs, has_retro,
            hard_gate_candidates, gate_warnings, slash_commands,
        )

    # Track 1 임시 파일 정리
    if retro_jsonl_path and Path(retro_jsonl_path).exists():
        try:
            Path(retro_jsonl_path).unlink()
        except Exception:
            pass

    return 0  # --session-review is informational: exit 0 always on success


if __name__ == "__main__":
    sys.exit(main())
