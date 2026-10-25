#!/usr/bin/env bash
# Run one review-kit (or control) review headlessly against a fixture branch.
#   ./run_case.sh <fixture> <branch> <run-name> "<prompt>"     e.g. ./run_case.sh cs-orders feature/cancel-order deep-cs "/rk:deep"
#   NOPLUGIN=1 ./run_case.sh ... "/code-review"                 control run with Claude Code's built-in reviewer
# Fixtures are extracted from fixtures.tgz on first use. Results land in ./runs/<run-name>/report.md
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; PLUGIN="$(dirname "$HERE")"
FIX=$1; BR=$2; NAME=$3; shift 3; PROMPT="$*"
[ -d "$HERE/fixtures" ] || { mkdir -p "$HERE/fixtures" && tar xzf "$HERE/fixtures.tgz" -C "$HERE/fixtures"; }
OUT="$HERE/runs/$NAME"; rm -rf "$OUT"; mkdir -p "$OUT"
cp -r "$HERE/fixtures/$FIX" "$OUT/$FIX"; cd "$OUT/$FIX" && git checkout -q "$BR"
date +%s > "$OUT/start"
PLUG=(--plugin-dir "$PLUGIN"); [ "${NOPLUGIN:-}" = 1 ] && PLUG=()
claude -p "$PROMPT" "${PLUG[@]}" --dangerously-skip-permissions --output-format stream-json --verbose \
  > "$OUT/stream.jsonl" 2> "$OUT/stderr.txt"
date +%s > "$OUT/end"
python3 - "$OUT" <<'PY'
import json,sys,pathlib
out=pathlib.Path(sys.argv[1]); res=None
for l in (out/'stream.jsonl').read_text().splitlines():
    try: m=json.loads(l)
    except Exception: continue
    if m.get('type')=='result': res=m
(out/'report.md').write_text((res or {}).get('result',''))
s=int((out/'end').read_text())-int((out/'start').read_text())
print(json.dumps({'cost_usd':(res or {}).get('total_cost_usd'),'seconds':s,'report':str(out/'report.md')}))
PY
