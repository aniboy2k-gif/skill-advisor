"""CSR #1037 — verification-before-completion dedicated error mapping (Option 1S-final).

Validated via the mandated workflow: external research (Sentry/OTel/ECS — producer-attached
structured-field routing) -> da-chain Tier 1 4-AI (Conditional Y, 0 CRITICAL) -> user HIL.

Design (Option 1S, surgical — NOT a global producer-scope rewrite):
- (1a) signal-skills.json: a dedicated `verification-before-completion` mapping keyed on test
  failure-OUTCOME tokens, so verification produces its OWN error_signal record.
- (1b-S) hard-gates.json: verification's FILE-PATH tokens (conftest, /tests/, _test., .spec.,
  .test.) get `signal_match_targets: file` (matched ONLY against edited file paths, never error
  text -> removes the /tests/-in-error-text FP); verification GAINS outcome tokens with
  `signal_match_targets: error` (matched ONLY against error snippets -> criterion #2 via failure
  OUTCOME, not path PRESENCE). Tokens without an entry default to "both" (backward-compatible;
  ALL OTHER gates unchanged).

HONEST COVERAGE: precision IMPROVEMENT (path-PRESENCE -> failure-OUTCOME), NOT a precision
SOLUTION. Outcome tokens do not fully separate completion-context from pure debugging; the
verification record's snippet is also matched by systematic-debugging (TRUE co-activation, NOT an
FP). True completion-context detection is deferred to a follow-up CSR (coherent with CSR #1030).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("session_review", _SCRIPTS / "session-review.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["session_review"] = _mod
build_hard_gate_candidates = _mod.build_hard_gate_candidates

sys.path.insert(0, str(_SCRIPTS))
from signal_to_skill import map_signals_to_skills  # noqa: E402
from hard_gate_parser import load_hard_gates  # noqa: E402

VERI = "verification-before-completion"


def _gate(results, skill):
    return next((r for r in results if r["skill"] == skill), None)


def _veri_err_record(snippet: str) -> list[dict]:
    """A verification error_signal record carrying `snippet` (as map_signals_to_skills emits)."""
    return [{
        "skill": VERI, "source": "error_signal", "signal": "test failure (completion-time)",
        "evidence_count": 1, "confidence": "medium", "snippet": snippet,
    }]


# ---- criterion #2: a test-FAILURE session triggers verification via its OWN outcome record ----
# Multi-runner recall (Claude Web H1 / ChatGPT H1: go/rspec/cargo/jest must not regress).

_RUNNER_FAILURES = {
    "pytest": "FAILED tests/test_foo.py::test_bar - AssertionError: assert 1 == 2\n===== 1 failed in 0.12s =====",
    "go": "--- FAIL: TestFoo (0.00s)\nFAIL\nexit status 1\nFAIL\tgithub.com/x/y\t0.002s",
    "rspec": "Failures:\n  1) Foo does bar\n     Failure/Error: expect(x).to eq(y)\n1 example, 1 failure",
    "cargo": "test tests::it_works ... FAILED\nfailures:\n    tests::it_works\ntest result: FAILED. 0 passed; 1 failed",
    "jest": "● Component › renders\n  expect(received).toBe(expected)\nTests: 1 failed, 1 passed",
}


def test_verification_triggers_on_each_runner_failure():
    """criterion #2 (recall): every mainstream runner's failure output flips verification to
    'triggered' via its OWN error record — NOT via a borrowed /tests/ path token."""
    for runner, snippet in _RUNNER_FAILURES.items():
        results, _ = build_hard_gate_candidates([], [], _veri_err_record(snippet), session_id=None)
        g = _gate(results, VERI)
        assert g is not None, runner
        assert g["detected"] == "triggered", f"{runner} did not trigger verification: {g}"
        assert any(t.startswith("error:") for t in g["triggered_by"]), f"{runner}: {g}"


# ---- criterion #3 + #4: non-test runtime failures must NOT inflate verification (FP budget) ----

_NEGATIVE_FAILURES = [
    "Connection failed: ECONNREFUSED 127.0.0.1:5432",
    "Error: deploy failed after 3 retries",
    "npm ERR! build failed with exit code 1",
    "fatal: authentication failed for 'https://...'",
]


def test_negative_runtime_failures_fp_budget():
    """criterion #4 (FP<=2): generic non-test runtime failures must not meaningfully activate
    verification (ChatGPT M-1 — measure, don't assert)."""
    fp = 0
    for snippet in _NEGATIVE_FAILURES:
        results, _ = build_hard_gate_candidates([], [], _veri_err_record(snippet), session_id=None)
        g = _gate(results, VERI)
        if g and g["detected"] == "triggered":
            fp += 1
    assert fp <= 2, f"verification FP budget exceeded on non-test failures: {fp} > 2"


def test_tests_path_in_error_text_no_longer_fires_without_failure():
    """The FP fix: an error snippet that merely embeds a /tests/ PATH but carries NO failure
    OUTCOME must NOT trigger verification (old behavior fired `error:/tests/`)."""
    snippet = "loaded /proj/tests/conftest.py; collected 0 items in 0.01s"
    results, _ = build_hard_gate_candidates([], [], _veri_err_record(snippet), session_id=None)
    g = _gate(results, VERI)
    assert g is not None
    assert g["detected"] == "miss", f"path-only snippet must not fire verification: {g}"
    assert not any(t == "error:/tests/" for t in g["triggered_by"]), g


# ---- L2: independence — fires when verification's is the ONLY error record present ----

def test_verification_independence_own_record_only():
    """L2: with the ONLY error_signal record being verification's, the gate triggers from its OWN
    record (not incidental on a foreign skill's snippet)."""
    results, _ = build_hard_gate_candidates(
        [], [], _veri_err_record("AssertionError: boom"), session_id=None)
    g = _gate(results, VERI)
    assert g is not None and g["detected"] == "triggered", g


# ---- M-2: reverse co-activation is a TRUE co-activation, not an FP ----

def test_co_activation_verification_and_systematic_is_true_positive():
    """M-2: verification's record snippet ('...AssertionError...') is also matched by
    systematic-debugging (default match_target). Both firing on a completion-time failure is a
    TRUE co-activation by the FP-budget definition (false activations only), NOT an FP."""
    err = [{
        "skill": VERI, "source": "error_signal", "signal": "x", "evidence_count": 1,
        "confidence": "medium", "snippet": "AssertionError: assert 1 == 2\n1 failed in 0.1s",
    }]
    results, _ = build_hard_gate_candidates([], [], err, session_id=None)
    gv = _gate(results, VERI)
    gs = _gate(results, "systematic-debugging")
    assert gv is not None and gv["detected"] == "triggered", gv
    assert gs is not None and gs["detected"] == "triggered", gs


# ---- 1c: file-edit path unchanged (editing a real test file still triggers verification) ----

def test_file_edit_path_unchanged():
    edits = [{"file": "/proj/tests/conftest.py", "tool": "Edit"}]
    results, _ = build_hard_gate_candidates(edits, [], [], session_id=None)
    g = _gate(results, VERI)
    assert g is not None and g["detected"] == "triggered", g
    assert any(t.startswith("file:") for t in g["triggered_by"]), g


def test_outcome_token_does_not_match_file_edit():
    """An outcome token (match_target=error) must NOT fire on a FILE named like the token
    (e.g. a file 'failures.py') — outcome tokens are error-only."""
    edits = [{"file": "/proj/src/failures.py", "tool": "Edit"}]
    results, _ = build_hard_gate_candidates(edits, [], [], session_id=None)
    g = _gate(results, VERI)
    assert g is not None and g["detected"] == "miss", g


# ---- 1a: map_signals_to_skills emits verification's OWN record on a failure session ----

def test_map_signals_emits_verification_record():
    signals = {
        "errors": [{"error_snippet": "AssertionError: assert 1 == 2 in test_foo", "line_index": 3}],
        "corrections": [],
    }
    recs = map_signals_to_skills(signals, edits=[])
    veri = next((r for r in recs if r.get("source") == "error_signal" and r.get("skill") == VERI), None)
    assert veri is not None, f"verification error_signal record must be emitted: {recs}"
    assert veri.get("snippet"), veri


# ---- H-2: parser version + signal_match_targets load behavior ----

def test_hard_gates_loads_with_match_targets():
    """The verification gate loads with a signal_match_targets sibling object; schema_version 1.1.
    Gates without the field keep pure list[str] session_signals (default 'both')."""
    gates, _ = load_hard_gates()
    g = next((x for x in gates if x.get("skill") == VERI), None)
    assert g is not None
    mt = g.get("signal_match_targets")
    assert isinstance(mt, dict) and mt, f"signal_match_targets must load: {g}"
    # file-path tokens declared file-only
    assert mt.get("/tests/") == "file", mt
    # session_signals stays a pure list of strings
    assert all(isinstance(s, str) for s in g.get("session_signals", [])), g


def test_signal_match_targets_only_reference_existing_tokens():
    """H-1 (scoped typo guard): every token in signal_match_targets must exist in that gate's
    session_signals — catches a misdeclared scope before it silently does nothing."""
    gates, _ = load_hard_gates()
    for g in gates:
        mt = g.get("signal_match_targets")
        if not mt:
            continue
        sigset = set(g.get("session_signals", []))
        unknown = [tok for tok in mt if tok not in sigset]
        assert not unknown, f"{g.get('skill')}: signal_match_targets references unknown tokens {unknown}"
