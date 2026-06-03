"""CSR #1030 — handoff-verify structured subagent-signal detection.

Validated via the mandated workflow: external research (Anthropic subagents doc — Task->Agent
rename v2.1.63, detect by tool_use name "Agent"/"Task"; local measurement 541 Agent / 0 Task) ->
da-chain Tier 2 3-AI (Gemini -> Claude Web -> ChatGPT, all Conditional Y, 0 CRITICAL) -> user HIL.

Design: a STRUCTURED-signal channel orthogonal to text session_signals. jsonl_analyzer full-scans
(uncapped, isSidechain:true excluded) for tool_use name in {Agent,Task}; build_hard_gate_candidates
dispatches gate.structured_signals through STRUCTURED_SIGNAL_HANDLERS, marks handoff-verify
"triggered" when a subagent ran, captures distinct subagent_type for transparency, warns on unknown
signals (no silent gate disable), and exposes subagent_count for audit.

Covers DA conditions: Agent detection, Task compat (H1 dual-name), FP=0 on no-subagent session,
isSidechain:true exclusion (Claude Web H1), uncapped recent-subagent (Gemini Q2/Claude M3),
unknown-signal warning (ChatGPT M-1), triggered + tier=="B"-via-SSOT integration (Claude Web H2).
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

sys.path.insert(0, str(_SCRIPTS))
from jsonl_analyzer import analyze_session_signals, _extract_subagent_invocations  # noqa: E402

HV = "handoff-verify"


def _gate(results, skill):
    return next((r for r in results if r["skill"] == skill), None)


def _assistant_agent_line(subagent_type="general-purpose", is_sidechain=False):
    return json.dumps({
        "type": "assistant",
        "isSidechain": is_sidechain,
        "message": {"content": [
            {"type": "tool_use", "name": "Agent",
             "input": {"description": "x", "subagent_type": subagent_type, "prompt": "y"}}
        ]},
    })


def _assistant_task_line(subagent_type="general-purpose"):
    return json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Task",
             "input": {"description": "x", "subagent_type": subagent_type, "prompt": "y"}}
        ]},
    })


def _plain_assistant_line():
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/a"}}]},
    })


def _write(tmp_path, lines):
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---- jsonl_analyzer extraction ----

def test_agent_invocation_detected(tmp_path):
    p = _write(tmp_path, [_plain_assistant_line(), _assistant_agent_line("Plan")])
    sig = analyze_session_signals(p)
    invs = sig["subagent_invocations"]
    assert sig["stats"]["total_subagent_invocations"] == 1
    assert invs[0]["subagent_type"] == "Plan"
    assert invs[0]["line_index"] == 1  # absolute line index


def test_task_name_compat_detected(tmp_path):
    """H1 dual-name: pre-v2.1.63 'Task' must still be detected."""
    p = _write(tmp_path, [_assistant_task_line("general-purpose")])
    sig = analyze_session_signals(p)
    assert sig["stats"]["total_subagent_invocations"] == 1
    assert sig["subagent_invocations"][0]["subagent_type"] == "general-purpose"


def test_no_subagent_false_positive_zero(tmp_path):
    """CSR DoD: Task-unused session -> FP 0."""
    p = _write(tmp_path, [_plain_assistant_line(), _plain_assistant_line()])
    sig = analyze_session_signals(p)
    assert sig["stats"]["total_subagent_invocations"] == 0
    assert sig["subagent_invocations"] == []


def test_sidechain_excluded(tmp_path):
    """Claude Web H1: isSidechain:true (subagent's own context) excluded from count."""
    p = _write(tmp_path, [
        _assistant_agent_line("general-purpose", is_sidechain=False),
        _assistant_agent_line("nested", is_sidechain=True),
    ])
    sig = analyze_session_signals(p)
    assert sig["stats"]["total_subagent_invocations"] == 1
    assert sig["subagent_invocations"][0]["subagent_type"] == "general-purpose"


def test_subagent_uncapped_beyond_max_events(tmp_path):
    """Gemini Q2 / Claude M3: a subagent AFTER max_events must NOT be silently missed."""
    lines = [_plain_assistant_line() for _ in range(250)] + [_assistant_agent_line("general-purpose")]
    p = _write(tmp_path, lines)
    # error/correction analysis is capped at max_events=200; subagent scan must be uncapped.
    sig = analyze_session_signals(p, max_events=200)
    assert sig["stats"]["total_subagent_invocations"] == 1
    assert sig["subagent_invocations"][0]["line_index"] == 250


def test_extract_helper_skips_blank_and_malformed(tmp_path):
    lines = ["", "not json", _assistant_agent_line("general-purpose"), "  "]
    invs = _extract_subagent_invocations(lines)
    assert len(invs) == 1
    assert invs[0]["line_index"] == 2


# ---- build_hard_gate_candidates dispatch ----

def test_handoff_verify_triggered_on_subagent():
    invs = [{"subagent_type": "general-purpose", "line_index": 5},
            {"subagent_type": "Plan", "line_index": 9}]
    results, warnings = build_hard_gate_candidates(
        edits=[], slash_commands=[], error_signals=[], session_id="sid",
        subagent_invocations=invs,
    )
    hv = _gate(results, HV)
    assert hv is not None
    assert hv["detected"] == "triggered"
    # distinct subagent_type captured for transparency (deduped)
    assert "subagent:general-purpose" in hv["triggered_by"]
    assert "subagent:Plan" in hv["triggered_by"]
    assert hv["subagent_count"] == 2
    # H2: tier resolves to B via SSOT (~/.claude/hard-gates.json), not data/hard-gates.json
    assert hv["tier"] == "B"


def test_handoff_verify_miss_without_subagent():
    results, _ = build_hard_gate_candidates(
        edits=[], slash_commands=[], error_signals=[], session_id="sid",
        subagent_invocations=[],
    )
    hv = _gate(results, HV)
    assert hv["detected"] == "miss"
    assert hv["subagent_count"] == 0


def test_backward_compat_no_subagent_arg():
    """Omitting subagent_invocations must not break (None default)."""
    results, _ = build_hard_gate_candidates(
        edits=[], slash_commands=[], error_signals=[], session_id="sid",
    )
    hv = _gate(results, HV)
    assert hv["detected"] == "miss"
    assert hv["subagent_count"] == 0


def test_unknown_structured_signal_warns(monkeypatch):
    """ChatGPT M-1: a declared signal with no handler warns (no silent gate disable)."""
    gates = [{"skill": "phantom-gate", "structured_signals": ["does_not_exist"]}]
    monkeypatch.setattr(_mod, "load_hard_gates", lambda: (gates, []))
    results, warnings = build_hard_gate_candidates(
        edits=[], slash_commands=[], error_signals=[], session_id="sid",
        subagent_invocations=[{"subagent_type": "x", "line_index": 1}],
    )
    assert any("unknown structured_signal 'does_not_exist'" in w for w in warnings)
    # gate present but not triggered by the unknown signal
    assert _gate(results, "phantom-gate")["detected"] == "miss"
