# skill-advisor

> Your Claude Code skills not triggering? Find out why — without touching a single file.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-blue)](https://code.claude.com/docs/en/skills)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**skill-advisor** is a read-only diagnostic skill for [Claude Code](https://code.claude.com). No SKILL.md is ever modified — it surfaces issues and outputs structured JSON proposals you review and apply when ready.

---

## When to use this

- A skill isn't loading automatically even though you installed it
- Two skills seem to react to the same file at the same time
- You want a safety check before editing a skill's configuration manually
- You want to know which of your skills have no file-based auto-trigger set up

---

## Features

### Find unreachable and misconfigured skills — `--scan`

Audits all installed skills and classifies issues by severity:

| Code | Severity | Meaning | User impact |
|------|----------|---------|-------------|
| C1 | **critical** | Broken absolute path in `file_path_globs` | Skill silently fails to load |
| H0 | **high** | Ghost skill — zero triggers across all mechanisms | Skill is completely unreachable |
| H1 | **high** | Missing `file_path_globs` | Skill won't load on file edits |
| M1 | **medium** | Duplicate glob string declared by 2+ skills | Potential redundant loading |
| I1 | **info** | Empty `description` field | Reduces indexing quality |

*H0 is higher severity than H1: a ghost skill is completely unreachable, while an H1 skill can still be triggered by utterance patterns.*

> ⚠ **Phase 1 limitation**: M1 detects exact string matches only. "No M1" does not guarantee zero conflicts.

### Review post-work skill coverage — `--session-review`

After completing a task, check which installed skills were relevant to files you edited — and which may have missed loading.

Analyzes the current Claude Code session's JSONL file to recommend related skills based on file changes:

```
/skill-advisor --session-review           → Immediate analysis (most recent session)
/skill-advisor --session-review --confirm → Choose session interactively
/skill-advisor --session-review --json    → Machine-readable output
```

Example output:
```
## /skill-advisor --session-review

⚠ Candidate recommendations only — load history not directly verified.

Session: abc123.jsonl  (2026-04-23 09:18, 12365 KB)
Parsed: 160 file edit events / 758 tool_uses

Related Skill Candidates:
  [medium] skill-creator  — SKILL.md ← **/.claude/skills/**
  [low]    doc-coauthoring — README.md ← **/README.md
```

> **Phase 1 limitation**: Bash command-based file changes are not detected. This is a candidate recommendation, not a definitive diagnosis.

### Get reviewable improvement proposals — `--enrich [skill-name]`

Reads the target skill's SKILL.md, optionally fetches the official README for `anthropics/skills` sources, and outputs a `SkillPatchProposal[]` array — structured suggestions you review before applying.

### Machine-readable output — `--scan --json`

Returns a JSON array for CI pipelines or shell scripts.

---

## Safe by Design

skill-advisor never writes to SKILL.md. Changes to your skill configuration should always be intentional and reviewed.

| Action | Tool |
|--------|------|
| Diagnose & advise | **skill-advisor** (this) |
| Apply changes | `skill-creator --apply-proposal` *(Phase 2)* |

---

## What is a Claude Code skill?

Claude Code skills are `SKILL.md` files that extend Claude's capabilities. Each skill can define three types of **trigger mechanisms**:

| Mechanism | How it works |
|-----------|-------------|
| `file_path_globs` | Auto-loads the skill when you edit a matching file path |
| `tool_events` | Auto-loads when a specific tool (Edit, Write…) is used on a matching file |
| `utterance_patterns` | Helps Claude identify the skill when you describe a task in natural language |

skill-advisor audits all three. A skill with none of them is a "ghost skill" — installed but unreachable.

> **New to Claude Code?** See the [official skills documentation](https://code.claude.com/docs/en/skills) to get started.

---

## Prerequisites

- [Claude Code](https://code.claude.com) installed and running
- `skill-index.sh` SessionStart hook active

  Check if it's already installed:
  ```bash
  ls ~/.claude/hooks/skill-index.sh
  # Prints the path if installed — if not found, install the Claude Code hooks package
  ```

  > If `skill-index.json` is unavailable at runtime, skill-advisor automatically falls back to scanning `~/.claude/skills/` directly and warns you.

---

## Installation

```bash
# Clone and install
git clone https://github.com/aniboy2k-gif/skill-advisor
cp -r skill-advisor ~/.claude/skills/
# ↑ This copies SKILL.md, scripts/session-review.py, and references/

# Rebuild the skill index so Claude Code recognises the new skill
# (This regenerates /tmp/skill-index.json that skill-advisor reads)
zsh ~/.claude/hooks/skill-index.sh
```

Start or restart a Claude Code session — skill-advisor will be available immediately.

---

## Usage

```
/skill-advisor                          → Full scan (default)
/skill-advisor --scan                   → Coverage audit with severity labels
/skill-advisor --scan --json            → JSON output for automation
/skill-advisor --enrich <skill-name>    → Deep analysis + SkillPatchProposal output
/skill-advisor --session-review         → Post-work skill candidate recommendations
/skill-advisor --session-review --confirm → Choose session interactively
```

### Example `--scan` output

```
## skill-advisor --scan  (2026-04-23)

| Skill            | globs | events | Type        | Issues  |
|------------------|-------|--------|-------------|---------|
| doc-coauthoring  |   8   |   10   | normal      | —       |
| skill-creator    |   7   |   12   | normal      | —       |
| my-custom-skill  |   0   |    0   | manual-only | ℹ H1-M  |

Issue list
[HIGH]   orphan-skill:     H0 Ghost skill — no triggers defined
[HIGH]   half-baked-skill: H1 file_path_globs missing
[MEDIUM] skill-a, skill-b: M1 duplicate glob "**/*.md"

Note: H1-M (manual-only) = skill relies on utterance patterns only,
      intentionally excluded from the H1 warning.
⚠ M1 matches exact strings only — fnmatch path overlap detection coming in Phase 2.
```

### Example `SkillPatchProposal` (`--enrich`)

```json
[
  {
    "schema_version": "1.0",
    "skill": "doc-coauthoring",
    "target_field": "file_path_globs",
    "proposal_type": "add_glob",
    "value": "**/*.mdx",
    "current_value": ["**/*.md"],
    "source": "official_readme",
    "source_url": "https://github.com/anthropics/skills/...",
    "fetched_at": "2026-04-23T10:00:00+0900",
    "confidence": "high",
    "reason": "MDX files mentioned in official README"
  }
]
```

**`proposal_type` values (Phase 1):** `add_glob` · `update_description` · `fix_path` · `update_utterance`

---

## I/O Contract

<details>
<summary>For CI / scripting use</summary>

| | Definition |
|-|-----------|
| **stdin** | None |
| **stdout** | Text report; `--json` → JSON array |
| **stderr** | Execution error messages |
| **exit 0** | `--scan`: no issues / `--session-review`: always (informational tool) |
| **exit 1** | `--scan`: actionable findings exist (useful for CI gating) |
| **exit 2** | Execution failed — file access error, parse error, etc. |

</details>

---

## Limitations

- M1 detects **exact string duplicates only** — fnmatch path overlap is Phase 2
- `--apply` is not available in Phase 1 — apply proposals manually via `skill-creator`
- `source_type` classification is path-heuristic — official skill impersonation is not detected

---

## Roadmap

### ✅ Phase 1 (current)
- Scan for C1 / H0 / H1 / M1 / I1 issues with severity classification
- Generate `SkillPatchProposal` JSON (4 proposal types)
- Automatic fallback scan when `skill-index.json` is unavailable
- `--session-review`: post-work skill candidate recommendations from JSONL session analysis

### 🔜 Phase 1.5 (next milestone)
- Load event logging in `skill-auto-loader.sh` for direct comparison
- Enable `--session-review` to show "actually loaded" vs "should have loaded"

### 🔜 Phase 2 (planned)
- Direct apply: send proposals to `skill-creator` automatically
- Better conflict detection: fnmatch-based path overlap for M1
- Smarter proposals: confidence scoring with source freshness tracking
- Trusted source verification for official skills
- `--session-review` utterance-based skill discovery (semantic analysis)

---

## License

MIT
