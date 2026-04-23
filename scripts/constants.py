"""Shared constants for skill-advisor scripts — prevents circular imports."""
from __future__ import annotations

from pathlib import Path

# Base directories
SKILL_INDEX = Path("/tmp/skill-index.json")
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
