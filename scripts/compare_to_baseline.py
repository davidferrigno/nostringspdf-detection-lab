#!/usr/bin/env python3
"""
compare_to_baseline.py

Diffs two benchmark runs and surfaces per-PDF precision/recall deltas.
The readout layer that turns "the heuristic backend scored 0.92" into
"the heuristic backend regressed on irs_2848 by 0.12 precision and
improved uscis_n400 by 0.04."

Use cases:

1. After running a new backend: compare it against the canonical
   acroform_self baseline to understand where it differs.

2. After tuning a backend: compare today's run against last week's to
   verify the tuning helped (or did not regress unrelated PDFs).

3. After re-extracting ground truth: compare a previous backend run
   against a fresh self-match to confirm scoring is still stable.

Inputs:
  - --baseline: benchmark run directory (or run_id) for the reference
  - --candidate: benchmark run directory (or run_id) being evaluated
  - Defaults: baseline=latest acroform_self run, candidate=latest non-baseline

Outputs:
  - reports/comparisons/<timestamp>_<baseline_id>_vs_<candidate_id>/
      comparison.json   Per-PDF + aggregate deltas
      comparison.csv    Per-PDF table
      comparison.md     Human-readable summary with classification:
                         IMPROVED / REGRESSED / UNCHANGED / NEW_ERROR

Guardrails:
- READ-ONLY access to benchmark scorecards
- All writes confined to reports/comparisons/
- assert_safe_output_path() refuses path traversal
- --dry-run mode reports without writing
- Significance thresholds configurable (default: 0.01 for precision/recall)

Usage:
    # Default: compare latest non-acroform_self run against latest acroform_self
    python scripts/compare_to_baseline.py

    # Explicit run IDs
    python scripts/compare_to_baseline.py \\
        --baseline 2026-05-20_205642_acroform_self \\
        --candidate 2026-05-21_140000_heuristic_lab_v1

    # Adjust significance threshold
    python scripts/compare_to_baseline.py --threshold 0.005
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_REPORTS_DIR = ROOT / "reports" / "benchmarks"
COMPARISONS_DIR = ROOT / "reports" / "comparisons"


def assert_safe_output_path(path: Path) -> None:
    resolved = path.resolve()
    expected = COMPARISONS_DIR.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError:
        raise RuntimeError(f"Refused to write outside {expected}: {resolved}")


# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------

def list_benchmark_runs() -> list[Path]:
    """All benchmark run directories sorted by mtime (newest first)."""
    if not BENCHMARK_REPORTS_DIR.exists():
        return []
    runs = [p for p in BENCHMARK_REPORTS_DIR.iterdir() if p.is_dir()]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_run(run_arg: str | None, prefer_backend: str | None = None,
                exclude_backend: str | None = None) -> Path | None:
    """
    Resolve a run argument to a directory. Three modes:
    - run_arg is a full path → use it directly
    - run_arg is a run_id (directory name in reports/benchmarks/) → resolve
    - run_arg is None → auto-discover using prefer_backend/exclude_backend
    """
    if run_arg:
        # Try as directory name in reports/benchmarks/
        direct = BENCHMARK_REPORTS_DIR / run_arg
        if direct.exists() and direct.is_dir():
            return direct
        # Try as direct path
        as_path = Path(run_arg)
        if as_path.exists() and as_path.is_dir():
            return as_path
        return None

    runs = list_benchmark_runs()
    for run in runs:
        scorecard = run / "scorecard.json"
        if not scorecard.exists():
            continue
        try:
            agg = json.loads(scorecard.read_text())["aggregate"]
            backend = agg["backend"]
        except Exception:
            continue
        if prefer_backend and backend == prefer_backend:
            return run
        if exclude_backend and backend != exclude_backend:
            return run
        if not prefer_backend and not exclude_backend:
            return run
    return None


# ---------------------------------------------------------------------------
# Load scorecard
# ---------------------------------------------------------------------------

def load_scorecard(run_dir: Path) -> dict:
    sc = json.loads((run_dir / "scorecard.json").read_text())
    sc["_run_dir"] = str(run_dir.relative_to(ROOT))
    return sc


def index_by_pdf_id(scorecard: dict) -> dict:
    return {entry["pdf_id"]: entry for entry in scorecard["per_pdf"]}


# ---------------------------------------------------------------------------
# Diff logic
# ---------------------------------------------------------------------------

def classify_change(delta_p: float | None, delta_r: float | None,
                    has_baseline_error: bool, has_candidate_error: bool,
                    threshold: float) -> str:
    """
    Classify the per-PDF change category:
      NEW_ERROR     - candidate has an error baseline didn't
      ERROR_FIXED   - baseline had error, candidate doesn't
      BOTH_ERROR    - both runs errored
      BOTH_NA       - exists in both but no metrics either side (data gap)
      IMPROVED      - both p and r improved by >= threshold (no regressions)
      REGRESSED     - either p or r regressed by >= threshold
      MIXED         - one improved, one regressed (both > threshold)
      UNCHANGED     - within threshold both directions
    """
    if has_baseline_error and has_candidate_error:
        return "BOTH_ERROR"
    if has_baseline_error and not has_candidate_error:
        return "ERROR_FIXED"
    if has_candidate_error and not has_baseline_error:
        return "NEW_ERROR"
    if delta_p is None or delta_r is None:
        return "BOTH_NA"

    p_improved = delta_p >= threshold
    p_regressed = delta_p <= -threshold
    r_improved = delta_r >= threshold
    r_regressed = delta_r <= -threshold

    if (p_improved or r_improved) and (p_regressed or r_regressed):
        return "MIXED"
    if p_regressed or r_regressed:
        return "REGRESSED"
    if p_improved or r_improved:
        return "IMPROVED"
    return "UNCHANGED"


def diff_per_pdf(baseline: dict, candidate: dict, threshold: float) -> list[dict]:
    """
    For each pdf_id appearing in either run, compute deltas.
    """
    baseline_by_id = index_by_pdf_id(baseline)
    candidate_by_id = index_by_pdf_id(candidate)
    all_ids = sorted(set(baseline_by_id.keys()) | set(candidate_by_id.keys()))

    diffs = []
    for pdf_id in all_ids:
        b = baseline_by_id.get(pdf_id)
        c = candidate_by_id.get(pdf_id)
        diff = {"pdf_id": pdf_id}

        # Track presence
        diff["in_baseline"] = b is not None
        diff["in_candidate"] = c is not None
        diff["baseline_error"] = bool(b and b.get("error"))
        diff["candidate_error"] = bool(c and c.get("error"))

        if b and "metrics" in b:
            bm = b["metrics"]
            diff["baseline"] = {
                "tp": bm["tp"], "fp": bm["fp"], "fn": bm["fn"],
                "precision": bm["precision"], "recall": bm["recall"], "f1": bm["f1"],
                "type_accuracy": bm["type_accuracy"],
                "detected_count": bm["detected_count"],
                "ground_truth_count": bm["ground_truth_count"],
            }
        else:
            diff["baseline"] = None

        if c and "metrics" in c:
            cm = c["metrics"]
            diff["candidate"] = {
                "tp": cm["tp"], "fp": cm["fp"], "fn": cm["fn"],
                "precision": cm["precision"], "recall": cm["recall"], "f1": cm["f1"],
                "type_accuracy": cm["type_accuracy"],
                "detected_count": cm["detected_count"],
                "ground_truth_count": cm["ground_truth_count"],
            }
        else:
            diff["candidate"] = None

        if diff["baseline"] and diff["candidate"]:
            diff["delta_precision"] = round(
                diff["candidate"]["precision"] - diff["baseline"]["precision"], 4
            )
            diff["delta_recall"] = round(
                diff["candidate"]["recall"] - diff["baseline"]["recall"], 4
            )
            diff["delta_f1"] = round(
                diff["candidate"]["f1"] - diff["baseline"]["f1"], 4
            )
            diff["delta_tp"] = diff["candidate"]["tp"] - diff["baseline"]["tp"]
            diff["delta_fp"] = diff["candidate"]["fp"] - diff["baseline"]["fp"]
            diff["delta_fn"] = diff["candidate"]["fn"] - diff["baseline"]["fn"]
            diff["delta_detected"] = (
                diff["candidate"]["detected_count"] - diff["baseline"]["detected_count"]
            )
        else:
            diff["delta_precision"] = None
            diff["delta_recall"] = None
            diff["delta_f1"] = None
            diff["delta_tp"] = None
            diff["delta_fp"] = None
            diff["delta_fn"] = None
            diff["delta_detected"] = None

        diff["classification"] = classify_change(
            diff["delta_precision"], diff["delta_recall"],
            diff["baseline_error"], diff["candidate_error"], threshold
        )

        diffs.append(diff)

    return diffs


def aggregate_summary(baseline: dict, candidate: dict, diffs: list[dict], threshold: float) -> dict:
    """Compute overall counts by classification."""
    counts = {
        "UNCHANGED": 0, "IMPROVED": 0, "REGRESSED": 0, "MIXED": 0,
        "NEW_ERROR": 0, "ERROR_FIXED": 0, "BOTH_ERROR": 0, "BOTH_NA": 0,
    }
    for d in diffs:
        counts[d["classification"]] = counts.get(d["classification"], 0) + 1

    b_agg = baseline["aggregate"]
    c_agg = candidate["aggregate"]

    return {
        "baseline_run_id": b_agg.get("run_id"),
        "baseline_backend": b_agg.get("backend"),
        "candidate_run_id": c_agg.get("run_id"),
        "candidate_backend": c_agg.get("backend"),
        "iou_threshold": b_agg.get("iou_threshold"),
        "significance_threshold": threshold,
        "pdfs_in_baseline": b_agg.get("pdfs_processed", 0),
        "pdfs_in_candidate": c_agg.get("pdfs_processed", 0),
        "pdfs_compared": len(diffs),
        "classification_counts": counts,
        "baseline_aggregate_precision": b_agg.get("aggregate_precision"),
        "baseline_aggregate_recall": b_agg.get("aggregate_recall"),
        "baseline_aggregate_f1": b_agg.get("aggregate_f1"),
        "candidate_aggregate_precision": c_agg.get("aggregate_precision"),
        "candidate_aggregate_recall": c_agg.get("aggregate_recall"),
        "candidate_aggregate_f1": c_agg.get("aggregate_f1"),
        "delta_aggregate_precision": round(
            (c_agg.get("aggregate_precision") or 0) - (b_agg.get("aggregate_precision") or 0), 4
        ),
        "delta_aggregate_recall": round(
            (c_agg.get("aggregate_recall") or 0) - (b_agg.get("aggregate_recall") or 0), 4
        ),
        "delta_aggregate_f1": round(
            (c_agg.get("aggregate_f1") or 0) - (b_agg.get("aggregate_f1") or 0), 4
        ),
    }


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def write_comparison_reports(diffs: list[dict], summary: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    assert_safe_output_path(output_dir)

    # JSON
    json_path = output_dir / "comparison.json"
    assert_safe_output_path(json_path)
    json_path.write_text(json.dumps({"summary": summary, "per_pdf": diffs}, indent=2))

    # CSV
    csv_path = output_dir / "comparison.csv"
    assert_safe_output_path(csv_path)
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pdf_id", "classification",
            "baseline_precision", "baseline_recall", "baseline_f1",
            "candidate_precision", "candidate_recall", "candidate_f1",
            "delta_precision", "delta_recall", "delta_f1",
            "baseline_tp", "baseline_fp", "baseline_fn",
            "candidate_tp", "candidate_fp", "candidate_fn",
            "delta_tp", "delta_fp", "delta_fn", "delta_detected",
            "baseline_error", "candidate_error",
        ])
        for d in diffs:
            b = d["baseline"] or {}
            c = d["candidate"] or {}
            w.writerow([
                d["pdf_id"], d["classification"],
                b.get("precision", ""), b.get("recall", ""), b.get("f1", ""),
                c.get("precision", ""), c.get("recall", ""), c.get("f1", ""),
                d.get("delta_precision", "") if d.get("delta_precision") is not None else "",
                d.get("delta_recall", "") if d.get("delta_recall") is not None else "",
                d.get("delta_f1", "") if d.get("delta_f1") is not None else "",
                b.get("tp", ""), b.get("fp", ""), b.get("fn", ""),
                c.get("tp", ""), c.get("fp", ""), c.get("fn", ""),
                d.get("delta_tp", "") if d.get("delta_tp") is not None else "",
                d.get("delta_fp", "") if d.get("delta_fp") is not None else "",
                d.get("delta_fn", "") if d.get("delta_fn") is not None else "",
                d.get("delta_detected", "") if d.get("delta_detected") is not None else "",
                1 if d["baseline_error"] else 0,
                1 if d["candidate_error"] else 0,
            ])

    # Markdown
    md_path = output_dir / "comparison.md"
    assert_safe_output_path(md_path)
    lines = []
    lines.append(f"# Benchmark Comparison")
    lines.append("")
    lines.append(f"**Baseline:** `{summary['baseline_run_id']}` ({summary['baseline_backend']})")
    lines.append(f"**Candidate:** `{summary['candidate_run_id']}` ({summary['candidate_backend']})")
    lines.append(f"**Significance threshold:** {summary['significance_threshold']}")
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| Metric | Baseline | Candidate | Delta |")
    lines.append("| --- | ---: | ---: | ---: |")
    lines.append(
        f"| Precision | {summary['baseline_aggregate_precision']} | "
        f"{summary['candidate_aggregate_precision']} | "
        f"**{summary['delta_aggregate_precision']:+.4f}** |"
    )
    lines.append(
        f"| Recall    | {summary['baseline_aggregate_recall']} | "
        f"{summary['candidate_aggregate_recall']} | "
        f"**{summary['delta_aggregate_recall']:+.4f}** |"
    )
    lines.append(
        f"| F1        | {summary['baseline_aggregate_f1']} | "
        f"{summary['candidate_aggregate_f1']} | "
        f"**{summary['delta_aggregate_f1']:+.4f}** |"
    )
    lines.append("")
    lines.append("## Classification Counts")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("| --- | ---: |")
    for cat in ["UNCHANGED", "IMPROVED", "REGRESSED", "MIXED",
                "NEW_ERROR", "ERROR_FIXED", "BOTH_ERROR", "BOTH_NA"]:
        n = summary["classification_counts"].get(cat, 0)
        lines.append(f"| {cat} | {n} |")
    lines.append("")
    lines.append("## Per-PDF Detail")
    lines.append("")
    lines.append("| PDF | Class | P-base | P-cand | ΔP | R-base | R-cand | ΔR | ΔTP | ΔFP | ΔFN |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    # Sort: errors first, then regressions, then mixed, then improvements, then unchanged
    sort_key = {
        "NEW_ERROR": 0, "BOTH_ERROR": 1, "BOTH_NA": 2,
        "REGRESSED": 3, "MIXED": 4, "IMPROVED": 5,
        "ERROR_FIXED": 6, "UNCHANGED": 7,
    }
    sorted_diffs = sorted(diffs, key=lambda d: (sort_key.get(d["classification"], 99), d["pdf_id"]))

    for d in sorted_diffs:
        b = d["baseline"] or {}
        c = d["candidate"] or {}
        dp = d.get("delta_precision")
        dr = d.get("delta_recall")
        dp_str = f"{dp:+.4f}" if dp is not None else "—"
        dr_str = f"{dr:+.4f}" if dr is not None else "—"
        dtp = d.get("delta_tp")
        dfp = d.get("delta_fp")
        dfn = d.get("delta_fn")
        lines.append(
            f"| `{d['pdf_id']}` | {d['classification']} | "
            f"{b.get('precision', '—')} | {c.get('precision', '—')} | {dp_str} | "
            f"{b.get('recall', '—')} | {c.get('recall', '—')} | {dr_str} | "
            f"{dtp if dtp is not None else '—'} | "
            f"{dfp if dfp is not None else '—'} | "
            f"{dfn if dfn is not None else '—'} |"
        )

    md_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default=None,
                        help="Baseline run id or path (default: latest acroform_self run)")
    parser.add_argument("--candidate", default=None,
                        help="Candidate run id or path (default: latest non-acroform_self run; "
                             "if none exists, latest acroform_self for sanity check)")
    parser.add_argument("--threshold", type=float, default=0.01,
                        help="Significance threshold for IMPROVED/REGRESSED classification "
                             "(default: 0.01)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute deltas without writing reports")
    args = parser.parse_args()

    # Resolve runs
    baseline_dir = resolve_run(args.baseline, prefer_backend="acroform_self")
    if baseline_dir is None:
        print(f"ERROR: could not resolve baseline run.", file=sys.stderr)
        sys.exit(1)

    candidate_dir = resolve_run(args.candidate, exclude_backend="acroform_self")
    if candidate_dir is None:
        # Fall back to the same backend (sanity-check mode)
        candidate_dir = resolve_run(args.candidate, prefer_backend="acroform_self")
        if candidate_dir is None:
            print(f"ERROR: could not resolve candidate run.", file=sys.stderr)
            sys.exit(1)

    if baseline_dir == candidate_dir:
        print(f"WARNING: baseline and candidate are the same run.")
        print(f"   This is a sanity-check comparison — expect zero deltas.")

    print(f"{'='*72}")
    print(f"compare_to_baseline.py")
    if args.dry_run:
        print("MODE: DRY RUN -- no reports will be written")
    print(f"Baseline:  {baseline_dir.relative_to(ROOT)}")
    print(f"Candidate: {candidate_dir.relative_to(ROOT)}")
    print(f"Significance threshold: {args.threshold}")
    print(f"{'='*72}")

    baseline = load_scorecard(baseline_dir)
    candidate = load_scorecard(candidate_dir)

    diffs = diff_per_pdf(baseline, candidate, args.threshold)
    summary = aggregate_summary(baseline, candidate, diffs, args.threshold)

    # Print summary
    print(f"\n--- Aggregate ---")
    print(
        f"Precision: {summary['baseline_aggregate_precision']:.4f} -> "
        f"{summary['candidate_aggregate_precision']:.4f} "
        f"({summary['delta_aggregate_precision']:+.4f})"
    )
    print(
        f"Recall:    {summary['baseline_aggregate_recall']:.4f} -> "
        f"{summary['candidate_aggregate_recall']:.4f} "
        f"({summary['delta_aggregate_recall']:+.4f})"
    )
    print(
        f"F1:        {summary['baseline_aggregate_f1']:.4f} -> "
        f"{summary['candidate_aggregate_f1']:.4f} "
        f"({summary['delta_aggregate_f1']:+.4f})"
    )

    print(f"\n--- Classification ---")
    counts = summary["classification_counts"]
    for cat in ["UNCHANGED", "IMPROVED", "REGRESSED", "MIXED",
                "NEW_ERROR", "ERROR_FIXED", "BOTH_ERROR", "BOTH_NA"]:
        n = counts.get(cat, 0)
        marker = ""
        if cat == "REGRESSED" and n > 0:
            marker = "  <-- REGRESSIONS"
        elif cat == "NEW_ERROR" and n > 0:
            marker = "  <-- NEW ERRORS"
        elif cat == "MIXED" and n > 0:
            marker = "  <-- INVESTIGATE"
        print(f"  {cat:13s}: {n:3d}{marker}")

    # Show specific PDFs in interesting categories
    for cat in ["NEW_ERROR", "REGRESSED", "MIXED"]:
        relevant = [d for d in diffs if d["classification"] == cat]
        if not relevant:
            continue
        print(f"\n--- {cat} details ---")
        for d in relevant[:20]:  # cap at 20 per category for display
            dp = d.get("delta_precision")
            dr = d.get("delta_recall")
            dp_str = f"{dp:+.4f}" if dp is not None else "—"
            dr_str = f"{dr:+.4f}" if dr is not None else "—"
            print(f"  {d['pdf_id']:30s}  ΔP={dp_str}  ΔR={dr_str}")
        if len(relevant) > 20:
            print(f"  ... and {len(relevant) - 20} more")

    # Write reports
    if not args.dry_run:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        baseline_id = baseline["aggregate"].get("run_id", baseline_dir.name)
        candidate_id = candidate["aggregate"].get("run_id", candidate_dir.name)
        # Compact directory name
        output_name = f"{timestamp}_vs_baseline"
        output_dir = COMPARISONS_DIR / output_name

        write_comparison_reports(diffs, summary, output_dir)
        print(f"\nReports written: {output_dir.relative_to(ROOT)}/")
        print(f"  - comparison.json")
        print(f"  - comparison.csv")
        print(f"  - comparison.md")
    else:
        print(f"\n(dry-run: no reports written)")

    # Exit code reflects whether we found regressions
    if summary["classification_counts"]["REGRESSED"] > 0 or summary["classification_counts"]["NEW_ERROR"] > 0:
        sys.exit(3)  # informational: regressions found (not a failure)
    sys.exit(0)


if __name__ == "__main__":
    main()
