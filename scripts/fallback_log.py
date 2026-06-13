"""fallback_log.py — CSR #1261 deprecation telemetry for the legacy /tmp/skill-index.json fallback.

PURPOSE (single, narrow): record when a consumer SELECTS the legacy `/tmp/skill-index.json`
fallback instead of the da-tools primary SSOT. The accumulated log lets a follow-up CSR prove
the legacy path is genuinely unused before physically removing it (measure-then-retire).

THIS TELEMETRY IS SOLELY FOR REMOVAL QUALIFICATION — NOT operational diagnosis. Per-(consumer,sid)
de-duplication means a logged "hit" denotes "this session selected the fallback", not how many
times; a session that falls back once and one that falls back many times are intentionally
indistinguishable. Do not repurpose this signal for runtime diagnostics (CSR #1261 DA: ChatGPT M1).

CANONICAL SCHEMA (shared by ALL emitters — python here + bash hooks/lib/skill-index-fallback-log.sh):
    {"ts": <ISO8601 UTC, e.g. 2026-06-13T09:30:00Z>,
     "event": "tmp_fallback_selected",
     "consumer": <"constants"|"session_activity"|"skill-resolve"|"skill-auto-loader">,
     "sid": <session id | "unknown">,
     "primary_state": <"missing"|"stat_error">}
(skill-index.sh additionally emits {"ts","event":"session_observed","sid"} for liveness + session floor.)

SINK: ~/.claude/skill-index-fallback.jsonl — HOME-LOCAL on the internal disk (/dev/disk3s5),
verified independent of the external da-system volume whose absence triggers the fallback
(CSR #1261 DA: Claude Web C1, df-measured). Writes are best-effort and MUST never raise into
the caller (the caller is choosing a fallback already — telemetry must not worsen a degraded state).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_LOG = Path.home() / ".claude" / "skill-index-fallback.jsonl"
_SEEN_DIR = Path.home() / ".claude" / ".skill-index-fallback.seen"


def _sid() -> str:
    # Best-effort session id; dependency-free (this runs in degraded/import-broken paths).
    return (
        os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or "unknown"
    )


def log_tmp_fallback(consumer: str, primary: Path | str) -> None:
    """Append one de-duplicated 'tmp_fallback_selected' record. Never raises.

    De-dup: at most one line per (sid, consumer) via a marker file, so a PreToolUse hook that
    fires on every edit does not flood the log; the check script counts distinct (consumer,sid).
    """
    try:
        sid = _sid()
        marker = _SEEN_DIR / f"{sid}__{consumer}"
        if marker.exists():
            return  # already recorded this session for this consumer
        # Determine why the primary was not used (diagnostic attribution, not just a boolean).
        try:
            primary_state = "missing" if not Path(primary).exists() else "stat_error"
        except OSError:
            primary_state = "stat_error"
        rec = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": "tmp_fallback_selected",
            "consumer": consumer,
            "sid": sid,
            "primary_state": primary_state,
        }
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _SEEN_DIR.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except Exception:
        pass  # telemetry is best-effort; never break the consumer
