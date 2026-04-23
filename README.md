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
- You want error and correction patterns from your session mapped to relevant skills

---

## Features

### Find unreachable and misconfigured skills — `--scan`

Audits all installed skills and classifies issues by severity:

| Code | Severity | Meaning | User impact |
|------|----------|---------|-------------|
| C1 | **critical** | Broken absolute path in `file_path_globs` | Skill silently fails to load |
| H0 | **high** | Ghost skill — zero triggers across all mechanisms | Skill is completely unreachable |
| H1 | **high** | Missing `file_path_globs` | Skill won't load on file edits |
| H1-E | **info** | tool_events only, no globs — intentional design | No false alarm; treated like H1-M |
| H1-M | **info** | utterance patterns only — intentional manual-only | No false alarm |
| M1 | **medium** | Duplicate glob string declared by 2+ skills | Potential redundant loading |
| I1 | **info** | Empty `description` field | Reduces indexing quality |

*H0 is higher severity than H1: a ghost skill is completely unreachable, while H1/H1-E/H1-M skills can still be triggered by other mechanisms.*

> ⚠ **Phase 1 limitation**: M1 detects exact string matches only. "No M1" does not guarantee zero conflicts.

### Review post-work skill coverage — `--session-review`

After completing a task, analyze the current session's JSONL to get two layers of skill recommendations:

**Layer 1 — File-change based** (existing): Which skills are relevant to files you edited?

**Layer 2 — Signal based** (new in Phase 1.6): What do error patterns and user corrections in this session suggest about missing skills?

```
/skill-advisor --session-review           → Immediate analysis (most recent session)
/skill-advisor --session-review --confirm → Choose session interactively
/skill-advisor --session-review --json    → Machine-readable output
```

Example output:
```
## /skill-advisor --session-review

Session: abc123.jsonl  (2026-04-23 09:18, 1662 KB)
Parsed: 160 file edit events / 758 tool_uses

---
### Related Skill Candidates (file-change based)

Skill                  Matched file                        Glob                           Confidence
----------------------------------------------------------------------------------------------------
skill-creator          SKILL.md                            **/.claude/skills/**           medium

---
### Error-driven Recommendations

Skill                  Signal                              Confidence   Evidence
--------------------------------------------------------------------------------
systematic-debugging   test failure pattern                high         3 건

---
### Correction-driven Recommendations

  → plan (repeated user corrections, 4건 수정 감지)

🔗 session-retrospective installed — run /session-retrospective for a full session retrospective
```

Each signal-based recommendation carries **provenance**: `source`, `signal`, `confidence`, and `evidence_count` — so you know exactly why a skill was recommended.

> **Conservative design**: signal detection uses a 3-condition AND gate (assistant tool_use preceding + short message + negation keyword) to minimise false positives. False negatives are accepted as a trade-off.

> **Phase 1 limitation**: Bash command-based file changes are not detected. Signal recommendations are heuristic, not definitive.

### Get reviewable improvement proposals — `--enrich [skill-name]`

Reads the target skill's SKILL.md, optionally fetches the official README for `anthropics/skills` sources, and outputs a `SkillPatchProposal[]` array — structured suggestions you review before applying.

### Machine-readable output — `--scan --json`

Returns a JSON array for CI pipelines or shell scripts.

The `--session-review --json` output includes:

```json
{
  "session": "abc123.jsonl",
  "track": "track1",
  "candidates": [...],
  "signal_recommendations": [
    {
      "skill": "systematic-debugging",
      "source": "error_signal",
      "signal": "test failure pattern",
      "confidence": "high",
      "evidence_count": 3
    }
  ],
  "proposals": [...]
}
```

---

## Optional Integration: session-retrospective

skill-advisor works standalone, but pairs naturally with [claude-skill-session-retrospective](https://github.com/accidentalrebel/claude-skill-session-retrospective).

### Two-track detection

skill-advisor automatically detects whether session-retrospective is installed and adjusts its output:

| | Track 1 (installed) | Track 2 (not installed) |
|-|---------------------|------------------------|
| **JSONL analysis** | ✅ same | ✅ same |
| **Signal recommendations** | ✅ same | ✅ same |
| **Footer message** | `🔗 session-retrospective installed — run /session-retrospective` | `💡 TIP: install session-retrospective for a full narrative retrospective` |

Both tracks produce **identical skill recommendation quality** — the difference is only the footer guidance.

### Install session-retrospective

```bash
cd ~/.claude/skills
git clone https://github.com/accidentalrebel/claude-skill-session-retrospective session-retrospective
```

Once installed, running `/skill-advisor --session-review` followed by `/session-retrospective` gives you:
- skill-advisor: which skills to use next time (forward-looking)
- session-retrospective: what you learned this session (backward-looking)

> **Note**: session-retrospective has no published license (licenseInfo: null as of 2026-04-23). skill-advisor's signal analysis is an independent implementation — no code from that repository is reused.

---

## What skill-advisor does right now (Phase 1.6)

skill-advisor **never writes to SKILL.md** — it only reads and reports.

| Capability | Phase 1.6 (now) | Phase 2 (planned) |
|-----------|:---:|:---:|
| Diagnose skill coverage (`--scan`) | ✅ | ✅ |
| Generate improvement proposals (`--enrich`) | ✅ dry-run only | ✅ |
| Apply proposals to SKILL.md | ❌ not available | ✅ via `skill-creator --apply-proposal` |
| File-change based skill candidates (`--session-review`) | ✅ | ✅ |
| Error/correction signal analysis (`--session-review`) | ✅ | ✅ |
| session-retrospective 2-track detection | ✅ | ✅ |

To apply proposals now: review the JSON output, then use `skill-creator` manually.

---

## Architecture (Phase 1.6)

```
scripts/
  session-review.py      Orchestrator — coordinates all analysis
  jsonl_analyzer.py      Collector — parses JSONL for error/correction signals
  signal_to_skill.py     Mapper — maps signals to skill recommendations (with provenance)
  constants.py           Shared constants (prevents circular imports)

data/
  signal-skills.json     Versioned mapping table (schema_version: "1.0")
```

The signal mapping table is externalized so you can tune it without touching Python code:

```json
{
  "schema_version": "1.0",
  "mappings": [
    {
      "id": "test-failure",
      "triggers": { "error_keywords": ["AssertionError", "test failed"], "min_count": 1 },
      "skill": "systematic-debugging",
      "confidence": "high",
      "evidence_label": "test failure pattern"
    }
  ]
}
```

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
- **Python 3.9+** (for `--session-review`)
  > Verify: `python3 --version`
- `skill-index.sh` SessionStart hook active

  Check if it's already installed:
  ```bash
  ls ~/.claude/hooks/skill-index.sh
  # Prints the path if installed — if not found, install the Claude Code hooks package
  ```

  To register the hook permanently, add to `~/.claude/settings.json`:
  ```json
  {
    "hooks": {
      "SessionStart": [
        {
          "hooks": [
            {"type": "command", "command": "zsh ~/.claude/hooks/skill-index.sh"}
          ]
        }
      ]
    }
  }
  ```

  > If `skill-index.json` is unavailable at runtime, skill-advisor automatically falls back to scanning `~/.claude/skills/` directly and warns you.

---

## Installation

```bash
# Clone and install
git clone https://github.com/aniboy2k-gif/skill-advisor
cp -r skill-advisor ~/.claude/skills/
# ↑ This copies SKILL.md, scripts/, data/, and references/

# Rebuild the skill index so Claude Code recognises the new skill
zsh ~/.claude/hooks/skill-index.sh
```

Start or restart a Claude Code session — skill-advisor will be available immediately.

### Optional: pair with session-retrospective

```bash
cd ~/.claude/skills
git clone https://github.com/accidentalrebel/claude-skill-session-retrospective session-retrospective
```

---

## Usage

```
/skill-advisor                          → Full scan (default)
/skill-advisor --scan                   → Coverage audit with severity labels
/skill-advisor --scan --json            → JSON output for automation
/skill-advisor --enrich <skill-name>    → Deep analysis + SkillPatchProposal output
/skill-advisor --session-review         → Post-work skill candidate recommendations
/skill-advisor --session-review --confirm → Choose session interactively
                                             ⚠ Requires interactive terminal — do not use in Claude Code sessions
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
[MEDIUM] skill-a, skill-b: M1 duplicate glob "**/*.md"

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

`--session-review --json` keys: `session`, `track`, `stats`, `candidates`, `signal_recommendations`, `proposals`

</details>

---

## Limitations

- M1 detects **exact string duplicates only** — fnmatch path overlap is Phase 2
- `--apply` is not available in Phase 1 — apply proposals manually via `skill-creator`
- `source_type` classification is path-heuristic — official skill impersonation is not detected
- `--enrich` supports **official** (`anthropics/skills`) and **local** (`.claude/skills/`) skills only
- `--session-review --confirm` requires an **interactive terminal**
- Signal analysis uses a conservative 3-condition gate — some corrections may not be detected (by design)
- session-retrospective integration: skill-advisor detects installation but does **not** execute its scripts or parse its output

---

## Roadmap

### ✅ Phase 1 (initial)
- Scan for C1 / H0 / H1 / M1 / I1 issues with severity classification
- Generate `SkillPatchProposal` JSON (4 proposal types)
- Automatic fallback scan when `skill-index.json` is unavailable
- `--session-review`: post-work skill candidate recommendations from JSONL session analysis

### ✅ Phase 1.6 (current)
- **JSONL signal analysis**: error patterns (`is_error: true`) and correction patterns mapped to skills
- **Provenance fields**: every recommendation carries `source`, `signal`, `confidence`, `evidence_count`
- **2-track detection**: auto-detects session-retrospective installation, adapts output accordingly
- **Versioned mapping table**: `data/signal-skills.json` for tunable signal→skill mapping
- **constants.py**: shared constants preventing circular imports across analyzer modules

### 🔜 Phase 1.5 (next milestone)
- Load event logging in `skill-auto-loader.sh` for direct comparison
- Enable `--session-review` to show "actually loaded" vs "should have loaded"

### 🔜 Phase 2 (planned)
- Direct apply: send proposals to `skill-creator` automatically
- Better conflict detection: fnmatch-based path overlap for M1
- Smarter proposals: confidence scoring with source freshness tracking
- Trusted source verification for official skills
- `--session-review` utterance-based skill discovery (semantic analysis)
- session-retrospective structured JSON exchange (requires author collaboration)

---

## License

MIT
