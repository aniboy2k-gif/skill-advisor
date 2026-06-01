"""CSR #973 — extract_slash_commands executed vs mention (da-chain C-1/H-1/M-2 결박).

실제 Claude Code transcript 구조 기반:
  - 실제 호출 = user entry, message.content = STRING, <command-name>/cmd</command-name> 트리플릿
  - 인용/논의 = content가 LIST(text 블록) 또는 tool_result → executed 아님 (mention)

CSR #1040: pytest 수집 호환 — 검사 로직을 _run_checks()로 캡슐화하고 pytest 테스트
함수로 노출. module-load 시 sys.exit를 호출하던 standalone 구조가 `pytest tests/`
수집 시 INTERNALERROR(SystemExit)를 유발하던 문제를 해소. standalone 실행도 유지.
"""
import json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from session_activity import extract_slash_commands  # noqa

def _write(entries):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for e in entries:
        f.write(json.dumps(e) + "\n")
    f.close()
    return Path(f.name)

def _real_invocation(cmd, args=""):
    # 실제 호출 구조: content = str triplet
    return {"type": "user", "message": {"role": "user",
            "content": f"<command-message>x</command-message>\n<command-name>/{cmd}</command-name>\n<command-args>{args}</command-args>"}}

def _text_mention(text):
    # 인용: content = list of text blocks
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}

def _tool_result_mention(text):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]}}


def _run_checks():
    """T1-T6 실행. 실패 케이스 이름 리스트 반환 (빈 리스트 = 전부 통과)."""
    passed = []; failed = []
    def check(name, cond):
        if cond: passed.append(name); print(f"  ✓ {name}")
        else: failed.append(name); print(f"  ✗ {name}")

    # T1: 실제 호출 /csr-task → executed
    p = _write([_real_invocation("csr-task", "args")])
    ex = extract_slash_commands(p)
    check("T1 real /csr-task invocation -> executed", "/csr-task" in ex)

    # T2: /trader-task 인용(text block)만 → NOT executed
    p = _write([_text_mention("da-chain 인자에 /trader-task 논의 + claude_fail #71 인용 /trader-task")])
    ex = extract_slash_commands(p)
    check("T2 /trader-task text-mention -> NOT executed", "/trader-task" not in ex)

    # T3: /trader-task tool_result 인용 → NOT executed
    p = _write([_tool_result_mention("CSR 본문에 /trader-task 35회 등장하나 미실행")])
    ex = extract_slash_commands(p)
    check("T3 /trader-task tool_result-mention -> NOT executed", "/trader-task" not in ex)

    # T4: H-1 colon namespaced /sc:analyze 실제 호출 → executed (콜론 mis-capture 방지)
    p = _write([_real_invocation("sc:analyze")])
    ex = extract_slash_commands(p)
    check("T4 H-1 /sc:analyze colon -> executed (full capture)", "/sc:analyze" in ex)

    # T5: M-2 한 메시지에 여러 호출은 없으나, 여러 엔트리 호출 모두 포착
    p = _write([_real_invocation("csr-task"), _real_invocation("plan"), _text_mention("/trader-task 언급")])
    ex = extract_slash_commands(p)
    check("T5 multiple invocations both captured", "/csr-task" in ex and "/plan" in ex)
    check("T5b mention excluded amid invocations", "/trader-task" not in ex)

    # T6: 핵심 회귀 — 실제 본 세션류(da-chain args + 논의 텍스트) 인용은 executed 0
    p = _write([_text_mention("--tier 2 /tmp/x — /trader-task SKILL.md re-DA + /da-chain 인자 논의")])
    ex = extract_slash_commands(p)
    check("T6 da-chain args + discussion -> no executed", ex == [])

    print(f"\nRESULT: PASS={len(passed)} FAIL={len(failed)}")
    return failed


def test_csr973_slash_detection():
    """pytest entry — CSR #973 7 케이스 (CSR #1040: pytest 수집 호환)."""
    failed = _run_checks()
    assert not failed, f"CSR #973 detection failures: {failed}"


if __name__ == "__main__":
    sys.exit(0 if not _run_checks() else 1)
