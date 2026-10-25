#!/usr/bin/env bash
# Run one review-kit (or control) review headlessly against a fixture branch.
#   ./run_case.sh <fixture> <branch> <run-name> "<prompt>"     e.g. ./run_case.sh cs-orders feature/cancel-order deep-cs "/rk:deep"
#   NOPLUGIN=1 ./run_case.sh ... "/code-review"                 control run with Claude Code's built-in reviewer
# Fixtures are extracted from fixtures.tgz on first use. Results land in ./runs/<run-name>/report.md
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; PLUGIN="$(dirname "$HERE")"
[ "$#" -ge 4 ] || { echo 'usage: run_case.sh FIXTURE BRANCH RUN_NAME PROMPT' >&2; exit 2; }
FIX=$1; BR=$2; NAME=$3; shift 3; PROMPT="$*"
[[ "$FIX" =~ ^[a-zA-Z0-9_-]+$ && "$NAME" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'invalid fixture/run name' >&2; exit 2; }
[ -d "$HERE/fixtures" ] || { mkdir -p "$HERE/fixtures"; tar xzf "$HERE/fixtures.tgz" -C "$HERE/fixtures"; }
OUT="$HERE/runs/$NAME"
[ ! -e "$OUT" ] || { echo "run already exists: $OUT" >&2; exit 2; }
mkdir -p "$OUT"
echo '{"execution_status":"failed","reason":"Evaluation has not completed"}' > "$OUT/status.json"
cp -r "$HERE/fixtures/$FIX" "$OUT/$FIX"
cd "$OUT/$FIX"
git checkout -q "$BR"
command -v claude >/dev/null || { echo 'claude CLI unavailable' >&2; exit 127; }
date +%s > "$OUT/start"
PLUG=(--plugin-dir "$PLUGIN"); [ "${NOPLUGIN:-}" != 1 ] || PLUG=()
claude --version > "$OUT/claude-version.txt"
claude -p "$PROMPT" "${PLUG[@]}" --dangerously-skip-permissions --output-format stream-json --verbose \
  > "$OUT/stream.jsonl" 2> "$OUT/stderr.txt"
date +%s > "$OUT/end"
python3 - "$OUT" <<'PY'
import json,sys,pathlib
out=pathlib.Path(sys.argv[1]); res=None
for l in (out/'stream.jsonl').read_text().splitlines():
    try: m=json.loads(l)
    except ValueError: continue
    if isinstance(m, dict) and m.get('type')=='result': res=m
if not res or res.get('is_error') is not False or res.get('subtype') != 'success':
    sys.exit('No successful Claude result; evaluation failed')
report=res.get('result')
if not isinstance(report,str) or not report.strip():
    sys.exit('Claude returned an empty report; evaluation failed')
(out/'report.md').write_text(report)
s=int((out/'end').read_text())-int((out/'start').read_text())
status={'execution_status':'completed','cost_usd':res.get('total_cost_usd'),
        'seconds':s,'report':str(out/'report.md')}
(out/'status.json').write_text(json.dumps(status,indent=2))
print(json.dumps(status))
PY
