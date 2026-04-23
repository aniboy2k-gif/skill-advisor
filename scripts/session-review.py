#!/usr/bin/env python3
"""
skill-advisor --session-review
Recommend related skills based on files edited in the current Claude Code session.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure scripts/ dir is on sys.path for sibling imports (constants, jsonl_analyzer, etc.)
_SCRIPTS_DIR = str(Path(__file__).parent.resolve())
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from constants import (  # noqa: E402
    DATA_DIR,
    EXCLUDE_PREFIXES,
    FILE_WRITE_TOOLS,
    PROJECTS_BASE,
    SKILL_INDEX,
)
from jsonl_analyzer import AnalysisError, analyze_session_signals  # noqa: E402
from signal_to_skill import map_signals_to_skills  # noqa: E402
from hard_gate_parser import load_hard_gates  # noqa: E402
from session_activity import extract_slash_commands  # noqa: E402

_RETRO_SKILL_NAME = "session-retrospective"
_RETRO_REPO_URL = "https://github.com/accidentalrebel/claude-skill-session-retrospective"


def is_retro_available(skills_dir: Path | None = None) -> tuple[bool, str | None]:
    """Detect session-retrospective and retrieve session JSONL via get-session.sh.

    Returns:
        (True, tmp_jsonl_path) on Track 1 success.
        (False, None) on Track 2 fallback — always safe to ignore second element.

    Track 1 requirements:
        1. session-retrospective skill installed (SKILL.md + get-session.sh present)
        2. CLAUDE_SESSION_ID environment variable set
        3. get-session.sh exits 0

    Args:
        skills_dir: Inject for testing. When None, checks CLAUDE_SKILLS_DIR env var then default.
    """
    env_path = os.environ.get("CLAUDE_SKILLS_DIR")
    base = skills_dir or (Path(env_path) if env_path else None) or (Path.home() / ".claude" / "skills")
    if base != (Path.home() / ".claude" / "skills"):
        print(f"[INFO] skill-advisor: using CLAUDE_SKILLS_DIR: {base}", file=sys.stderr)

    retro = base / _RETRO_SKILL_NAME
    script = retro / "scripts" / "get-session.sh"

    # 파일 존재 확인
    if not (retro.exists() and (retro / "SKILL.md").exists() and script.exists()):
        return False, None

    # 심볼릭 링크 거부 (보안)
    if script.is_symlink():
        print("[WARN] skill-advisor: get-session.sh가 심볼릭 링크 — Track 2로 전환", file=sys.stderr)
        return False, None

    # CLAUDE_SESSION_ID 사전 확인
    session_id = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if not session_id:
        return False, None

    # get-session.sh 실행
    try:
        result = subprocess.run(
            [str(script), session_id],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return False, None
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        tmp.write(result.stdout)
        tmp.close()
        return True, tmp.name
    except subprocess.TimeoutExpired as e:
        if hasattr(e, "process") and e.process:
            e.process.kill()
        return False, None
    except Exception:
        return False, None


def find_jsonl(confirm: bool = False) -> Path | None:
    cwd_hash = str(Path(os.getcwd()).resolve()).replace("/", "-")
    project_dir = PROJECTS_BASE / cwd_hash

    if project_dir.exists():
        candidates = sorted(
            project_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    else:
        candidates = sorted(
            PROJECTS_BASE.rglob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:5]

    if not candidates:
        print("❌ No JSONL session files found.", file=sys.stderr)
        return None

    if confirm and len(candidates) > 1:
        print("Available sessions (most recent first):")
        for i, p in enumerate(candidates[:5], 1):
            import datetime
            mt = datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"  {i}. {p.name}  ({mt}, {p.stat().st_size // 1024} KB)")
        try:
            choice = input("Select [1]: ").strip() or "1"
        except EOFError:
            print("[WARN] Non-interactive environment — using most recent session.", file=sys.stderr)
            return candidates[0]
        try:
            return candidates[int(choice) - 1]
        except (IndexError, ValueError):
            return candidates[0]

    return candidates[0]


_MAX_JSONL_SIZE = 100 * 1024 * 1024  # 100MB


def extract_edits(jsonl: Path, max_edits: int = 200) -> tuple[list[dict], dict]:
    # JSONL 크기 제한 — 100MB 초과 시 최근 부분만 읽음
    try:
        size = jsonl.stat().st_size
    except OSError:
        size = 0
    if size > _MAX_JSONL_SIZE:
        print(
            f"[WARN] JSONL {size // 1024 // 1024}MB > 100MB — 최근 부분만 분석합니다.",
            file=sys.stderr,
        )
        with jsonl.open("rb") as fh:
            fh.seek(-_MAX_JSONL_SIZE, 2)
            raw = fh.read()
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    else:
        try:
            text = jsonl.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            text = jsonl.read_text(encoding="utf-8", errors="replace")
            print("[WARN] Encoding issues detected — using replace mode", file=sys.stderr)

    all_lines = text.splitlines()
    tool_uses_seen = 0
    parse_errors = 0
    edits: list[dict] = []

    for line in reversed(all_lines):
        if len(edits) >= max_edits:
            break
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue

        for c in d.get("message", {}).get("content", []) or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            tool_uses_seen += 1
            name = c.get("name", "")
            if name in FILE_WRITE_TOOLS:
                inp = c.get("input", {})
                path = inp.get("file_path") or inp.get("path")
                if path:
                    edits.append({"file": path, "tool": name})
                    if len(edits) >= max_edits:
                        break

    stats = {
        "total_lines": len(all_lines),
        "tool_uses": tool_uses_seen,
        "edits_found": len(edits),
        "parse_errors": parse_errors,
    }
    return edits, stats


def glob_confidence(g: str) -> str:
    depth = g.count("/")
    has_double_star = "**" in g
    is_simple_ext = has_double_star and depth <= 1 and g.count(".") == 1
    if is_simple_ext:
        return "low"
    if has_double_star and depth >= 2:
        return "medium"
    if depth >= 2:
        return "high"
    return "medium"


def load_skill_index() -> list[dict]:
    if not SKILL_INDEX.exists():
        try:
            hook = Path.home() / ".claude" / "hooks" / "skill-index.sh"
            # 심볼릭 링크 거부 (보안)
            if not hook.is_symlink() and hook.is_file():
                try:
                    subprocess.run(["zsh", str(hook)], capture_output=True, timeout=10)
                except subprocess.TimeoutExpired as e:
                    if hasattr(e, "process") and e.process:
                        e.process.kill()
        except Exception:
            pass
    if not SKILL_INDEX.exists():
        return []
    try:
        data = json.loads(SKILL_INDEX.read_text(encoding="utf-8"))
        # v1/v2 하위 호환
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return data.get("skills", [])
        return []
    except Exception:
        return []


def build_candidates(edits: list[dict], skills: list[dict]) -> dict[str, dict]:
    order = {"high": 3, "medium": 2, "low": 1}
    seen: set[tuple] = set()
    per_skill: dict[str, dict] = {}

    for skill in skills:
        name = skill.get("skill", "?")
        for g in skill.get("file_path_globs", []):
            for edit in edits:
                f = edit["file"]
                if any(f.startswith(p) for p in EXCLUDE_PREFIXES):
                    continue
                key = (name, f)
                if key in seen:
                    continue
                if fnmatch.fnmatch(f, g):
                    seen.add(key)
                    conf = glob_confidence(g)
                    cur = per_skill.get(name)
                    if not cur or order[conf] > order[cur["confidence"]]:
                        per_skill[name] = {
                            "skill": name,
                            "file": Path(f).name,
                            "_full_path": f,
                            "glob": g,
                            "confidence": conf,
                            "matched_files": cur["matched_files"] + 1 if cur else 1,
                        }
                    elif cur:
                        cur["matched_files"] += 1

    return per_skill


def build_proposals(edits: list[dict], candidates: dict[str, dict]) -> list[dict]:
    from datetime import datetime, timezone
    matched_paths = {c["_full_path"] for c in candidates.values()}
    unmatched = [
        e["file"] for e in edits
        if e["file"] not in matched_paths
        and not any(e["file"].startswith(p) for p in EXCLUDE_PREFIXES)
    ]

    proposals = []
    for f in unmatched[:5]:
        p = Path(f)
        proposals.append({
            "schema_version": "1.0",
            "skill": "(unknown — no matching skill)",
            "target_field": "file_path_globs",
            "proposal_type": "add_glob",
            "value": f"**/{p.name}",
            "current_value": [],
            "confidence": "low",
            "reason": f"Edited file '{p.name}' matched no skill glob",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
    return proposals


def build_hard_gate_candidates(
    edits: list[dict],
    slash_commands: list[str],
    error_signals: list[dict],
) -> tuple[list[dict], list[str]]:
    """Hard Gate 트리거 후보 탐지.

    Returns:
        (candidates, warnings)
        candidates: detected=True means slash command found in session;
                    detected=False means not found but trigger signals present.
    """
    gates, warnings = load_hard_gates()
    invoked = {cmd.lstrip("/") for cmd in slash_commands}
    results = []
    for gate in gates:
        skill = gate.get("skill", "")
        detected = skill in invoked
        triggered_by: list[str] = []
        for sig in gate.get("session_signals", []):
            sig_lower = sig.lower()
            for edit in edits:
                if sig_lower in edit["file"].lower():
                    name = Path(edit["file"]).name
                    if f"file:{name}" not in triggered_by:
                        triggered_by.append(f"file:{name}")
                    break
            for err in error_signals:
                snippet = err.get("snippet", "")
                if sig_lower in snippet.lower():
                    label = f"error:{sig}"
                    if label not in triggered_by:
                        triggered_by.append(label)
                    break
        results.append({
            "skill": skill,
            "trigger_pattern": gate.get("trigger_pattern", ""),
            "source": gate.get("source", "hard-gates.json"),
            "detected": detected,
            "triggered_by": triggered_by[:3],
            "detection_basis": (
                "slash_command_found" if detected else "JSONL keyword match [ESTIMATED]"
            ),
        })
    return results, warnings


def print_report(
    jsonl: Path,
    stats: dict,
    candidates: dict,
    proposals: list,
    signal_recs: list | None = None,
    has_retro: bool = False,
    hard_gate_candidates: list | None = None,
    hard_gate_warnings: list | None = None,
    slash_commands: list | None = None,
) -> None:
    import datetime
    mt = datetime.datetime.fromtimestamp(jsonl.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    track_label = "[Track 1: session-retrospective]" if has_retro else "[Track 2: built-in]"
    print(f"\n## /skill-advisor --session-review\n")
    print(f"Track: {track_label}")
    print(
        "⚠ Candidate recommendations only — load history not directly verified.\n"
        "  (Phase 1.5 load log required for direct comparison)\n"
    )
    print(f"Session: {jsonl.name}  ({mt}, {jsonl.stat().st_size // 1024} KB)")
    print(
        f"Parsed: {stats['edits_found']} file edit events "
        f"/ {stats['tool_uses']} tool_uses"
        + (f" / ⚠ {stats['parse_errors']} parse errors" if stats['parse_errors'] else "")
    )
    if slash_commands:
        print(f"Slash commands detected: {', '.join(slash_commands[:10])}")

    print("\n---\n### Related Skill Candidates (file-change based)\n")
    if candidates:
        print(f"{'Skill':<22} {'Matched file':<35} {'Glob':<30} {'Confidence'}")
        print("-" * 100)
        for c in sorted(candidates.values(), key=lambda x: -{"high": 3, "medium": 2, "low": 1}[x["confidence"]]):
            n = c.get("matched_files", 1)
            suffix = f" (+{n-1} more)" if n > 1 else ""
            print(f"{c['skill']:<22} {c['file'] + suffix:<35} {c['glob']:<30} {c['confidence']}")
    else:
        print("No related skills found for edited files.")
        print("→ Run `/skill-advisor --scan` to check skill coverage.")

    if signal_recs:
        err_recs = [r for r in signal_recs if r["source"] == "error_signal"]
        cor_recs = [r for r in signal_recs if r["source"] == "correction_signal"]
        if err_recs:
            print("\n---\n### Error-driven Recommendations\n")
            print(f"{'Skill':<22} {'Signal':<35} {'Confidence':<12} {'Evidence'}")
            print("-" * 80)
            for r in sorted(err_recs, key=lambda x: -{"high": 3, "medium": 2, "low": 1}[x["confidence"]]):
                print(
                    f"{r['skill']:<22} {r['signal'][:34]:<35} "
                    f"{r['confidence']:<12} {r['evidence_count']} detected"
                )
        if cor_recs:
            print("\n---\n### Correction-driven Recommendations\n")
            for r in cor_recs:
                print(f"  → {r['skill']} ({r['signal']}, {r['evidence_count']} corrections detected)")

    if proposals:
        print("\n---\n### Improvement Proposals (SkillPatchProposal)\n")
        print("Files edited with no matching skill glob — consider adding globs:\n")
        print(json.dumps(proposals, indent=2, ensure_ascii=False))
        print("\nApply via `skill-creator`. See: /skill-advisor --enrich <skill-name>")

    print()
    if has_retro:
        print(f"🔗 session-retrospective detected — run /session-retrospective for a full retrospective")
    else:
        print(f"💡 TIP: install session-retrospective for a full narrative session retrospective")
        print(f"   {_RETRO_REPO_URL}")


def print_json(
    jsonl: Path,
    stats: dict,
    candidates: dict,
    proposals: list,
    signal_recs: list | None = None,
    has_retro: bool = False,
    hard_gate_candidates: list | None = None,
    hard_gate_warnings: list | None = None,
    slash_commands: list | None = None,
    edits: list | None = None,
) -> None:
    print(json.dumps({
        "session": str(jsonl),
        "track": "track1" if has_retro else "track2",
        "track_info": "session-retrospective" if has_retro else "built-in",
        "edited_files": [e["file"] for e in (edits or [])],
        "slash_commands_found": slash_commands or [],
        "skill_candidates": [
            {k: v for k, v in c.items() if k != "_full_path"}
            for c in candidates.values()
        ],
        "hard_gate_candidates": hard_gate_candidates or [],
        "hard_gate_warnings": hard_gate_warnings or [],
        "signal_recommendations": signal_recs or [],
        "proposals": proposals,
        "session_stats": stats,
    }, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="skill-advisor --session-review")
    parser.add_argument("--confirm", action="store_true", help="Choose session interactively")
    parser.add_argument("--max-edits", type=int, default=200, help="Max file edit events to analyze")
    parser.add_argument("--jsonl", type=str, default=None, help="Explicit JSONL path")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    args = parser.parse_args()

    # 트랙 감지 (JSONL 결정 전 수행 — Track 1은 JSONL을 직접 제공)
    has_retro, retro_jsonl_path = is_retro_available()

    # JSONL 결정: 우선순위 --jsonl > Track1 > find_jsonl
    if args.jsonl:
        # --jsonl 경로 검증 (PROJECTS_BASE 또는 /tmp 하위만 허용)
        import tempfile as _tf
        requested = Path(args.jsonl).resolve()
        projects_base = PROJECTS_BASE.resolve()
        tmpdir = Path(_tf.gettempdir()).resolve()
        if not (
            str(requested).startswith(str(projects_base))
            or str(requested).startswith(str(tmpdir))
        ):
            print(
                f"[ERROR] --jsonl 경로는 {projects_base} 또는 {tmpdir} 하위여야 합니다.",
                file=sys.stderr,
            )
            return 2
        jsonl: Path | None = requested
    elif retro_jsonl_path:
        jsonl = Path(retro_jsonl_path)
    else:
        jsonl = find_jsonl(confirm=args.confirm)

    if not jsonl:
        return 2

    edits, stats = extract_edits(jsonl, max_edits=args.max_edits)
    skills = load_skill_index()
    if not skills:
        print("[WARN] skill-index.json unavailable — run: zsh ~/.claude/hooks/skill-index.sh", file=sys.stderr)

    candidates = build_candidates(edits, skills)
    proposals = build_proposals(edits, candidates)

    # 시그널 분석 (두 트랙 공통)
    signal_recs: list = []
    try:
        signals = analyze_session_signals(jsonl, max_events=args.max_edits)
        signal_recs = map_signals_to_skills(signals)
    except Exception as e:
        print(f"[WARN] skill-advisor: signal analysis failed — {e}", file=sys.stderr)

    # 슬래시 커맨드 추출 + Hard Gate 후보 탐지
    slash_commands = extract_slash_commands(jsonl, max_events=args.max_edits * 2)
    error_signals = [r for r in signal_recs if r.get("source") == "error_signal"]
    hard_gate_candidates, gate_warnings = build_hard_gate_candidates(
        edits, slash_commands, error_signals
    )

    if args.json_out:
        print_json(
            jsonl, stats, candidates, proposals,
            signal_recs, has_retro,
            hard_gate_candidates, gate_warnings, slash_commands,
            edits=edits,
        )
    else:
        print_report(
            jsonl, stats, candidates, proposals,
            signal_recs, has_retro,
            hard_gate_candidates, gate_warnings, slash_commands,
        )

    # Track 1 임시 파일 정리
    if retro_jsonl_path and Path(retro_jsonl_path).exists():
        try:
            Path(retro_jsonl_path).unlink()
        except Exception:
            pass

    return 0  # --session-review is informational: exit 0 always on success


if __name__ == "__main__":
    sys.exit(main())
