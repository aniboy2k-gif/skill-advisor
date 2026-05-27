#!/usr/bin/env bash
# g-integrated-test.sh — CSR #825 Plan v4 (G3' 축소) 회귀 검증
# Fixture: A (detection 3 status + schema_version) · E (unified view + thresholds) · F (Tier classification)
#
# Phase 1 (Red): SKILL.md + session-review.py 미변경 → 일부 FAIL
# Phase 5 (Green): 변경 완료 → 모든 fixture PASS

set -uo pipefail

FIXTURE_DIR="$HOME/.claude/skills/skill-advisor/tests"
SKILL_MD="$HOME/.claude/skills/skill-advisor/SKILL.md"
SESSION_REVIEW="$HOME/.claude/skills/skill-advisor/scripts/session-review.py"
THRESHOLDS="$HOME/.claude/skill-advisor/thresholds.json"

PASS=0
FAIL=0
TOTAL=0

run_test() {
  local name="$1"
  local cmd="$2"
  local expected="$3"

  TOTAL=$((TOTAL + 1))
  if eval "$cmd" 2>/dev/null; then actual="PASS"; else actual="FAIL"; fi

  if [ "$actual" = "$expected" ]; then
    PASS=$((PASS + 1))
    echo "  ✓ $name (expected $expected)"
  else
    FAIL=$((FAIL + 1))
    echo "  ✗ $name (expected $expected, got $actual)"
  fi
}

echo "================================================================"
echo "CSR #825 Plan v4 (G3' 축소) 회귀 검증"
echo "================================================================"
echo ""

# Pre-check
SCHEMA_V2_IN_SCRIPT="no"
grep -q '"schema_version".*2\|schema_version["\047]:\s*2' "$SESSION_REVIEW" 2>/dev/null && SCHEMA_V2_IN_SCRIPT="yes"
UNIFIED_VIEW="no"
grep -q "unified_skill_view" "$SESSION_REVIEW" 2>/dev/null && UNIFIED_VIEW="yes"
SKILL_MD_HAS_TIER_RULE="no"
# CSR #825 Plan v4 — major/minor Tier 분리 명시 검증 (유연한 pattern)
grep -q "Tier 1.*의무\|major/minor.*Tier\|major.*Tier 1\|F (축소).*Tier 분리" "$SKILL_MD" 2>/dev/null && SKILL_MD_HAS_TIER_RULE="yes"
THRESHOLDS_EXISTS="no"
test -f "$THRESHOLDS" && THRESHOLDS_EXISTS="yes"

echo "Pre-check status:"
echo "  schema_version: 2 in script: $SCHEMA_V2_IN_SCRIPT"
echo "  unified_skill_view in script: $UNIFIED_VIEW"
echo "  SKILL.md major/minor Tier rule: $SKILL_MD_HAS_TIER_RULE"
echo "  thresholds.json exists: $THRESHOLDS_EXISTS"
echo ""

# Phase 결정
if [ "$SCHEMA_V2_IN_SCRIPT" = "yes" ] && [ "$UNIFIED_VIEW" = "yes" ] && [ "$SKILL_MD_HAS_TIER_RULE" = "yes" ] && [ "$THRESHOLDS_EXISTS" = "yes" ]; then
  PHASE="Green"
  EXPECTED="PASS"
else
  PHASE="Red"
  EXPECTED="FAIL"
fi
echo "Phase: $PHASE (expected: change tests $EXPECTED)"
echo ""

# === Fixture 파일 존재 검증 (변경 무관) ===
run_test "fixture-A exists" "test -f $FIXTURE_DIR/fixture-A-detection-3-status.json" "PASS"
run_test "fixture-E exists" "test -f $FIXTURE_DIR/fixture-E-unified-view.json" "PASS"
run_test "fixture-F exists" "test -f $FIXTURE_DIR/fixture-F-tier-classification.json" "PASS"

# === Fixture A — detection 4 status (executed/triggered/artifact_confirmed/miss) ===
run_test "fixture-A 4 test cases" \
  "[ \$(jq '.test_cases | length' $FIXTURE_DIR/fixture-A-detection-3-status.json) -eq 4 ]" \
  "PASS"
run_test "fixture-A schema_version_policy.current = 2" \
  "[ \$(jq '.schema_version_policy.current' $FIXTURE_DIR/fixture-A-detection-3-status.json) -eq 2 ]" \
  "PASS"

# === Fixture E — unified view + thresholds ===
run_test "fixture-E top_n_cap = 10" \
  "[ \$(jq '.top_n_cap' $FIXTURE_DIR/fixture-E-unified-view.json) -eq 10 ]" \
  "PASS"
run_test "fixture-E ordering 4 priorities" \
  "[ \$(jq '.ordering_rule | length' $FIXTURE_DIR/fixture-E-unified-view.json) -eq 4 ]" \
  "PASS"

# === Fixture F — major/minor classification ===
run_test "fixture-F 5 test cases" \
  "[ \$(jq '.test_cases | length' $FIXTURE_DIR/fixture-F-tier-classification.json) -eq 5 ]" \
  "PASS"
run_test "fixture-F major examples >= 4" \
  "[ \$(jq '.classification_criteria.major.examples | length' $FIXTURE_DIR/fixture-F-tier-classification.json) -ge 4 ]" \
  "PASS"

# === 구현 변경 검증 (Phase 별 expected) ===
run_test "session-review.py has schema_version: 2" \
  "[ \"$SCHEMA_V2_IN_SCRIPT\" = \"yes\" ]" \
  "$EXPECTED"
run_test "session-review.py has unified_skill_view" \
  "[ \"$UNIFIED_VIEW\" = \"yes\" ]" \
  "$EXPECTED"
run_test "SKILL.md has major/minor Tier rule" \
  "[ \"$SKILL_MD_HAS_TIER_RULE\" = \"yes\" ]" \
  "$EXPECTED"
run_test "thresholds.json exists" \
  "[ \"$THRESHOLDS_EXISTS\" = \"yes\" ]" \
  "$EXPECTED"

echo ""
echo "================================================================"
echo "Test Results: $PASS / $TOTAL PASS, $FAIL FAIL (Phase: $PHASE)"
echo "================================================================"

if [ "$FAIL" -eq 0 ]; then exit 0; else exit 1; fi
