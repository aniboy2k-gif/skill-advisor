"""
CSR #1094 — Shared corrupt-line parity test for the two independent JSONL readers.

The two readers — jsonl_analyzer.analyze_session_signals (forward full-read, absolute
line_index) and session-review.extract_edits (reversed newest-first, tail-seek) — keep
their traversal/iteration logic DELIBERATELY SEPARATE. A shared low-level iterator/parse
primitive was evaluated and DECLINED via da-chain (Tier 2, 3-AI Conditional Y): the only
shareable surface is the json.loads line-parse idiom (drift-proof; rule-of-three not met
at 2 call sites; a dict|None return would collapse blank/malformed/non-object).

This test binds — at the TEST layer, without coupling implementations — the ONE invariant
both readers MUST honor: a malformed JSONL line is SKIPPED (not raised) and valid lines are
still processed. SCOPE NOTE: malformed-line skipping is the ONLY shared invariant asserted
here. Other parsing behavior (encoding fallback strict→replace vs replace, line-index
semantics, error accounting warn vs counter) is INTENTIONALLY divergent and not constrained.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from jsonl_analyzer import analyze_session_signals  # noqa: E402

# session-review.py has a hyphen → load via importlib (mirrors test_session_review.py)
_spec = importlib.util.spec_from_file_location("session_review", _SCRIPTS / "session-review.py")
_session_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_session_review)
sys.modules.setdefault("session_review", _session_review)
extract_edits = _session_review.extract_edits


# ── fixtures ────────────────────────────────────────────────────────────────

# A valid line that analyze_session_signals counts as a signal (is_error tool_result → errors)
_VALID_FOR_ANALYZE = json.dumps(
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x", "is_error": True, "content": "FAILED"}]}}
)
# A valid line that extract_edits counts as a signal (Write tool_use → edits)
_VALID_FOR_EXTRACT = json.dumps(
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "x", "name": "Write", "input": {"file_path": "/tmp/a.py"}}]}}
)
_MALFORMED = "{this is not valid json"


def _write(tmp_path: Path, lines: list[str]) -> Path:
    f = tmp_path / "session.jsonl"
    f.write_text("\n".join(lines), encoding="utf-8")
    return f


def test_fixture_malformed_line_truly_unparseable():
    """Guard: the malformed fixture must actually fail json.loads (else the test is vacuous)."""
    with pytest.raises(json.JSONDecodeError):
        json.loads(_MALFORMED)


# Reader adapters: each returns the number of detected signals; must NOT raise on malformed input.
def _run_analyze(path: Path) -> int:
    return analyze_session_signals(path)["stats"]["total_errors"]


def _run_extract(path: Path) -> int:
    _edits, stats = extract_edits(path)
    return stats["edits_found"]


_READERS = [
    pytest.param(_run_analyze, "analyze_session_signals", _VALID_FOR_ANALYZE, id="analyze"),
    pytest.param(_run_extract, "extract_edits", _VALID_FOR_EXTRACT, id="extract_edits"),
]


@pytest.mark.parametrize("reader, name, valid_line", _READERS)
def test_malformed_line_is_skipped_not_raised(reader, name, valid_line, tmp_path):
    """SHARED INVARIANT: a malformed JSONL line is skipped, not raised."""
    jsonl = _write(tmp_path, [valid_line, _MALFORMED, valid_line])
    # Must not raise. (If reader throws on the bad line, this fails the parity invariant.)
    reader(jsonl)


@pytest.mark.parametrize("reader, name, valid_line", _READERS)
def test_valid_lines_processed_despite_malformed(reader, name, valid_line, tmp_path):
    """SHARED INVARIANT: valid lines are still processed when a malformed line is interleaved."""
    jsonl = _write(tmp_path, [valid_line, _MALFORMED, valid_line])
    count = reader(jsonl)
    assert count >= 1, f"{name}: expected >=1 signal despite malformed line, got {count}"


@pytest.mark.parametrize("reader, name, valid_line", _READERS)
def test_all_malformed_returns_zero_without_raising(reader, name, valid_line, tmp_path):
    """SHARED INVARIANT: an all-malformed file yields no signals and does not raise."""
    jsonl = _write(tmp_path, [_MALFORMED, _MALFORMED, _MALFORMED])
    assert reader(jsonl) == 0
