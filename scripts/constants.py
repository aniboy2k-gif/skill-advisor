"""Shared constants for skill-advisor scripts — prevents circular imports."""
from __future__ import annotations

from pathlib import Path

# Base directories (CSR #832 — /tmp 휘발성 회피)
# primary 영속 위치 우선 + /tmp legacy fallback (backward compat)
_SKILL_INDEX_PRIMARY = Path.home() / ".claude" / "da-tools" / "skill-index.json"
_SKILL_INDEX_LEGACY = Path("/tmp/skill-index.json")
SKILL_INDEX = _SKILL_INDEX_PRIMARY if _SKILL_INDEX_PRIMARY.exists() else _SKILL_INDEX_LEGACY
PROJECTS_BASE = Path.home() / ".claude" / "projects"
SCRIPTS_DIR = Path(__file__).parent
DATA_DIR = SCRIPTS_DIR.parent / "data"

# Tool names that write files
FILE_WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Paths to exclude from skill matching
EXCLUDE_PREFIXES = (
    str(Path.home() / ".claude" / "projects"),
    str(Path.home() / ".claude" / "da-tools"),
)

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)
