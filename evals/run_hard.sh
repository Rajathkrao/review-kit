#!/usr/bin/env bash
# Run one prompt over the harder Python eval set and print a scored summary.
#   ./run_hard.sh TAG "<prompt>" [CASE ...]      e.g. ./run_hard.sh quick-v4 "/rk:quick"
#   JOBS=8 ./run_hard.sh deep-v4 "/rk:deep"      parallel runs (default 4)
#   NOPLUGIN=1 ./run_hard.sh builtin "/code-review"
# CASE is fixture:branch from answer-keys.json; default: every case with "set": "hard".
# Runs land in ./runs/TAG__<fixture>__<branch>/; rescore any time with ./score.py --suite TAG.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[ "$#" -ge 2 ] || { echo 'usage: run_hard.sh TAG PROMPT [CASE ...]' >&2; exit 2; }
TAG=$1; PROMPT=$2; shift 2
[[ "$TAG" =~ ^[a-zA-Z0-9-]+$ ]] || { echo 'TAG: letters, digits and dashes only' >&2; exit 2; }
if [ "$#" -gt 0 ]; then CASES=("$@"); else
  mapfile -t CASES < <(python3 -c 'import json,sys; [print(k) for k,v in json.load(open(sys.argv[1])).items() if v.get("set")=="hard"]' "$HERE/answer-keys.json")
fi
# Extract once up front so the parallel runs below never race on it.
"$HERE/run_case.sh" --extract-only
mkdir -p "$HERE/runs"
for c in "${CASES[@]}"; do
  FIX=${c%%:*}; BR=${c#*:}; NAME="${TAG}__${FIX}__${BR//\//_}"
  while [ "$(jobs -rp | wc -l)" -ge "${JOBS:-4}" ]; do wait -n || true; done
  ( "$HERE/run_case.sh" "$FIX" "$BR" "$NAME" "$PROMPT" > "$HERE/runs/.$NAME.log" 2>&1 \
      && echo "done   $c" || echo "FAILED $c (see runs/.$NAME.log, runs/$NAME/stderr.txt)" ) &
done
wait
python3 "$HERE/score.py" --suite "$TAG"
