"""CSR #1039 — completion-context structured signal for verification-before-completion.

Validated via the mandated workflow: external research (OTel/Sentry/ECS — route by producer-attached
structured field, not body substring; combine signals with AND in one predicate) -> da-chain Tier 2
3-AI (Gemini -> Claude Web -> ChatGPT, all Conditional Y, 0 CRITICAL) -> user HIL.

Design (B+C): the verification gate's failure-OUTCOME triggers (error: labels) only count when a
PRODUCER-ATTACHED completion-context signal is present. The signal is read from
hard-gate-audit.jsonl (the hook `completion-claim-detector.sh` emits completion-claim events with a
session_id) — NOT from assistant response text (so CSR #1027's substring FP is not reintroduced).

DA-driven design points covered here:
- Claude Web H1: completion_context handler is PURE ADDITIVE (#1030 dispatch contract preserved);
  the strip lives in a separate post-pass _apply_completion_context_gate.
- Claude Web H2 / ChatGPT H2: completion_context_state is a 4-value enum (present/absent/
  audit_missing/audit_unreadable), and suppressed_signals records the stripped error: labels.
- Claude Web M3: per-line parse guard — a torn/malformed line is skipped, not fatal.
- ChatGPT M3: COMPLETION_CLAIM_EVENTS is a pinned taxonomy constant (producer/consumer sync).
- M2 residual: session-level granularity (an unrelated completion claim in the same SID lets a
  debugging failure fire) — pinned as a KNOWN residual, not a regression.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("session_review", _SCRIPTS / "session-review.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["session_review"] = _mod

build_hard_gate_candidates = _mod.build_hard_gate_candidates
_detect_completion_context = _mod._detect_completion_context
_detect_completion_context_state = _mod._detect_completion_context_state
_apply_completion_context_gate = _mod._apply_completion_context_gate
COMPLETION_CLAIM_EVENTS = _mod.COMPLETION_CLAIM_EVENTS

VBC = "verification-before-completion"


def _gate(results, skill):
    return next((r for r in results if r["skill"] == skill), None)


def _failure_error_signal():
    """A verification-before-completion failure-OUTCOME error_signal (matches an error: token)."""
    return [{
        "skill": VBC,
        "source": "error_signal",
        "signal": "test failure (completion-time)",
        "evidence_count": 1,
        "confidence": "medium",
        "snippet": "FAILED /proj/tests/test_foo.py::test_bar - AssertionError: boom",
    }]


def _write_audit(tmp_path, lines):
    """Create ~/.claude/da-tools/hard-gate-audit.jsonl under a fake home (tmp_path)."""
    d = tmp_path / ".claude" / "da-tools"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "hard-gate-audit.jsonl"
    p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return p


def _fake_home(monkeypatch, tmp_path):
    monkeypatch.setattr(_mod.Path, "home", staticmethod(lambda: tmp_path))


# ---- taxonomy pin (ChatGPT M3) ----

def test_completion_claim_events_pinned():
    """Producer/consumer sync guard: the known hook event names must stay recognized.
    If the hook (completion-claim-detector.sh) adds a new completion event, update this set."""
    expected = {
        "completion_claim_detected",
        "completion_coverage_gap",
        "completion_claim_skipped_evidence_present",
        "completion_coverage_gap_unclassified_no_marker",
        "completion_claim_coverage_satisfied",
        "completion_claim_blocked",
        "completion_claim_detected_skip_override",
        "completion_claim_coverage_satisfied_unclassified_minmarker",
    }
    assert set(COMPLETION_CLAIM_EVENTS) == expected


# ---- DoD #3 / #2 via build_hard_gate_candidates ----

def test_dod3_pure_debugging_failure_does_not_fire():
    """DoD #3: a test-failure OUTCOME with NO completion context must NOT fire the gate."""
    results, _ = build_hard_gate_candidates(
        [], [], _failure_error_signal(), session_id="sid", completion_context_state="absent",
    )
    g = _gate(results, VBC)
    assert g is not None
    assert g["detected"] == "miss", g
    assert g["completion_context_state"] == "absent"
    # observability (H2): the stripped error: outcome label is recorded, not silently dropped
    assert any(t.startswith("error:") for t in g["suppressed_signals"]), g


def test_dod2_completion_context_failure_still_fires():
    """DoD #2: a test-failure OUTCOME WITH completion context still fires, with transparency label."""
    results, _ = build_hard_gate_candidates(
        [], [], _failure_error_signal(), session_id="sid", completion_context_state="present",
    )
    g = _gate(results, VBC)
    assert g is not None
    assert g["detected"] == "triggered", g
    assert "completion_context" in g["triggered_by"], g
    assert g["suppressed_signals"] == []


def test_no_1027_regression_completion_state_does_not_match_text():
    """The completion signal comes from the audit log, never from edited file paths / response text.
    A 'done'/'complete' substring path with no completion context must still be 'miss'."""
    for p in ["/proj/done_list.txt", "/proj/ui/autocomplete.tsx"]:
        results, _ = build_hard_gate_candidates(
            [{"file": p, "tool": "Edit"}], [], [], session_id="sid", completion_context_state="absent",
        )
        g = _gate(results, VBC)
        assert g is not None and g["detected"] == "miss", f"FP on {p}: {g}"


# ---- #1030 dispatch contract (Claude Web H1): handler is pure additive ----

def test_handler_is_pure_additive():
    assert _detect_completion_context({"completion_context_present": True}) == ["completion_context"]
    assert _detect_completion_context({"completion_context_present": False}) == []
    assert _detect_completion_context({}) == []


def test_apply_gate_is_pure_no_mutation():
    """Post-pass returns NEW lists (immutability)."""
    gate = {"require_completion_context": True}
    original = ["error:AssertionError", "file:test_foo.py"]
    kept, suppressed = _apply_completion_context_gate(original, gate, completion_context_present=False)
    assert original == ["error:AssertionError", "file:test_foo.py"]  # unchanged
    assert kept == ["file:test_foo.py"]            # error: stripped, file: kept (surgical)
    assert suppressed == ["error:AssertionError"]


def test_bare_completion_context_is_not_an_independent_trigger():
    """REGRESSION (deep-verify): completion_context is a transparency companion, NOT a standalone
    trigger. A completion claim with NO test signal (no error:, no file:) must NOT fire the gate —
    otherwise virtually every completion-claiming session would flag verification (precision
    regression, outside the #1039 DoD failure-OUTCOME scope)."""
    results, _ = build_hard_gate_candidates(
        [], [], [], session_id="sid", completion_context_state="present",
    )
    g = _gate(results, VBC)
    assert g is not None
    assert g["detected"] == "miss", g
    assert "completion_context" not in g["triggered_by"], g


def test_completion_context_kept_as_companion_to_file_trigger():
    """A real trigger (file: test-file edit) + completion present → fires, and completion_context
    rides along as transparency."""
    results, _ = build_hard_gate_candidates(
        [{"file": "/proj/tests/conftest.py", "tool": "Edit"}], [], [],
        session_id="sid", completion_context_state="present",
    )
    g = _gate(results, VBC)
    assert g is not None and g["detected"] == "triggered", g


def test_apply_gate_drops_sole_completion_label(monkeypatch):
    """Unit: post-pass drops a bare completion_context label (sole) but keeps it as a companion."""
    gate = {"require_completion_context": True}
    sole, _ = _apply_completion_context_gate(["completion_context"], gate, True)
    assert sole == []  # sole completion_context → not a trigger
    companion, _ = _apply_completion_context_gate(
        ["error:AssertionError", "completion_context"], gate, True)
    assert companion == ["error:AssertionError", "completion_context"]  # companion retained


def test_apply_gate_noop_without_require_field():
    """Gates without require_completion_context are unaffected (backward-compat)."""
    kept, suppressed = _apply_completion_context_gate(
        ["error:x"], {"skill": "systematic-debugging"}, completion_context_present=False
    )
    assert kept == ["error:x"] and suppressed == []


def test_backward_compat_other_gate_unaffected():
    """systematic-debugging (no require_completion_context) still fires on error with NO completion
    context and with the new arg defaulted."""
    err = [{
        "skill": "systematic-debugging", "source": "error_signal", "signal": "x",
        "evidence_count": 1, "confidence": "medium",
        "snippet": "E   AssertionError: 1 == 2\n2 failed",
    }]
    results, _ = build_hard_gate_candidates([], [], err, session_id="sid")  # no completion arg
    g = _gate(results, "systematic-debugging")
    assert g is not None and g["detected"] == "triggered", g


# ---- _detect_completion_context_state (data source B) ----

def test_state_present_from_audit(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _write_audit(tmp_path, [
        json.dumps({"session_id": "other", "event": "completion_claim_detected"}),
        json.dumps({"session_id": "sid", "event": "completion_coverage_gap"}),
    ])
    assert _detect_completion_context_state("sid") == "present"


def test_state_absent_no_match(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _write_audit(tmp_path, [json.dumps({"session_id": "sid", "event": "some_other_event"})])
    assert _detect_completion_context_state("sid") == "absent"


def test_state_sid_filter_other_sid_ignored(monkeypatch, tmp_path):
    """A completion event for a DIFFERENT session must not count."""
    _fake_home(monkeypatch, tmp_path)
    _write_audit(tmp_path, [json.dumps({"session_id": "other", "event": "completion_claim_detected"})])
    assert _detect_completion_context_state("sid") == "absent"


def test_state_audit_missing(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)  # no audit file written
    assert _detect_completion_context_state("sid") == "audit_missing"


def test_state_audit_unreadable(monkeypatch, tmp_path):
    """A path that is a directory (not a file) -> OSError on open -> audit_unreadable."""
    _fake_home(monkeypatch, tmp_path)
    d = tmp_path / ".claude" / "da-tools" / "hard-gate-audit.jsonl"
    d.mkdir(parents=True)  # make the audit "file" a directory
    assert _detect_completion_context_state("sid") == "audit_unreadable"


def test_state_none_sid_is_absent():
    assert _detect_completion_context_state(None) == "absent"


def test_m3_torn_line_skipped_then_match(monkeypatch, tmp_path):
    """Claude Web M3: a malformed/torn line BEFORE a valid matching line must be skipped, not fatal."""
    _fake_home(monkeypatch, tmp_path)
    _write_audit(tmp_path, [
        '{"session_id": "sid", "event": "completion_claim_detec',  # torn line
        "",  # blank
        json.dumps({"session_id": "sid", "event": "completion_claim_detected"}),
    ])
    assert _detect_completion_context_state("sid") == "present"


# ---- end-to-end fail-toward-absent (M1) ----

def test_m1_audit_missing_strips_outcome(monkeypatch, tmp_path):
    """M1: when the audit log is missing (hook disabled/never ran), the state is non-present, so a
    failure OUTCOME is stripped (fail-toward-absent: prefer FN over a false alarm)."""
    _fake_home(monkeypatch, tmp_path)
    state = _detect_completion_context_state("sid")
    assert state == "audit_missing"
    results, _ = build_hard_gate_candidates(
        [], [], _failure_error_signal(), session_id="sid", completion_context_state=state,
    )
    g = _gate(results, VBC)
    assert g is not None and g["detected"] == "miss", g
    assert g["completion_context_state"] == "audit_missing"


# ---- M2 known residual (session-level granularity) ----

def test_m2_session_granularity_residual_documented():
    """KNOWN RESIDUAL (da-chain Claude Web M2 / ChatGPT H1): the signal is session-level, not
    temporally adjacent to the failure. A session that has ANY completion claim (even unrelated to
    the debugging failure) makes the failure OUTCOME fire. This is the documented #38-style coarse
    granularity; DoD #3 is met only at session granularity. Pinned so the limitation is explicit and
    a future temporal-window refinement has a regression anchor."""
    # completion_context_state="present" models "a completion was claimed somewhere this session".
    results, _ = build_hard_gate_candidates(
        [], [], _failure_error_signal(), session_id="sid", completion_context_state="present",
    )
    g = _gate(results, VBC)
    # By design this FIRES even if the completion claim was unrelated to the failure (residual).
    assert g is not None and g["detected"] == "triggered", g
