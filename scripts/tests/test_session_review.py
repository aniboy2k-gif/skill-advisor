"""
skill-advisor session-review regression tests.
Run: pytest scripts/tests/test_session_review.py -v
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# Load session-review.py (hyphen → can't use regular import)
_spec = importlib.util.spec_from_file_location(
    "session_review",
    Path(__file__).parent.parent / "session-review.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["session_review"] = _mod

build_candidates = _mod.build_candidates
build_proposals = _mod.build_proposals
find_jsonl = _mod.find_jsonl
find_jsonl_by_session_id = _mod.find_jsonl_by_session_id
print_json = _mod.print_json


FAKE_SKILLS = [
    {
        "skill": "my-skill",
        "file_path_globs": ["**/*.ts"],
        "tool_events": [],
        "utterance_patterns": {},
        "description": "test skill",
    }
]


# ── C-2 fix: full-path deduplication ─────────────────────────────────────────

def test_build_proposals_same_name_different_path():
    """C-2: 동명 이경로 파일에서 한 쪽이 조용히 누락되면 안 된다."""
    edits = [
        {"file": "/proj/src/index.ts", "tool": "Edit"},
        {"file": "/proj/lib/index.ts", "tool": "Edit"},
    ]
    skills = [
        {
            "skill": "my-skill",
            "file_path_globs": ["**/src/**/*.ts"],
            "tool_events": [],
            "utterance_patterns": {},
            "description": "test",
        }
    ]
    candidates = build_candidates(edits, skills)
    proposals = build_proposals(edits, candidates)

    proposed_values = [p["value"] for p in proposals]
    # /proj/lib/index.ts matched no glob → should appear as a proposal
    assert any("index.ts" in v for v in proposed_values), (
        f"/proj/lib/index.ts should produce a proposal but got: {proposed_values}"
    )


def test_build_candidates_stores_full_path():
    """C-2: build_candidates가 _full_path를 저장한다."""
    edits = [{"file": "/proj/src/foo.ts", "tool": "Edit"}]
    candidates = build_candidates(edits, FAKE_SKILLS)
    assert candidates, "Expected at least one candidate"
    for c in candidates.values():
        assert "_full_path" in c, "_full_path field missing from candidate"
        assert c["_full_path"] == "/proj/src/foo.ts"


# ── M-2 fix: extension-less glob ─────────────────────────────────────────────

def test_build_proposals_extensionless_file():
    """M-2: 확장자 없는 파일(Makefile)에 **/Makefile/** 패턴이 생성되면 안 된다."""
    edits = [{"file": "/proj/Makefile", "tool": "Edit"}]
    candidates: dict = {}
    proposals = build_proposals(edits, candidates)
    assert proposals, "Expected a proposal for unmatched Makefile"
    assert proposals[0]["value"] == "**/Makefile", (
        f"Expected '**/Makefile' but got '{proposals[0]['value']}'"
    )
    assert not proposals[0]["value"].endswith("/**"), (
        "Glob must not end with /** for a file without extension"
    )


# ── CSR #965: find_jsonl fail-closed on ambiguity ────────────────────────────

def _make_projects(tmp_path, monkeypatch, n_files):
    """tmp PROJECTS_BASE/<cwd_hash>/ 에 n개 jsonl 생성하고 cwd_hash 반환."""
    import os
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    projects = tmp_path / "projects"
    cwd_hash = str(Path(os.getcwd()).resolve()).replace("/", "-")
    proj_dir = projects / cwd_hash
    proj_dir.mkdir(parents=True)
    sids = []
    for i in range(n_files):
        sid = f"0000000{i}-aaaa-bbbb-cccc-dddddddddddd"
        (proj_dir / f"{sid}.jsonl").write_text("{}")
        sids.append(sid)
    monkeypatch.setattr(_mod, "PROJECTS_BASE", projects)
    return cwd_hash, sids


def test_find_jsonl_failclosed_on_ambiguity(tmp_path, monkeypatch):
    """CSR #965: 비대화형 + 후보 ≥2 → silent 추측 금지, None 반환 (cross-session 차단)."""
    _make_projects(tmp_path, monkeypatch, 2)
    with patch("builtins.input", side_effect=EOFError):
        result = find_jsonl(confirm=True)
    assert result is None, "비대화형 다중 후보는 fail-closed(None)이어야 함"
    # confirm=False (비대화형 기본) 도 동일
    assert find_jsonl(confirm=False) is None


def test_find_jsonl_single_candidate_no_regression(tmp_path, monkeypatch):
    """CSR #965: 단일 후보는 그대로 사용 (정상 단일 세션 무회귀)."""
    _, sids = _make_projects(tmp_path, monkeypatch, 1)
    result = find_jsonl(confirm=False)
    assert result is not None and result.name == f"{sids[0]}.jsonl"


def test_find_jsonl_by_session_id_exact(tmp_path, monkeypatch):
    """CSR #965: session_id-direct 는 cwd_hash scope 내 정확한 파일을 해석한다."""
    _, sids = _make_projects(tmp_path, monkeypatch, 2)
    result = find_jsonl_by_session_id(sids[1])
    assert result is not None and result.name == f"{sids[1]}.jsonl"


def test_find_jsonl_by_session_id_absent_returns_none(tmp_path, monkeypatch):
    """CSR #965: 해당 session_id 파일 부재 시 None (caller 폴백). None 입력도 None."""
    _make_projects(tmp_path, monkeypatch, 1)
    assert find_jsonl_by_session_id("ffffffff-0000-0000-0000-000000000000") is None
    assert find_jsonl_by_session_id(None) is None


# ── D-H1 fix: _full_path not in JSON output ──────────────────────────────────

def test_print_json_excludes_full_path(tmp_path, capsys):
    """D-H1: --json 출력에 _full_path 필드가 포함되지 않는다."""
    import json

    f = tmp_path / "s.jsonl"
    f.write_text("{}")

    candidates = {
        "my-skill": {
            "skill": "my-skill",
            "file": "foo.ts",
            "_full_path": "/secret/path/foo.ts",
            "glob": "**/*.ts",
            "confidence": "medium",
            "matched_files": 1,
        }
    }
    stats = {"total_lines": 1, "tool_uses": 0, "edits_found": 0, "parse_errors": 0}
    print_json(f, stats, candidates, [])
    out = capsys.readouterr().out
    data = json.loads(out)
    for c in data["skill_candidates"]:
        assert "_full_path" not in c, f"_full_path should not appear in JSON output: {c}"


# ── New: Hard Gate + Security + Track tests ──────────────────────────────────

def test_jsonl_path_outside_projects_base_rejected(tmp_path, capsys):
    """보안: PROJECTS_BASE 외부 경로 → exit code 2."""
    import subprocess, sys
    script = Path(_mod.__file__)
    result = subprocess.run(
        [sys.executable, str(script), "--jsonl", "../../../../etc/passwd"],
        capture_output=True, text=True
    )
    assert result.returncode == 2, f"Expected exit 2, got {result.returncode}"
    assert "ERROR" in result.stderr, "Expected [ERROR] in stderr"


def test_track2_when_no_session_id(monkeypatch):
    """session_id 소스(hook stdin / CLAUDE_CODE_SESSION_ID / .session-hint) 모두 없으면 (False, None)."""
    import lib.session_id as _sid
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setattr(_sid, "_read_session_hint", lambda: None)
    available, path = _mod.is_retro_available()
    assert not available, "session_id 없을 때 Track 1이면 안 됨"
    assert path is None


def test_hard_gate_candidates_in_json_output(tmp_path, capsys):
    """JSON 출력에 hard_gate_candidates 키가 포함되어야 한다."""
    import json as _json
    jsonl_file = tmp_path / "test.jsonl"
    jsonl_file.write_text('{"type":"user","message":{"content":[{"type":"text","text":"/plan 실행"}]}}\n')
    stats = {"total_lines": 1, "tool_uses": 0, "edits_found": 0, "parse_errors": 0}
    _mod.print_json(
        jsonl_file, stats, {}, [],
        hard_gate_candidates=[{"skill": "plan", "detected": True}],
        hard_gate_warnings=[],
        slash_commands=["/plan"],
    )
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert "hard_gate_candidates" in data, "hard_gate_candidates 키 없음"
    assert data["track"] == "track2", f"track expected track2, got {data['track']}"
    assert "/plan" in data["slash_commands_found"]


def test_slash_command_no_false_positive(tmp_path):
    """슬래시 커맨드 추출 오탐 방지 (CSR #1038 — #973 구조 기반 contract 정합).

    CSR #973 이후 extract_slash_commands는 message.content가 '문자열'이고
    <command-name> 트리플릿일 때만 추출한다 (자유텍스트 미스캔). 따라서:
      (1) 구조적 게이트: 자유텍스트의 경로/URL(/usr/local 등)은 추출 안 됨.
      (2) 화이트리스트 필터(session_activity.py: known + _KNOWN_PREFIXES):
          트리플릿 *내부*라도 비화이트리스트 토큰(/usr)은 제외 — 진짜 오탐 surface.
      (3) exact-set: 화이트리스트 트리플릿만 정확히 추출.
    """
    import importlib
    sa_path = Path(__file__).parent.parent / "session_activity.py"
    spec = importlib.util.spec_from_file_location("session_activity", sa_path)
    sa_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sa_mod)

    jsonl_file = tmp_path / "test.jsonl"
    # content = 문자열 (#973 contract). 자유텍스트 경로/URL 노이즈 + 화이트리스트
    # 트리플릿 2개(/plan, /skill-advisor) + 비화이트리스트 트리플릿 1개(/usr).
    text = (
        'Looking at /usr/local/bin/python3 and https://github.com/owner/repo/issues. '
        '<command-name>/plan</command-name> and <command-name>/skill-advisor</command-name> '
        'and <command-name>/usr</command-name> should be filtered.'
    )
    jsonl_file.write_text(
        '{"type":"user","message":{"content":"'
        + text.replace('"', '\\"') + '"}}\n'
    )
    cmds = sa_mod.extract_slash_commands(jsonl_file)
    # (2) 화이트리스트 필터 실검증: 트리플릿 내부라도 비화이트리스트 /usr은 제외 (진짜 오탐 surface)
    assert "/usr" not in cmds, f"Non-whitelisted /usr leaked through whitelist filter: {cmds}"
    # (1) 구조적 게이트: 자유텍스트 경로 토큰은 추출 안 됨 (free-text 미스캔 regression guard)
    false_positives = [c for c in cmds if c in ("/usr", "/local", "/bin", "/python3", "/owner", "/repo", "/issues")]
    assert not false_positives, f"False positives detected: {false_positives}"
    # (3) exact-set: 화이트리스트 트리플릿만 정확히 추출 (>= 1 보다 강한 검증)
    assert set(cmds) == {"/plan", "/skill-advisor"}, f"Expected exactly /plan and /skill-advisor, got: {cmds}"


# ── D-H2: H1-E logic correctness ─────────────────────────────────────────────

def test_h1e_classification_for_events_only_skill():
    """D-H2: tool_events>0, globs=0 스킬은 H1-E(info)를 받아야 하며 H1(high)이 아니다."""
    issues: list[dict] = []
    globs: list = []
    events = ["Edit"]
    utterances = {"ko": ["test"]}
    has_utterances = bool(utterances.get("ko") or utterances.get("en"))

    # Replicate the SKILL.md --scan classification logic
    if len(globs) == 0 and len(events) == 0:
        if not has_utterances:
            issues.append({"severity": "high", "code": "H0", "msg": "ghost"})
        else:
            issues.append({"severity": "info", "code": "H1-M", "msg": "manual"})
    elif len(globs) == 0 and len(events) > 0:
        issues.append({"severity": "info", "code": "H1-E", "msg": "events only"})

    codes = [i["code"] for i in issues]
    assert "H1-E" in codes, f"Expected H1-E but got: {codes}"
    assert "H1" not in codes, f"H1 should not appear for events-only skill: {codes}"
    h1e_severities = [i["severity"] for i in issues if i["code"] == "H1-E"]
    assert all(s == "info" for s in h1e_severities), (
        f"H1-E must be info level: {h1e_severities}"
    )


# S4 Phase 7.3 — Tier coverage 확장 테스트
def test_tier_coverage_summary_basic():
    """build_tier_coverage_summary: 빈 리스트는 빈 dict, 항목은 Tier별 집계."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from session_review import build_tier_coverage_summary  # type: ignore

    empty = build_tier_coverage_summary([])
    assert empty == {}

    candidates = [
        {"skill": "security-pipeline", "tier": "A", "detected": True, "triggered_by": []},
        {"skill": "check-context-size", "tier": "A", "detected": False, "triggered_by": []},
        {"skill": "verification-before-completion", "tier": "B", "detected": False, "triggered_by": ["file:foo"]},
        {"skill": "handoff-verify", "tier": "B", "detected": False, "triggered_by": []},
        {"skill": "plan", "tier": "C", "detected": True, "triggered_by": []},
    ]
    summary = build_tier_coverage_summary(candidates)
    assert summary["A"]["total"] == 2
    assert summary["A"]["detected"] == 1  # security-pipeline detected=True
    assert summary["B"]["total"] == 2
    # triggered_by는 트리거 조건만 충족 — 실제 실행 증거 아님 → detected 카운트 제외
    # (build_tier_coverage_summary 함수 주석 정합)
    assert summary["B"]["detected"] == 0
    assert summary["C"]["total"] == 1
    assert summary["C"]["detected"] == 1  # plan detected=True


def test_tier_coverage_4status_v2(tmp_path):
    """CSR #965: v2 4-status 입력을 executed/signal_only/artifact/miss 로 구분 집계.

    이전 버그: 'if detected_val:' 가 "miss" 포함 모든 문자열을 detected 로 오집계.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from session_review import build_tier_coverage_summary  # type: ignore

    candidates = [
        {"skill": "s-exec", "tier": "C", "detected": "executed", "triggered_by": []},
        {"skill": "s-trig", "tier": "C", "detected": "triggered", "triggered_by": ["file:x"]},
        {"skill": "s-arti", "tier": "C", "detected": "artifact_confirmed", "triggered_by": []},
        {"skill": "s-miss", "tier": "C", "detected": "miss", "triggered_by": []},
    ]
    s = build_tier_coverage_summary(candidates)["C"]
    assert s["total"] == 4
    assert s["executed"] == 1
    assert s["signal_only"] == 1
    assert s["artifact"] == 1
    assert s["miss"] == 0 + 1  # 'miss' 1건
    # detected(=confirmed, back-compat) = executed + artifact, "miss"/"triggered" 미포함
    assert s["detected"] == 2
    # skills 엔트리는 status 필드 보유
    assert {e["status"] for e in s["skills"]} == {"executed", "triggered", "artifact_confirmed", "miss"}


def test_tier_coverage_text_breakdown(tmp_path, capsys):
    """CSR #965: Tier Coverage 출력이 '합산 detected' 대신 4-status breakdown 표기."""
    f = tmp_path / "s.jsonl"
    f.write_text("{}")
    stats = {"total_lines": 1, "tool_uses": 0, "edits_found": 0, "parse_errors": 0}
    hgc = [
        {"skill": "plan", "tier": "C", "detected": "executed", "triggered_by": []},
        {"skill": "csr-task", "tier": "C", "detected": "triggered", "triggered_by": ["file:y"]},
    ]
    _mod.print_report(f, stats, {}, [], hard_gate_candidates=hgc, slash_commands=["/plan"])
    out = capsys.readouterr().out
    assert "executed 1" in out and "signal-only 1" in out, out
    assert "plan✅" in out and "csr-task⚠" in out, out
    # 합산 'N/M detected' 형식 제거 확인
    assert "/2 detected" not in out


def test_load_ssot_tier_map_fallback(tmp_path, monkeypatch):
    """_load_ssot_tier_map: SSOT 없거나 parse fail이면 빈 dict 반환."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from session_review import _load_ssot_tier_map  # type: ignore

    # home을 tmp_path로 바꿔 SSOT 부재 시뮬레이션
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = _load_ssot_tier_map()
    assert result == {}


# ── CSR #971: check_session_coherence (P1-c) ─────────────────────────────────

check_session_coherence = _mod.check_session_coherence

_LIVE_UUID = "a1b2c3d4-1234-1234-1234-123456789abc"
_OTHER_UUID = "ffffffff-1234-1234-1234-123456789abc"


def test_coherence_session_id_direct_skipped(monkeypatch):
    """session_id_direct is coherent by construction → no warning even if env differs."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _OTHER_UUID)
    jsonl = Path(f"/x/{_LIVE_UUID}.jsonl")
    assert check_session_coherence(jsonl, "session_id_direct") is None


def test_coherence_live_env_unset_unverifiable(monkeypatch):
    """No per-process live signal → unverifiable → None (no false alarm)."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    jsonl = Path(f"/x/{_LIVE_UUID}.jsonl")
    assert check_session_coherence(jsonl, "find_jsonl") is None


def test_coherence_mismatch_warns(monkeypatch):
    """live env set + stem != live (fallback path) → warning emitted."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _LIVE_UUID)
    jsonl = Path(f"/x/{_OTHER_UUID}.jsonl")
    warn = check_session_coherence(jsonl, "find_jsonl")
    assert warn is not None and "cross-session" in warn
    assert _OTHER_UUID in warn and _LIVE_UUID in warn


def test_coherence_explicit_path_also_checked(monkeypatch):
    """H-1: --jsonl explicit path is also checked (highest-value once live trusted)."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _LIVE_UUID)
    jsonl = Path(f"/x/{_OTHER_UUID}.jsonl")
    assert check_session_coherence(jsonl, "explicit") is not None


def test_coherence_match_no_warning(monkeypatch):
    """stem == live → coherent → None."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _LIVE_UUID)
    jsonl = Path(f"/x/{_LIVE_UUID}.jsonl")
    assert check_session_coherence(jsonl, "find_jsonl") is None


def test_coherence_non_uuid_stem_skipped(monkeypatch):
    """Non-UUID stem (e.g. track1 temp file) → cannot compare → None (no noise)."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _LIVE_UUID)
    jsonl = Path("/x/tmphv5km54w.jsonl")
    assert check_session_coherence(jsonl, "track1") is None


def test_coherence_invalid_live_uuid_skipped(monkeypatch):
    """Live env present but not a valid UUID → unverifiable → None."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "not-a-uuid")
    jsonl = Path(f"/x/{_LIVE_UUID}.jsonl")
    assert check_session_coherence(jsonl, "find_jsonl") is None


def test_coherence_C1_lock_never_reads_session_hint(monkeypatch):
    """CSR #971 C-1 regression lock: even with env unset (the only path where
    .session-hint would be reached), the function must NOT consult extract_session_id()
    / the shared per-cwd .session-hint (the #965 contamination vector). Proven by
    making extract_session_id raise — the function must still return None without error."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    def _boom(*a, **k):
        raise AssertionError("check_session_coherence must NOT call extract_session_id (C-1)")

    monkeypatch.setattr(_mod, "extract_session_id", _boom)
    jsonl = Path(f"/x/{_LIVE_UUID}.jsonl")
    assert check_session_coherence(jsonl, "find_jsonl") is None  # no exception = C-1 held


# ── CSR #1061: _emit_coherence_mismatch_audit (sparse audit side-channel) ─────


def _patch_subprocess_capture(monkeypatch):
    """Capture subprocess.run calls (cmd, input=) into a list; return the list."""
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "input": kwargs.get("input")})

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(_mod.subprocess, "run", _fake_run)
    return calls


def test_audit_emitted_on_mismatch_with_valid_payload(monkeypatch):
    """CSR #1061 HIGH-1 (Claude Web DA): mismatch → exactly 1 emit AND the captured
    payload round-trips to valid JSON with required fields. Locks the well-formed-payload
    contract so a future refactor breaking json.dumps fails HERE instead of silently
    emitting 0 rows (the fail-open + no-check silent-regression class)."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _LIVE_UUID)
    calls = _patch_subprocess_capture(monkeypatch)
    jsonl = Path(f"/x/{_OTHER_UUID}.jsonl")
    warn = check_session_coherence(jsonl, "find_jsonl")
    assert warn is not None  # diagnostic behavior unchanged
    assert len(calls) == 1  # sparse: exactly one emit on mismatch
    payload = json.loads(calls[0]["input"])  # round-trip: must be valid JSON
    assert payload["event"] == "session_coherence_mismatch"
    assert payload["producer"] == "session-review.py"
    assert payload["schema_version"] == "1"
    assert payload["stem"] == _OTHER_UUID
    assert payload["live"] == _LIVE_UUID
    assert payload["jsonl_source"] == "find_jsonl"
    assert payload["ts"].endswith("Z")  # iso8601 UTC


def test_audit_not_emitted_on_any_none_path(monkeypatch):
    """CSR #1061 L2: all 4 None-returning paths emit 0 audit events — sparse contract
    locked on EVERY branch (session_id_direct / unverifiable / non-UUID stem / coherent),
    not just 'coherent'."""
    calls = _patch_subprocess_capture(monkeypatch)
    # 1. session_id_direct (early return None even if env differs)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _OTHER_UUID)
    assert check_session_coherence(Path(f"/x/{_LIVE_UUID}.jsonl"), "session_id_direct") is None
    # 2. unverifiable: live env unset
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    assert check_session_coherence(Path(f"/x/{_LIVE_UUID}.jsonl"), "find_jsonl") is None
    # 3. non-UUID stem (track1 temp)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _LIVE_UUID)
    assert check_session_coherence(Path("/x/tmphv5km54w.jsonl"), "track1") is None
    # 4. coherent: stem == live
    assert check_session_coherence(Path(f"/x/{_LIVE_UUID}.jsonl"), "find_jsonl") is None
    assert len(calls) == 0  # zero emit on any None path


def test_audit_failure_is_fail_open(monkeypatch):
    """CSR #1061 HIGH-1/ChatGPT DA: a subprocess failure (timeout/OSError/non-zero) must
    NOT raise and must NOT change the diagnostic's return — fail-open best-effort policy
    (exit/return contract unchanged regardless of audit-path outcome, LOW-2)."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _LIVE_UUID)

    def _boom_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="append-audit-event.sh", timeout=2)

    monkeypatch.setattr(_mod.subprocess, "run", _boom_run)
    jsonl = Path(f"/x/{_OTHER_UUID}.jsonl")
    warn = check_session_coherence(jsonl, "find_jsonl")  # must not raise
    assert warn is not None and "cross-session" in warn  # return contract intact


def test_audit_emit_helper_swallows_oserror(monkeypatch):
    """CSR #1061: _emit_coherence_mismatch_audit must be fail-open against OSError
    (e.g. helper not found / not executable) — returns None, never raises."""

    def _boom_run(*a, **k):
        raise OSError("helper not found")

    monkeypatch.setattr(_mod.subprocess, "run", _boom_run)
    # direct call — must not raise
    assert _mod._emit_coherence_mismatch_audit("a", "b", "find_jsonl") is None
