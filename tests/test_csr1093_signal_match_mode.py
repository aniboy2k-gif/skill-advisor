"""CSR #1093 — per-token signal_match_mode (substring | word) opt-in.

da-chain Tier 2 grounded design (CRITICAL 0, 채택 9):
  - default "substring" = byte-identical to pre-#1093 `token.lower() in text.lower()` (무회귀)
  - "word" = (?<![A-Za-z0-9_])TOKEN(?![A-Za-z0-9_]) IGNORECASE — concatenation FP 제거
  - H1: ASCII-only boundary → non-ASCII token degenerates to substring (+ warns once/gate)
  - H2: signal_match_mode keys = RAW case-sensitive token (IGNORECASE handles case, not the key)
  - M1: "word" does NOT fix delimiter-adjacent FPs (ARIA still matches "aria-label")
  - L2: underscore-FN is the intended tradeoff (auth↛auth_token in word mode)
  - H3: orphaned mode key (not in session_signals) → warning
  - H4: unknown-mode warning emitted ONCE per gate (not per match attempt)
"""
import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location("session_review_mod", _SCRIPTS / "session-review.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_signal_matches = _mod._signal_matches
_token_has_non_ascii = _mod._token_has_non_ascii
build_hard_gate_candidates = _mod.build_hard_gate_candidates


def _run_checks():
    fails = []

    def chk(cond, label):
        if not cond:
            fails.append(label)

    # --- substring mode (default): byte-identical to current behavior ---
    chk(_signal_matches("auth", "src/author.py", "substring"), "substring: auth in author.py")
    chk(_signal_matches("CSR", "CSRF.py", "substring"), "substring: CSR in CSRF.py")
    chk(_signal_matches("auth", "AUTH.PY", "substring"), "substring: case-insensitive")

    # --- word mode: concatenation FP removal (the #1027 motivation) ---
    chk(not _signal_matches("auth", "src/author.py", "word"), "word: auth NOT in author.py (FP removed)")
    chk(not _signal_matches("CSR", "CSRF.py", "word"), "word: CSR NOT in CSRF.py (FP removed)")
    chk(not _signal_matches("token", "tokenizer.py", "word"), "word: token NOT in tokenizer.py (FP removed)")

    # --- word mode: legitimate matches kept ---
    chk(_signal_matches("auth", "auth.py", "word"), "word: auth in auth.py (kept)")
    chk(_signal_matches("auth", "x auth y", "word"), "word: auth surrounded by space (kept)")
    chk(_signal_matches("auth", "auth-x.py", "word"), "word: auth before hyphen (kept)")
    chk(_signal_matches("CSR", "CSR-1093.md", "word"), "word: CSR before hyphen (kept)")

    # --- L2: underscore-FN is the intended tradeoff (documented) ---
    chk(not _signal_matches("auth", "auth_token.py", "word"), "word: auth NOT in auth_token.py (intended FN)")

    # --- M1: delimiter-adjacent FP is NOT fixed by word mode (honest scope) ---
    chk(_signal_matches("ARIA", "aria-label.tsx", "word"), "word: ARIA STILL matches aria-label.tsx (M1)")

    # --- H1: non-ASCII token degenerates to substring under word mode (no tightening) ---
    chk(_signal_matches("서브에이전트", "나의서브에이전트", "word"), "word: non-ASCII degenerates to substring (H1)")

    # --- M4: mixed-script tokens (real gate tokens: 'AI 게시판', '가이드 본문') ---
    chk(_token_has_non_ascii("AI 게시판"), "M4: 'AI 게시판' flagged non-ASCII (warns on word opt-in)")
    chk(_token_has_non_ascii("가이드 본문"), "M4: '가이드 본문' flagged non-ASCII")
    chk(not _token_has_non_ascii("agent completed"), "M4: ASCII-with-space token NOT flagged")
    chk(_signal_matches("AI 게시판", "나의 AI 게시판 글", "word"), "M4 word: mixed-script 'AI 게시판' matches in phrase (Korean boundary hybrid)")
    chk(_signal_matches("AI 게시판", "my AI 게시판 x", "substring"), "M4 substring default: space token byte-identical (no regression)")
    chk(_signal_matches("agent completed", "the agent completed now", "word"), "M4 word: ASCII space-token 'agent completed' phrase match")
    chk(not _signal_matches("agent completed", "agent completedx", "word"), "M4 word: 'agent completed' rejects suffix concat")

    # --- unknown mode → treated as substring by the helper ---
    chk(_signal_matches("auth", "author.py", "banana"), "unknown mode → substring fallback")

    # --- H2/H3/H4: build_hard_gate_candidates warnings (once per gate), backward-compat ---
    orig_load = _mod.load_hard_gates
    try:
        _mod.load_hard_gates = lambda: ([{
            "skill": "x",
            "session_signals": ["auth", "서브에이전트"],
            "signal_match_mode": {
                "auth": "word",          # ascii word — fine, no warning
                "서브에이전트": "word",   # H1: non-ASCII + word → degenerate warning
                "ghost": "word",         # H3: orphan (not in session_signals)
                "auth": "auth",          # (dict dedup) — see banana below for unknown
            },
        }], [])
        # Re-set with an unknown-mode entry that survives dict (distinct key)
        _mod.load_hard_gates = lambda: ([{
            "skill": "x",
            "session_signals": ["auth", "서브에이전트"],
            "signal_match_mode": {
                "auth": "word",
                "서브에이전트": "word",
                "ghost": "banana",   # H3 orphan + H4 unknown mode
            },
        }], [])
        _cands, warns = build_hard_gate_candidates(
            edits=[{"file": "src/author.py"}], slash_commands=[], error_signals=[],
            session_id=None, subagent_invocations=[], completion_context_state="absent",
        )
        joined = " | ".join(warns)
        chk(any("ghost" in w and "orphan" in w for w in warns), "H3: orphan key warning")
        chk(any("ghost" in w and "unknown mode" in w for w in warns), "H4: unknown-mode warning")
        chk(any("서브에이전트" in w and "non-ASCII" in w for w in warns), "H1: non-ASCII word warning")
        # H4: emitted once per gate, not per match attempt (1 edit, 1 gate → exactly 1 of each)
        chk(sum("non-ASCII" in w for w in warns) == 1, "H4: non-ASCII warning emitted once (not per-match)")

        # backward-compat: no signal_match_mode → runs, substring behavior (auth matches author.py)
        _mod.load_hard_gates = lambda: ([{"skill": "y", "session_signals": ["auth"]}], [])
        cands2, _w2 = build_hard_gate_candidates(
            edits=[{"file": "src/author.py"}], slash_commands=[], error_signals=[],
            session_id=None, subagent_invocations=[], completion_context_state="absent",
        )
        y = next(c for c in cands2 if c["skill"] == "y")
        chk(y["detected"] == "triggered", "backward-compat: substring default still triggers (author.py)")
    finally:
        _mod.load_hard_gates = orig_load

    return fails


def test_csr1093_signal_match_mode():
    fails = _run_checks()
    assert not fails, "FAILED: " + "; ".join(fails)


if __name__ == "__main__":
    fails = _run_checks()
    if fails:
        print(f"FAIL ({len(fails)}):")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("PASS: all CSR #1093 signal_match_mode checks")
