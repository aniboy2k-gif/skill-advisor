"""CSR #1027 regression — mechanism-aligned session_signals for verification-before-completion.

Validated via the mandated workflow (external research → design → da-chain 4-AI → user HIL).
Design v2 (post-DA): add ONLY live file-path-aligned tokens (conftest, /tests/, _test., .spec.,
.test.) to verification-before-completion.

CSR #1029 update: the error-snippet matching branch in build_hard_gate_candidates is now LIVE —
signal_to_skill.py propagates the matched error snippet text into the error_signal record
(`snippet` key, single canonical string per the G-Ex Sentry-style fingerprint grouping design).
test_error_snippet_branch_is_now_live (was *_is_dead_documented) pins that revival, and the
end-to-end test confirms map_signals_to_skills emits records carrying the snippet.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "session_review",
    Path(__file__).parent.parent / "session-review.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["session_review"] = _mod

build_hard_gate_candidates = _mod.build_hard_gate_candidates

sys.path.insert(0, str(Path(__file__).parent.parent))
from signal_to_skill import map_signals_to_skills  # noqa: E402


def _gate(results, skill):
    return next((r for r in results if r["skill"] == skill), None)


def test_verification_triggers_on_test_file_edit():
    """Editing a conftest.py / *.spec.* file flips verification-before-completion to 'triggered'."""
    edits = [
        {"file": "/proj/tests/conftest.py", "tool": "Edit"},
        {"file": "/proj/ui/button.spec.ts", "tool": "Write"},
    ]
    results, _ = build_hard_gate_candidates(edits, [], [], session_id=None)
    g = _gate(results, "verification-before-completion")
    assert g is not None
    assert g["detected"] == "triggered", g
    assert any(t.startswith("file:") for t in g["triggered_by"]), g


def test_no_false_trigger_on_docs_only_session():
    """A docs-only / unrelated edit session must NOT trigger verification-before-completion
    (false-positive ceiling)."""
    edits = [
        {"file": "/proj/docs/guide.md", "tool": "Edit"},
        {"file": "/proj/README.rst", "tool": "Write"},
    ]
    results, _ = build_hard_gate_candidates(edits, [], [], session_id=None)
    g = _gate(results, "verification-before-completion")
    assert g is not None
    assert g["detected"] == "miss", g


def test_removed_response_text_tokens_no_false_positive():
    """CSR #1027 follow-up: the noisy response-text tokens (완료/done/finished/complete/구현 완료)
    were REMOVED because session_signals match file paths + error snippets (not response text),
    so they only produced false positives via substring (e.g. 'complete' in 'autocomplete').
    These realistic paths must now report 'miss' (da-chain Gemini MEDIUM / ChatGPT LOW)."""
    fp_paths = [
        "/proj/src/complete_handler.py",   # 'complete' substring (was FP)
        "/proj/incomplete.md",             # 'complete' in 'incomplete' (was FP)
        "/proj/ui/autocomplete.tsx",       # 'complete' in 'autocomplete' (was FP)
        "/proj/done_list.txt",             # 'done' substring (was FP)
    ]
    for p in fp_paths:
        results, _ = build_hard_gate_candidates([{"file": p, "tool": "Edit"}], [], [], session_id=None)
        g = _gate(results, "verification-before-completion")
        assert g is not None
        assert g["detected"] == "miss", f"false positive on {p}: {g}"


def test_pytest_token_not_added_avoids_cross_gate_collision():
    """Regression for da-chain MEDIUM-1: `pytest` was intentionally NOT added to
    verification-before-completion (it already belongs to systematic-debugging). Editing a bare
    pytest.ini must NOT flip verification-before-completion (no `pytest`/`.ini` token there)."""
    edits = [{"file": "/proj/pytest.ini", "tool": "Edit"}]
    results, _ = build_hard_gate_candidates(edits, [], [], session_id=None)
    g = _gate(results, "verification-before-completion")
    assert g is not None
    assert g["detected"] == "miss", g


def test_error_snippet_branch_is_now_live():
    """CSR #1029 (was *_is_dead_documented): the error_signal record now carries a `snippet` key,
    so the error-snippet matching branch fires. A snippet bearing systematic-debugging's
    session_signal tokens flips that gate to 'triggered' with an `error:` provenance label."""
    error_signals = [{
        "skill": "systematic-debugging",
        "source": "error_signal",
        "signal": "test failure pattern",
        "evidence_count": 3,
        "confidence": "high",
        "snippet": "Traceback (most recent call last)\nAssertionError: boom",
    }]
    results, _ = build_hard_gate_candidates([], [], error_signals, session_id=None)
    g = _gate(results, "systematic-debugging")
    assert g is not None
    assert g["detected"] == "triggered", g
    assert any(t.startswith("error:") for t in g["triggered_by"]), g


def test_systematic_debugging_error_tokens_revived():
    """CSR #1029: systematic-debugging's error tokens (traceback/AssertionError/failed) match
    the propagated snippet — previously 0 fires (dead branch)."""
    error_signals = [{
        "skill": "systematic-debugging",
        "source": "error_signal",
        "signal": "test failure pattern",
        "evidence_count": 1,
        "confidence": "medium",
        "snippet": "E   AssertionError: 1 == 2\n2 failed in 0.3s",
    }]
    results, _ = build_hard_gate_candidates([], [], error_signals, session_id=None)
    g = _gate(results, "systematic-debugging")
    assert g is not None
    assert g["detected"] == "triggered", g
    labels = [t for t in g["triggered_by"] if t.startswith("error:")]
    assert labels, g


def test_verification_triggers_on_test_failure_session_functional():
    """CSR #1029 criterion #2, re-pinned at the FUNCTIONAL level by CSR #1037.

    SUPERSEDES test_verification_triggers_on_test_path_in_error_snippet (which asserted the
    `error:/tests/` MECHANISM). The CONTRACT preserved: a test-failure session (runs only, NO
    edits) still flips verification-before-completion to 'triggered'. The MECHANISM changed: it now
    fires on a failure-OUTCOME token from verification's OWN dedicated mapping (CSR #1037 Option
    1S), NOT on the `/tests/` path token borrowed from systematic-debugging's snippet. This test
    asserts the OUTCOME (gate triggered) independent of the internal triggered_by label format, so
    it stays green even if the error_signal schema evolves."""
    error_signals = [{
        "skill": "verification-before-completion",
        "source": "error_signal",
        "signal": "test failure (completion-time)",
        "evidence_count": 1,
        "confidence": "medium",
        "snippet": "FAILED /proj/tests/test_foo.py::test_bar - AssertionError",
    }]
    results, _ = build_hard_gate_candidates([], [], error_signals, session_id=None)
    g = _gate(results, "verification-before-completion")
    assert g is not None
    assert g["detected"] == "triggered", g  # functional contract, mechanism-agnostic
    # and it must NOT be the superseded /tests/ path mechanism
    assert not any(t == "error:/tests/" for t in g["triggered_by"]), g


def test_error_snippet_false_positive_ceiling():
    """CSR #1029 검증기준 #4: records WITHOUT a snippet (legacy shape) and records with an
    unrelated snippet must NOT trigger — the live branch keeps its false-positive ceiling."""
    # (a) legacy record without snippet key → empty string → no match
    legacy = [{
        "skill": "systematic-debugging",
        "source": "error_signal",
        "signal": "x",
        "evidence_count": 1,
        "confidence": "low",
    }]
    results, _ = build_hard_gate_candidates([], [], legacy, session_id=None)
    g = _gate(results, "systematic-debugging")
    assert g is not None and g["detected"] == "miss", g

    # (b) unrelated snippet — none of the session_signal tokens present
    unrelated = [{
        "skill": "systematic-debugging",
        "source": "error_signal",
        "signal": "x",
        "evidence_count": 1,
        "confidence": "low",
        "snippet": "build completed in 3s; cache warm",
    }]
    results, _ = build_hard_gate_candidates([], [], unrelated, session_id=None)
    g = _gate(results, "systematic-debugging")
    assert g is not None and g["detected"] == "miss", g
    gv = _gate(results, "verification-before-completion")
    assert gv is not None and gv["detected"] == "miss", gv


def test_map_signals_propagates_snippet_end_to_end():
    """CSR #1029 root: map_signals_to_skills must emit an error_signal record carrying the
    matched snippet text (so downstream build_hard_gate_candidates can match it)."""
    signals = {
        "errors": [{"error_snippet": "AssertionError: boom in test_foo", "line_index": 5}],
        "corrections": [],
    }
    recs = map_signals_to_skills(signals, edits=[])
    err = next((r for r in recs if r.get("source") == "error_signal"
                and r.get("skill") == "systematic-debugging"), None)
    assert err is not None, recs
    assert err.get("snippet"), f"snippet must be propagated, got: {err}"
    assert "AssertionError" in err["snippet"], err


def test_map_signals_merges_snippets_across_mappings():
    """CSR #1029 da-chain M-1: systematic-debugging is produced by 3 distinct error mappings
    (test-failure / permission / file-not-found). Two errors hitting different mappings must merge
    both snippets into ONE record (value-deduped, capped) — this exercises the _upsert snippet-merge
    branch end-to-end, the only new control flow otherwise covered by reading alone."""
    signals = {
        "errors": [
            {"error_snippet": "AssertionError: 1 == 2", "line_index": 1},
            {"error_snippet": "PermissionError: [Errno 13] Permission denied: /x", "line_index": 2},
        ],
        "corrections": [],
    }
    recs = map_signals_to_skills(signals, edits=[])
    err = next((r for r in recs if r.get("source") == "error_signal"
                and r.get("skill") == "systematic-debugging"), None)
    assert err is not None, recs
    snip = err.get("snippet", "")
    assert "AssertionError" in snip and "PermissionError" in snip, f"both snippets must merge: {err}"
    # value-dedup: each distinct snippet appears once
    assert snip.count("AssertionError: 1 == 2") == 1, snip
