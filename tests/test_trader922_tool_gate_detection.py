"""trader922-followup — tool-invoked Hard Gate detection (plan → EnterPlanMode/ExitPlanMode).

Fixes a false-negative where a gate satisfied via a TOOL (not a slash command) was
reported "miss". da-chain Tier 2 (Gemini→ChatGPT→Claude Web, all Conditional Y, CRITICAL 0).
Regression fixtures for every adopted condition:
  - tool-only → executed          (core fix)
  - slash-only → executed         (unchanged baseline)
  - both → detection_basis merges both channels
  - absent-field gate unaffected
  - isSidechain-only → NOT collected (Claude Web HIGH-1: Plan subagent must not flip parent)
  - tool_result echo → NOT matched (Claude Web MEDIUM: tool_use blocks only)
  - truncation → early tool still collected (Gemini/ChatGPT HIGH: decoupled from max_edits)
  - orphan map key → warning (Claude Web MEDIUM)
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

_scripts = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_scripts))
# session-review.py has a hyphen → load via importlib (not a valid import name).
_spec = importlib.util.spec_from_file_location("sr", _scripts / "session-review.py")
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)
build_hard_gate_candidates = sr.build_hard_gate_candidates
extract_edits = sr.extract_edits


def _write(entries):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for e in entries:
        f.write(json.dumps(e) + "\n")
    f.close()
    return Path(f.name)


def _tool_use(name, sidechain=False, input_=None):
    e = {"type": "assistant",
         "message": {"role": "assistant",
                     "content": [{"type": "tool_use", "name": name, "input": input_ or {}}]}}
    if sidechain:
        e["isSidechain"] = True
    return e


def _plan_gate(cands):
    return next((c for c in cands if c["skill"] == "plan"), None)


# ---- build_hard_gate_candidates: tool-evidence → executed ----
def test_tool_only_marks_plan_executed():
    cands, _ = build_hard_gate_candidates([], [], [], tool_names_seen={"ExitPlanMode"})
    g = _plan_gate(cands)
    assert g is not None and g["detected"] == "executed"
    assert "tool_use" in g["detection_basis"] and "ExitPlanMode" in g["detection_basis"]


def test_no_evidence_is_miss():
    cands, _ = build_hard_gate_candidates([], [], [], tool_names_seen=set())
    assert _plan_gate(cands)["detected"] == "miss"


def test_slash_only_still_executed():
    cands, _ = build_hard_gate_candidates([], ["/plan"], [], tool_names_seen=set())
    g = _plan_gate(cands)
    assert g["detected"] == "executed" and g["detection_basis"] == "slash_command_found"


def test_both_channels_merged_in_basis():
    cands, _ = build_hard_gate_candidates([], ["/plan"], [], tool_names_seen={"EnterPlanMode"})
    g = _plan_gate(cands)
    assert g["detected"] == "executed"
    assert "slash_command_found" in g["detection_basis"] and "tool_use" in g["detection_basis"]


def test_unrelated_tool_does_not_match_plan():
    cands, _ = build_hard_gate_candidates([], [], [], tool_names_seen={"Bash", "Read"})
    assert _plan_gate(cands)["detected"] == "miss"


def test_orphan_map_key_warns(monkeypatch):
    monkeypatch.setattr(sr, "GATE_EXECUTION_TOOL_NAMES",
                        {"plan-renamed": frozenset({"EnterPlanMode"})})
    _, warnings = build_hard_gate_candidates([], [], [], tool_names_seen=set())
    assert any("orphan" in w.lower() and "plan-renamed" in w for w in warnings)


# ---- extract_edits: tool_names collection ----
def test_mainthread_tool_collected():
    p = _write([_tool_use("EnterPlanMode"), _tool_use("ExitPlanMode")])
    _, stats = extract_edits(p)
    assert "EnterPlanMode" in stats["tool_names"] and "ExitPlanMode" in stats["tool_names"]


def test_sidechain_tool_excluded():
    # Plan subagent's ExitPlanMode in a sidechain line must NOT be collected (HIGH-1).
    p = _write([_tool_use("ExitPlanMode", sidechain=True)])
    _, stats = extract_edits(p)
    assert "ExitPlanMode" not in stats["tool_names"]
    # and end-to-end: parent plan gate stays "miss"
    cands, _ = build_hard_gate_candidates([], [], [], tool_names_seen=set(stats["tool_names"]))
    assert _plan_gate(cands)["detected"] == "miss"


def test_tool_result_echo_not_matched():
    # a tool_result block that echoes the string "ExitPlanMode" must not be collected.
    entry = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "content": "ran ExitPlanMode earlier"}]}}
    p = _write([entry])
    _, stats = extract_edits(p)
    assert "ExitPlanMode" not in stats["tool_names"]


def test_early_tool_survives_edit_truncation():
    # many edits (reverse-scanned first) then an EnterPlanMode earlier in the session:
    # decoupled collection must still find it (Gemini/ChatGPT HIGH).
    entries = [_tool_use("EnterPlanMode")]  # earliest line
    for i in range(50):
        entries.append(_tool_use("Write", input_={"file_path": f"/tmp/f{i}.py"}))
    p = _write(entries)
    _, stats = extract_edits(p, max_edits=5)
    assert len(stats["tool_names"]) >= 1 and "EnterPlanMode" in stats["tool_names"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
