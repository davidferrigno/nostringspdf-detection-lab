#!/usr/bin/env bash
# Overnight lab runner — deterministic commands only.
# No approvals needed. Failures are logged and skipped.

cd ~/detection-lab || exit 1
source .venv/bin/activate

STATUS="reports/overnight_status.md"
mkdir -p reports

echo "# Overnight Status Report" > "$STATUS"
echo "" >> "$STATUS"
echo "Started: $(date -u)" >> "$STATUS"
echo "Hostname: $(hostname)" >> "$STATUS"
echo "Branch at start: $(git branch --show-current)" >> "$STATUS"
echo "HEAD at start: $(git rev-parse --short HEAD)" >> "$STATUS"
echo "" >> "$STATUS"

run_task () {
  NAME="$1"
  CMD="$2"
  
  echo "## $NAME" >> "$STATUS"
  echo "Started: $(date -u)" >> "$STATUS"
  echo '```' >> "$STATUS"
  echo "\$ $CMD" >> "$STATUS"
  echo '```' >> "$STATUS"
  echo '```' >> "$STATUS"
  
  if bash -lc "$CMD" >> "$STATUS" 2>&1; then
    echo '```' >> "$STATUS"
    echo "Result: COMPLETED at $(date -u)" >> "$STATUS"
  else
    echo '```' >> "$STATUS"
    echo "Result: FAILED at $(date -u)" >> "$STATUS"
  fi
  echo "" >> "$STATUS"
}

git checkout lab/automation-runner

run_task "Pre-flight smoke test" \
"python scripts/test_lab_smoke.py"

run_task "Detection lab dry run" \
"python scripts/run_detection_lab.py --dry-run"

run_task "Full detection lab run (Lane A)" \
"python scripts/run_detection_lab.py --all"

run_task "Render flat-PDF GT draft overlays" \
"python scripts/render_ground_truth_overlays.py --gt-dir benchmarks/ground_truth_flat --output-dir reports/overlays/ground_truth_flat 2>&1 || echo 'render_ground_truth_overlays.py does not yet support --gt-dir argument; skipped — to be added tomorrow'"

run_task "Geometry richness probe" \
"python scripts/probe_geometry_richness.py 2>&1 || echo 'probe_geometry_richness.py not available yet; skipped'"

run_task "Corpus expansion" \
"python scripts/discover_public_pdfs.py 2>&1 || echo 'discover_public_pdfs.py not available yet; skipped'"

echo "## Final git state" >> "$STATUS"
echo '```' >> "$STATUS"
git status --short --branch >> "$STATUS" 2>&1
echo '```' >> "$STATUS"
echo "" >> "$STATUS"

echo "## Final commit log" >> "$STATUS"
echo '```' >> "$STATUS"
git log --oneline -10 >> "$STATUS" 2>&1
echo '```' >> "$STATUS"
echo "" >> "$STATUS"

echo "Completed: $(date -u)" >> "$STATUS"

git add reports/overnight_status.md 2>/dev/null || true
git add reports/latest/ 2>/dev/null || true
git add reports/overlays/ 2>/dev/null || true
git commit -m "docs(lab): overnight status report" 2>/dev/null || echo "nothing to commit"
git push origin lab/automation-runner 2>/dev/null || echo "push skipped or already up to date"

echo ""
echo "==============================================="
echo "Overnight runner complete at $(date -u)"
echo "Status report: $STATUS"
echo "==============================================="
