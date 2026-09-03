#!/usr/bin/env bash
# AURA-EVAL final acceptance test.
# Project -> SOP -> workflow -> run -> plan/generate/evaluate/refine/approve
#         -> dataset -> download JSONL
# Usage:  API=http://localhost:8000 bash scripts/acceptance.sh
set -euo pipefail

API="${API:-http://localhost:8000}"
OUT="${OUT:-./.acceptance}"
mkdir -p "$OUT"

jqr() { python3 -c "import sys,json;d=json.load(sys.stdin);print(eval('d'+sys.argv[1]))" "$1"; }
step() { printf '\n\033[36m▶ %s\033[0m\n' "$1"; }

step "0/8 Health"
curl -fsS "$API/api/health" | tee "$OUT/health.json" >/dev/null
curl -fsS "$API/api/health/database" >/dev/null
curl -fsS "$API/api/health/llm" >/dev/null
echo "  health, database and llm probes OK"

step "1/8 Create project"
PROJECT=$(curl -fsS -X POST "$API/api/projects" -H 'content-type: application/json' \
  -d '{"name":"Acceptance Project","description":"Created by scripts/acceptance.sh"}')
PROJECT_ID=$(echo "$PROJECT" | jqr "['id']")
echo "  project_id=$PROJECT_ID"

step "2/8 Create SOP (versioned)"
SOP=$(curl -fsS -X POST "$API/api/sops" -H 'content-type: application/json' -d "{
  \"name\":\"Acceptance SOP\",
  \"description\":\"Quality rules for Python Q&A samples\",
  \"project_id\":\"$PROJECT_ID\",
  \"threshold\":70,
  \"rules\":[
    {\"id\":\"r1\",\"text\":\"Answer must be factually correct and runnable.\",\"criterion\":\"correctness\",\"severity\":\"critical\",\"weight\":2.0},
    {\"id\":\"r2\",\"text\":\"Answer must directly address the question asked.\",\"criterion\":\"relevance\",\"severity\":\"major\",\"weight\":1.5},
    {\"id\":\"r3\",\"text\":\"Answer must include a short worked example.\",\"criterion\":\"completeness\",\"severity\":\"major\",\"weight\":1.0},
    {\"id\":\"r4\",\"text\":\"No unsafe, harmful or destructive code.\",\"criterion\":\"safety\",\"severity\":\"critical\",\"weight\":2.0}
  ]}")
SOP_ID=$(echo "$SOP" | jqr "['id']")
echo "  sop_id=$SOP_ID version=$(echo "$SOP" | jqr "['current_version']")"

step "3/8 Create workflow"
WORKFLOW=$(curl -fsS -X POST "$API/api/workflows" -H 'content-type: application/json' -d "{
  \"project_id\":\"$PROJECT_ID\",
  \"name\":\"Acceptance Workflow\",
  \"objective\":\"Generate high-quality Python question/answer training samples\",
  \"sop_id\":\"$SOP_ID\",
  \"config\":{\"sample_count\":6,\"judges\":3,\"max_retries\":2,\"dataset_style\":\"instruction\",
             \"dataset_formats\":[\"jsonl\",\"json\",\"csv\"],\"mock_failure_rate\":0.1}}")
WORKFLOW_ID=$(echo "$WORKFLOW" | jqr "['id']")
echo "  workflow_id=$WORKFLOW_ID"

step "4/8 Trigger run (async, expect 202 + run_id)"
RUN=$(curl -fsS -X POST "$API/api/workflows/$WORKFLOW_ID/run" -H 'content-type: application/json' -d '{}')
RUN_ID=$(echo "$RUN" | jqr "['id']")
echo "  run_id=$RUN_ID status=$(echo "$RUN" | jqr "['status']")"

step "5/8 Drive run to completion (serverless-safe /advance loop)"
STATUS=PENDING
for i in $(seq 1 120); do
  ST=$(curl -fsS "$API/api/runs/$RUN_ID/status")
  STATUS=$(echo "$ST" | jqr "['status']")
  printf '\r  step=%s status=%s   ' "$(echo "$ST" | jqr "['steps_executed']")" "$STATUS"
  case "$STATUS" in
    COMPLETED|FAILED|STOPPED) break ;;
  esac
  curl -fsS -X POST "$API/api/runs/$RUN_ID/advance" -H 'content-type: application/json' \
       -d '{"max_steps":25}' >/dev/null || true
  sleep 1
done
echo
[ "$STATUS" = "COMPLETED" ] || { echo "✗ run ended as $STATUS"; exit 1; }

curl -fsS "$API/api/runs/$RUN_ID" > "$OUT/run.json"
echo "  agents exercised:"
curl -fsS "$API/api/runs/$RUN_ID/trace" > "$OUT/trace.json"
python3 - "$OUT/trace.json" <<'PY'
import json,sys,collections
spans=json.load(open(sys.argv[1]))
spans=spans.get("spans",spans) if isinstance(spans,dict) else spans
c=collections.Counter(s.get("agent") or s.get("node") for s in spans)
for k,v in c.most_common(): print(f"    {k:<16} {v} span(s)")
for need in ("planner","generator","evaluator","approval"):
    assert any(need in str(k or "") for k in c), f"missing agent: {need}"
print("    ✓ planner / generator / evaluator / approval all executed")
PY

step "6/8 Samples & approval statuses"
curl -fsS "$API/api/samples?run_id=$RUN_ID&limit=100" > "$OUT/samples.json"
python3 - "$OUT/samples.json" <<'PY'
import json,sys,collections
d=json.load(open(sys.argv[1])); items=d.get("items",d) if isinstance(d,dict) else d
c=collections.Counter(s["status"] for s in items)
print("   ",dict(c))
assert items, "no samples produced"
PY

step "7/8 Build dataset"
DATASET=$(curl -fsS -X POST "$API/api/datasets" -H 'content-type: application/json' \
  -d "{\"run_id\":\"$RUN_ID\",\"name\":\"acceptance-dataset\",\"style\":\"instruction\",\"formats\":[\"jsonl\",\"json\",\"csv\"]}")
DATASET_ID=$(echo "$DATASET" | jqr "['id']")
echo "  dataset_id=$DATASET_ID rows=$(echo "$DATASET" | jqr "['row_count']")"

step "8/8 Download JSONL"
curl -fsS "$API/api/datasets/$DATASET_ID/download?format=jsonl" -o "$OUT/dataset.jsonl"
LINES=$(wc -l < "$OUT/dataset.jsonl")
python3 - "$OUT/dataset.jsonl" <<'PY'
import json,sys
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
assert rows, "empty JSONL"
print(f"    {len(rows)} valid JSON lines; keys = {sorted(rows[0].keys())}")
PY
echo "  saved $OUT/dataset.jsonl ($LINES lines)"

printf '\n\033[32m✓ ACCEPTANCE TEST PASSED\033[0m — artifacts in %s\n' "$OUT"
