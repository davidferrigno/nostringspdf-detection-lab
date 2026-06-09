#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

MANIFEST="${1:-corpus/manifest.json}"
OUT="${2:-runs}"
LOG_DIR="$REPO_ROOT/runs/logs"
mkdir -p "$LOG_DIR"

STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_PATH="$LOG_DIR/pipeline-$STAMP.log"

echo "Running lab pipeline..."
echo "Log: $LOG_PATH"

if py -3.13 scripts/run_lab_pipeline.py --manifest "$MANIFEST" --out "$OUT" >"$LOG_PATH" 2>&1; then
  cat "$LOG_PATH"
  echo "Latest scorecard: $REPO_ROOT/$OUT/latest/scorecard.md"
else
  code=$?
  cat "$LOG_PATH"
  echo "Lab pipeline failed with exit code $code" >&2
  exit "$code"
fi
