"""Shared constants for skill-advisor scripts — prevents circular imports."""
from __future__ import annotations

from pathlib import Path

# Base directories (CSR #832 — /tmp 휘발성 회피)
# primary 영속 위치 우선 + /tmp legacy fallback (backward compat)
_SKILL_INDEX_PRIMARY = Path.home() / ".claude" / "da-tools" / "skill-index.json"
_SKILL_INDEX_LEGACY = Path("/tmp/skill-index.json")
if _SKILL_INDEX_PRIMARY.exists():
    SKILL_INDEX = _SKILL_INDEX_PRIMARY
else:
    SKILL_INDEX = _SKILL_INDEX_LEGACY
    # CSR #1261 deprecation telemetry — logged AT THE DECISION POINT so every importer of
    # constants.SKILL_INDEX that selects the legacy path is counted (no coverage hole).
    # ★ SCOPED EXCEPTION: this is the ONLY permitted import-time side effect in this module,
    #   and it fires only on the RARE legacy branch (primary absent). No other unconditional
    #   import-time I/O is allowed here (enforced by tests/test_fallback_log_schema.py).
    try:
        from fallback_log import log_tmp_fallback
        log_tmp_fallback("constants", _SKILL_INDEX_PRIMARY)
    except Exception:
        pass
PROJECTS_BASE = Path.home() / ".claude" / "projects"
SCRIPTS_DIR = Path(__file__).parent
DATA_DIR = SCRIPTS_DIR.parent / "data"

# Tool names that write files
FILE_WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# tool_use names whose presence counts as INVOKING a Hard Gate (skill → tool names).
# Same semantic as a slash command in session-review: "invoked, NOT outcome-verified"
# (a /plan slash is marked executed regardless of whether that plan was approved; a
# tool invocation is the same-or-stronger 'invoked' evidence — ExitPlanMode means a
# plan was actually presented). Kept as a CODE constant, NOT in hard-gates.json, so the
# enforcement SSOT and its json-loaders (hard_gate_parser) stay unaffected — the plan→tools
# map is diagnostic-only (da-chain trader922-followup: Gemini HIGH-2 SSOT-pollution,
# Claude Web Q3). Precedent: FILE_WRITE_TOOLS above. Match is exact-case set intersection.
GATE_EXECUTION_TOOL_NAMES = {"plan": frozenset({"EnterPlanMode", "ExitPlanMode"})}

# Paths to exclude from skill matching
EXCLUDE_PREFIXES = (
    str(Path.home() / ".claude" / "projects"),
    str(Path.home() / ".claude" / "da-tools"),
)

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)
