"""CSR #1027 regression — mechanism-aligned session_signals for verification-before-completion.

Validated via the mandated workflow (external research → design → da-chain 4-AI → user HIL).
Design v2 (post-DA): add ONLY live file-path-aligned tokens (conftest, /tests/, _test., .spec.,
.test.) to verification-before-completion. The error-snippet matching branch in
build_hard_gate_candidates is DEAD (the error_signal record produced by signal_to_skill.py has no
`snippet` key — verified in da-chain CRITICAL-1), so error-snippet tokens were intentionally NOT
added. Test 3 documents that dead branch to prevent false confidence (root fix = future-work CSR).
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


def test_error_snippet_branch_is_dead_documented():
    """da-chain CRITICAL-1: the error_signal record has no `snippet` key, so the error-snippet
    matching branch never fires. This test pins that reality — if a future code change populates
    `snippet`, this test will flip and force a deliberate revisit. error_signals here mimic the
    real schema {skill, source, signal, evidence_count, confidence} (NO snippet)."""
    error_signals = [{
        "skill": "verification-before-completion",
        "source": "error_signal",
        "signal": "AssertionError",
        "evidence_count": 3,
        "confidence": "high",
    }]
    results, _ = build_hard_gate_candidates([], [], error_signals, session_id=None)
    g = _gate(results, "verification-before-completion")
    assert g is not None
    # No file edits + dead error branch => no error-derived trigger.
    assert g["detected"] == "miss", g
    assert not any(t.startswith("error:") for t in g["triggered_by"]), g
