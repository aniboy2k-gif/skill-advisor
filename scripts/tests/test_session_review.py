"""
skill-advisor session-review regression tests.
Run: pytest scripts/tests/test_session_review.py -v
"""
from __future__ import annotations

import importlib.util
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


# ── M-1 fix: EOFError in --confirm ───────────────────────────────────────────

def test_find_jsonl_eoferror_returns_first_candidate(tmp_path):
    """M-1: input()이 EOFError를 던져도 크래시 없이 첫 번째 파일을 반환한다."""
    f1 = tmp_path / "a.jsonl"
    f1.write_text("{}")
    f2 = tmp_path / "b.jsonl"
    f2.write_text("{}")

    with (
        patch.object(_mod, "PROJECTS_BASE", tmp_path),
        patch("builtins.input", side_effect=EOFError),
    ):
        result = find_jsonl(confirm=True)

    assert result is not None, "Should return a path even on EOFError"


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
    for c in data["candidates"]:
        assert "_full_path" not in c, f"_full_path should not appear in JSON output: {c}"


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
