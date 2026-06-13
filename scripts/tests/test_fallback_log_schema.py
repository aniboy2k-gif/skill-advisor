"""CSR #1261 — schema-regression + scoped-exception guard for the /tmp deprecation telemetry.

Guards (DA-mandated):
- H2 (schema drift): the canonical telemetry record keys must stay stable across all emitters.
- H1 (scoped import-time write): constants.py must NOT write telemetry on the happy path
  (primary present); the import-time write is permitted ONLY on the rare legacy branch.
- de-dup: at most one line per (sid, consumer).
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path

CANONICAL_KEYS = {"ts", "event", "consumer", "sid", "primary_state"}


@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    """Point fallback_log at a temp HOME-local sink and a temp seen-dir."""
    import fallback_log
    importlib.reload(fallback_log)
    log = tmp_path / "skill-index-fallback.jsonl"
    seen = tmp_path / ".seen"
    monkeypatch.setattr(fallback_log, "_LOG", log)
    monkeypatch.setattr(fallback_log, "_SEEN_DIR", seen)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-sid-1")
    return fallback_log, log


def test_schema_keys_exact(isolated_log):
    fallback_log, log = isolated_log
    fallback_log.log_tmp_fallback("constants", Path("/nonexistent/skill-index.json"))
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert set(rec.keys()) == CANONICAL_KEYS, f"schema drift: {set(rec.keys())}"
    assert rec["event"] == "tmp_fallback_selected"
    assert rec["consumer"] == "constants"
    assert rec["sid"] == "test-sid-1"
    assert rec["primary_state"] == "missing"  # nonexistent primary
    assert rec["ts"].endswith("Z")


def test_dedup_per_consumer_sid(isolated_log):
    fallback_log, log = isolated_log
    for _ in range(5):
        fallback_log.log_tmp_fallback("skill-auto-loader", Path("/nonexistent"))
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1  # deduped to one


def test_distinct_consumers_distinct_lines(isolated_log):
    fallback_log, log = isolated_log
    fallback_log.log_tmp_fallback("constants", Path("/nonexistent"))
    fallback_log.log_tmp_fallback("session_activity", Path("/nonexistent"))
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2


def test_never_raises(isolated_log, monkeypatch):
    fallback_log, log = isolated_log
    # Force the sink dir to be unwritable-ish by pointing at an impossible path; must swallow.
    monkeypatch.setattr(fallback_log, "_LOG", Path("/proc/nonexistent/x.jsonl"))
    monkeypatch.setattr(fallback_log, "_SEEN_DIR", Path("/proc/nonexistent/.seen"))
    fallback_log.log_tmp_fallback("constants", Path("/nonexistent"))  # must not raise


def test_constants_no_write_on_happy_path(tmp_path, monkeypatch):
    """H1/ChatGPT scoped-exception: when primary EXISTS, importing constants writes nothing."""
    import fallback_log
    importlib.reload(fallback_log)
    log = tmp_path / "skill-index-fallback.jsonl"
    monkeypatch.setattr(fallback_log, "_LOG", log)
    monkeypatch.setattr(fallback_log, "_SEEN_DIR", tmp_path / ".seen")
    # Make the primary appear to exist so constants takes the happy branch.
    fake_primary = tmp_path / ".claude" / "da-tools" / "skill-index.json"
    fake_primary.parent.mkdir(parents=True)
    fake_primary.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    import constants
    importlib.reload(constants)
    assert constants.SKILL_INDEX == fake_primary
    assert not log.exists(), "constants.py wrote telemetry on the happy path (scoped-exception violated)"
