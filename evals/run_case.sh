#!/usr/bin/env bash
# Run one review-kit (or control) review headlessly against a fixture branch.
#   ./run_case.sh <fixture> <branch> <run-name> "<prompt>"     e.g. ./run_case.sh cs-orders feature/cancel-order deep-cs "/rk:deep"
#   NOPLUGIN=1 ./run_case.sh ... "/code-review"                 control run with Claude Code's built-in reviewer
# Fixtures are extracted from fixtures.tgz, plus the harder Python set built from ./hard
# (build_hard_fixtures.py), on first use. Results land in ./runs/<run-name>/report.md, with
# wall-clock seconds and cost in ./runs/<run-name>/status.json. See run_hard.sh for the whole set.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; PLUGIN="$(dirname "$HERE")"
EXTRACT_ONLY=0; [ "${1:-}" != --extract-only ] || EXTRACT_ONLY=1
[ "$#" -ge 4 ] || [ "$EXTRACT_ONLY" = 1 ] || { echo 'usage: run_case.sh FIXTURE BRANCH RUN_NAME PROMPT' >&2; exit 2; }
if [ "$EXTRACT_ONLY" = 1 ]; then FIX=x; NAME=x; else
FIX=$1; BR=$2; NAME=$3; shift 3; PROMPT="$*"
fi
[[ "$FIX" =~ ^[a-zA-Z0-9_-]+$ && "$NAME" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'invalid fixture/run name' >&2; exit 2; }
if [ ! -d "$HERE/fixtures" ]; then
  # Extract into a private folder and rename it into place, so parallel runs never see a
  # half-extracted fixtures folder. If another run wins the rename, use its copy.
  TMPFX=$(mktemp -d "$HERE/.fixtures.XXXXXX")
  tar xzf "$HERE/fixtures.tgz" -C "$TMPFX"
  python3 "$HERE/build_hard_fixtures.py" "$TMPFX" >/dev/null
  # os.rename is atomic and refuses a non-empty target on Linux and macOS (mv -T is GNU-only).
  python3 -c 'import os,sys; os.rename(sys.argv[1], sys.argv[2])' "$TMPFX" "$HERE/fixtures" 2>/dev/null || rm -rf "$TMPFX"
fi
[ "$EXTRACT_ONLY" = 0 ] || exit 0
[ -d "$HERE/fixtures/$FIX" ] || { echo "no fixture $FIX in $HERE/fixtures (extracted by an older run_case.sh? delete that folder)" >&2; exit 2; }
OUT="$HERE/runs/$NAME"
mkdir -p "$HERE/runs"
mkdir "$OUT" || { echo "run already exists: $OUT" >&2; exit 2; }
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
        'seconds':s,'api_seconds':round((res.get('duration_api_ms') or 0)/1000),
        'num_turns':res.get('num_turns'),'report':str(out/'report.md')}
(out/'status.json').write_text(json.dumps(status,indent=2))
print(json.dumps(status))
PY
