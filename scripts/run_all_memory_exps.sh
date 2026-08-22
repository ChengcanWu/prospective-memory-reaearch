#!/usr/bin/env bash
# Sequential PM-Bench runs with the fixed pm_memory implementation.
# Continues on failure so one bad setup does not block the rest.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Shared venv lives in the sibling project; override with VENV if it moves.
VENV="${VENV:-/Users/cyanie/machine learning/Content_条件延迟记忆_2/.venv}"
source "$VENV/bin/activate"
cd "$ROOT"
export PYTHONPATH="code:third_party/amem-paper:third_party/mem0-main:data/PMBench/sim:${PYTHONPATH:-}"
export MEM0_TELEMETRY=False
export POSTHOG_DISABLED=1
LOGDIR="$ROOT/data/PMBench/runs/fixed_mem_$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOGDIR"
echo "LOGDIR=$LOGDIR" | tee "$LOGDIR/master.log"

summarize_memory() {
  local memfile="$1"
  local label="$2"
  python - "$memfile" "$label" "$LOGDIR/master.log" <<'PY'
import json, sys
from collections import Counter
path, label, master = sys.argv[1:4]
from pathlib import Path
p = Path(path)
if not p.exists():
    line = f"[mem-check] {label}: NO memory jsonl at {path}"
    print(line)
    Path(master).open("a").write(line + "\n")
    raise SystemExit(0)
ev = Counter(); errs = Counter(); zero = nonzero = 0
for raw in p.open():
    o = json.loads(raw)
    ev[o.get("event")] += 1
    if "error" in (o.get("event") or ""):
        errs[f"{o.get('error_type')}: {str(o.get('error'))[:100]}"] += 1
    if o.get("event") == "recall":
        if o.get("memory_chars", 0):
            nonzero += 1
        else:
            zero += 1
line = f"[mem-check] {label}: events={dict(ev)} recall_zero={zero} recall_nonzero={nonzero}"
print(line)
Path(master).open("a").write(line + "\n")
if errs:
    eline = f"[mem-check] {label}: ERRORS {dict(errs.most_common(5))}"
    print(eline)
    Path(master).open("a").write(eline + "\n")
PY
}

run_one() {
  local provider="$1"
  local setup="$2"
  shift 2
  local stamp
  stamp="$(date +%Y%m%d-%H%M%S)"
  local logfile="$LOGDIR/${provider}_${setup}_${stamp}.log"
  echo "==== START $provider $setup @ $stamp ====" | tee -a "$LOGDIR/master.log"
  set +e
  python code/run_pm_memory.py --provider "$provider" --setup "$setup" "$@" 2>&1 | tee "$logfile"
  local code=${PIPESTATUS[0]}
  set -e
  # Locate newest matching memory jsonl for this setup/provider
  local out_root
  if [[ "$provider" == "deepseek" ]]; then
    out_root="$ROOT/data/PMBench/runs/local_deepseek"
  else
    out_root="$ROOT/data/PMBench/runs/local_qwen35"
  fi
  local memfile
  memfile="$(find "$out_root" -name "*.memory.jsonl" -type f 2>/dev/null | xargs ls -t 2>/dev/null | head -1 || true)"
  if [[ -n "${memfile:-}" ]]; then
    summarize_memory "$memfile" "${provider}_${setup}"
  fi
  if [[ $code -eq 0 ]]; then
    echo "==== OK $provider $setup ====" | tee -a "$LOGDIR/master.log"
  else
    echo "==== FAIL $provider $setup (exit $code) ====" | tee -a "$LOGDIR/master.log"
  fi
  return 0
}

# DeepSeek
run_one deepseek baseline
run_one deepseek mem0
run_one deepseek amem

# Qwen
run_one qwen baseline
run_one qwen mem0 --use-qwen-embed
run_one qwen amem

echo "ALL_DONE" | tee -a "$LOGDIR/master.log"
