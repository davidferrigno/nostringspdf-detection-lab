#!/usr/bin/env python3
"""
run_benchmark.py v1.1

Detection benchmark runner. Backends now imported from
scripts/backend_registry.py — single source of truth.

To add a new backend, edit backend_registry.py.
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend_registry import (
    BACKENDS,
    get_backend,
    get_backend_metadata,
    get_lanes_for_backend,
    list_backends,
)


BENCHMARK_VERSION = "v1.1"

ROOT = Path(__file__).resolve().parent.parent
ACROFORM_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"
FLAT_MANIFEST = ROOT / "samples" / "flat" / "manifest.json"
GROUND_TRUTH_DIR = ROOT / "benchmarks" / "ground_truth"
GROUND_TRUTH_FLAT_DIR = ROOT / "benchmarks" / "ground_truth_flat"
REPORTS_DIR = ROOT / "reports" / "benchmarks"


def assert_safe_output_path(path: Path) -> None:
    resolved = path.resolve()
    expected = REPORTS_DIR.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError:
        raise RuntimeError(f"Refused to write outside {expected}: {resolved}")


def iou(box_a: list, box_b: list) -> float:
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    x_left = max(ax, bx)
    y_top = max(ay, by)
    x_right = min(ax + aw, bx + bw)
    y_bottom = min(ay + ah, by + bh)
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    intersection = (x_right - x_left) * (y_bottom - y_top)
    area_a = aw * ah
    area_b = bw * bh
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def match_fields(detected: list, ground_truth: list, iou_threshold: float = 0.5) -> dict:
    detected_by_page = {}
    for i, d in enumerate(detected):
        detected_by_page.setdefault(d["page"], []).append(i)

    candidates = []
    for gt_idx, gt in enumerate(ground_truth):
        candidate_det_indices = detected_by_page.get(gt["page"], [])
        for det_idx in candidate_det_indices:
            score = iou(gt["bbox"], detected[det_idx]["bbox"])
            if score >= iou_threshold:
                candidates.append((score, gt_idx, det_idx))

    candidates.sort(key=lambda x: -x[0])
    claimed_gt = set()
    claimed_det = set()
    tp = []
    type_mismatches = []

    for score, gt_idx, det_idx in candidates:
        if gt_idx in claimed_gt or det_idx in claimed_det:
            continue
        claimed_gt.add(gt_idx)
        claimed_det.add(det_idx)
        gt_type = ground_truth[gt_idx]["type"]
        det_type = detected[det_idx]["type"]
        type_match = gt_type == det_type
        tp.append({
            "gt_idx": gt_idx, "det_idx": det_idx, "iou": round(score, 4),
            "gt_id": ground_truth[gt_idx]["id"], "det_id": detected[det_idx]["id"],
            "gt_type": gt_type, "det_type": det_type, "type_match": type_match,
        })
        if not type_match:
            type_mismatches.append({
                "gt_idx": gt_idx, "det_idx": det_idx,
                "gt_id": ground_truth[gt_idx]["id"], "det_id": detected[det_idx]["id"],
                "gt_type": gt_type, "det_type": det_type,
            })

    fp = [i for i in range(len(detected)) if i not in claimed_det]
    fn = [i for i in range(len(ground_truth)) if i not in claimed_gt]

    return {"iou_threshold": iou_threshold, "tp": tp, "fp": fp, "fn": fn, "type_mismatches": type_mismatches}


def compute_metrics(match_result: dict, detected_count: int, ground_truth_count: int) -> dict:
    tp = len(match_result["tp"])
    fp = len(match_result["fp"])
    fn = len(match_result["fn"])
    type_correct = sum(1 for t in match_result["tp"] if t["type_match"])
    type_mismatches = len(match_result["type_mismatches"])

    precision = tp / detected_count if detected_count > 0 else 0.0
    recall = tp / ground_truth_count if ground_truth_count > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    type_accuracy = type_correct / tp if tp > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn,
        "detected_count": detected_count, "ground_truth_count": ground_truth_count,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "type_correct": type_correct, "type_mismatches": type_mismatches,
        "type_accuracy": round(type_accuracy, 4),
    }


def benchmark_pdf(pdf_path: Path, ground_truth: dict, backend_fn, iou_threshold: float) -> dict:
    pdf_id = ground_truth["pdf_id"]
    result = {
        "pdf_id": pdf_id, "pdf": ground_truth["pdf"],
        "page_count": ground_truth["page_count"],
        "detect_seconds": 0.0, "score_seconds": 0.0, "error": None,
    }

    t0 = time.perf_counter()
    try:
        detected = backend_fn(pdf_path)
    except Exception as e:
        result["error"] = f"detect: {type(e).__name__}: {e}"
        return result
    result["detect_seconds"] = round(time.perf_counter() - t0, 3)

    t0 = time.perf_counter()
    try:
        match_result = match_fields(detected, ground_truth["fields"], iou_threshold)
        metrics = compute_metrics(match_result, len(detected), len(ground_truth["fields"]))
    except Exception as e:
        result["error"] = f"score: {type(e).__name__}: {e}"
        return result
    result["score_seconds"] = round(time.perf_counter() - t0, 3)

    result["metrics"] = metrics
    result["match_detail"] = match_result

    type_counts_det = {}
    for f in detected:
        type_counts_det[f["type"]] = type_counts_det.get(f["type"], 0) + 1
    result["detected_type_counts"] = type_counts_det

    return result


def write_reports(results: list, run_dir: Path, backend_name: str, iou_threshold: float,
                  run_id: str, total_duration: float, lane: str, schema_version: str) -> None:
    total_tp = sum(r["metrics"]["tp"] for r in results if "metrics" in r)
    total_fp = sum(r["metrics"]["fp"] for r in results if "metrics" in r)
    total_fn = sum(r["metrics"]["fn"] for r in results if "metrics" in r)
    total_detected = sum(r["metrics"]["detected_count"] for r in results if "metrics" in r)
    total_gt = sum(r["metrics"]["ground_truth_count"] for r in results if "metrics" in r)
    total_type_correct = sum(r["metrics"]["type_correct"] for r in results if "metrics" in r)
    total_type_mismatches = sum(r["metrics"]["type_mismatches"] for r in results if "metrics" in r)

    agg_precision = total_tp / total_detected if total_detected > 0 else 0.0
    agg_recall = total_tp / total_gt if total_gt > 0 else 0.0
    agg_f1 = 2 * (agg_precision * agg_recall) / (agg_precision + agg_recall) if (agg_precision + agg_recall) > 0 else 0.0
    agg_type_accuracy = total_type_correct / total_tp if total_tp > 0 else 0.0

    n_perfect = sum(1 for r in results if "metrics" in r
                    and r["metrics"]["precision"] == 1.0 and r["metrics"]["recall"] == 1.0)
    n_errors = sum(1 for r in results if r.get("error"))

    aggregate = {
        "run_id": run_id, "backend": backend_name, "lane": lane,
        "schema_version": schema_version,
        "benchmark_version": BENCHMARK_VERSION, "iou_threshold": iou_threshold,
        "pdfs_processed": len(results), "pdfs_perfect": n_perfect, "pdfs_with_errors": n_errors,
        "total_tp": total_tp, "total_fp": total_fp, "total_fn": total_fn,
        "total_detected": total_detected, "total_ground_truth": total_gt,
        "aggregate_precision": round(agg_precision, 4),
        "aggregate_recall": round(agg_recall, 4),
        "aggregate_f1": round(agg_f1, 4),
        "total_type_correct": total_type_correct, "total_type_mismatches": total_type_mismatches,
        "aggregate_type_accuracy": round(agg_type_accuracy, 4),
        "total_duration_seconds": round(total_duration, 2),
    }

    scorecard = {"aggregate": aggregate, "per_pdf": []}
    for r in results:
        if r.get("error"):
            scorecard["per_pdf"].append({
                "pdf_id": r["pdf_id"], "pdf": r["pdf"],
                "page_count": r["page_count"], "error": r["error"],
            })
            continue
        scorecard["per_pdf"].append({
            "pdf_id": r["pdf_id"], "pdf": r["pdf"],
            "page_count": r["page_count"],
            "metrics": r["metrics"], "detected_type_counts": r["detected_type_counts"],
            "detect_seconds": r["detect_seconds"], "score_seconds": r["score_seconds"],
        })

    scorecard_path = run_dir / "scorecard.json"
    assert_safe_output_path(scorecard_path)
    scorecard_path.write_text(json.dumps(scorecard, indent=2))

    csv_path = run_dir / "scorecard.csv"
    assert_safe_output_path(csv_path)
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "pdf_id", "pdf", "page_count", "ground_truth_count", "detected_count",
            "tp", "fp", "fn", "precision", "recall", "f1",
            "type_correct", "type_mismatches", "type_accuracy",
            "detect_seconds", "error",
        ])
        for r in results:
            if r.get("error"):
                writer.writerow([
                    r["pdf_id"], r["pdf"], r["page_count"],
                    "", "", "", "", "", "", "", "", "", "", "",
                    r["detect_seconds"], r["error"],
                ])
                continue
            m = r["metrics"]
            writer.writerow([
                r["pdf_id"], r["pdf"], r["page_count"],
                m["ground_truth_count"], m["detected_count"],
                m["tp"], m["fp"], m["fn"], m["precision"], m["recall"], m["f1"],
                m["type_correct"], m["type_mismatches"], m["type_accuracy"],
                r["detect_seconds"], "",
            ])

    md_path = run_dir / "scorecard.md"
    assert_safe_output_path(md_path)
    lines = [
        f"# Detection Benchmark Scorecard",
        "",
        f"**Run ID:** `{run_id}`",
        f"**Backend:** `{backend_name}`",
        f"**Lane:** `{lane}`",
        f"**Schema version:** `{schema_version}`",
        f"**Benchmark version:** `{BENCHMARK_VERSION}`",
        f"**IoU threshold:** {iou_threshold}",
        f"**Total duration:** {aggregate['total_duration_seconds']}s",
        "",
        "## Aggregate",
        "",
        f"| Metric | Value |",
        f"| --- | ---: |",
        f"| PDFs processed | {aggregate['pdfs_processed']} |",
        f"| PDFs with precision=1.0 AND recall=1.0 | {aggregate['pdfs_perfect']} |",
        f"| PDFs with errors | {aggregate['pdfs_with_errors']} |",
        f"| Total ground truth fields | {aggregate['total_ground_truth']} |",
        f"| Total detected fields | {aggregate['total_detected']} |",
        f"| True positives | {aggregate['total_tp']} |",
        f"| False positives | {aggregate['total_fp']} |",
        f"| False negatives | {aggregate['total_fn']} |",
        f"| Aggregate precision | **{aggregate['aggregate_precision']}** |",
        f"| Aggregate recall | **{aggregate['aggregate_recall']}** |",
        f"| Aggregate F1 | **{aggregate['aggregate_f1']}** |",
        f"| Type accuracy (over TPs) | {aggregate['aggregate_type_accuracy']} |",
        f"| Type mismatches | {aggregate['total_type_mismatches']} |",
        "",
        "## Per-PDF Results",
        "",
        "| PDF | GT | Det | TP | FP | FN | Precision | Recall | F1 | Type acc |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in sorted(results, key=lambda x: x["pdf_id"]):
        if r.get("error"):
            lines.append(f"| `{r['pdf_id']}` | — | — | — | — | — | — | — | — | ERROR |")
            continue
        m = r["metrics"]
        lines.append(
            f"| `{r['pdf_id']}` | {m['ground_truth_count']} | {m['detected_count']} | "
            f"{m['tp']} | {m['fp']} | {m['fn']} | "
            f"{m['precision']} | {m['recall']} | {m['f1']} | {m['type_accuracy']} |"
        )
    lines.append("")
    md_path.write_text("\n".join(lines))

    per_pdf_dir = run_dir / "per_pdf"
    per_pdf_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        if r.get("error") or "match_detail" not in r:
            continue
        detail_path = per_pdf_dir / f"{r['pdf_id']}.json"
        assert_safe_output_path(detail_path)
        detail_path.write_text(json.dumps({
            "pdf_id": r["pdf_id"], "pdf": r["pdf"],
            "metrics": r["metrics"], "match_detail": r["match_detail"],
        }, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="acroform_self",
                        choices=list_backends(),
                        help=f"Detection backend (available: {', '.join(list_backends())})")
    parser.add_argument("--iou", type=float, default=0.5,
                        help="IoU threshold for match (default: 0.5)")
    parser.add_argument("--lane", choices=["A", "B"], default="A",
                        help="Scoring lane: A=AcroForm widgets, B=flat-PDF fill zones")
    parser.add_argument("--force-lane-mismatch", action="store_true",
                        help="Run even if the backend is not declared for the selected lane")
    parser.add_argument("--pdf", default=None,
                        help="Benchmark only the PDF with this pdf_id")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run measurement but do not write reports")
    args = parser.parse_args()

    if not (0.0 < args.iou <= 1.0):
        print(f"ERROR: --iou must be in (0.0, 1.0], got {args.iou}", file=sys.stderr)
        sys.exit(1)

    declared_lanes = get_lanes_for_backend(args.backend)
    if args.lane not in declared_lanes and not args.force_lane_mismatch:
        print(f"ERROR: backend '{args.backend}' is not declared for lane '{args.lane}'.")
        print(f"  Declared lanes: {declared_lanes}")
        print(f"  To force anyway: --force-lane-mismatch")
        sys.exit(2)

    if args.lane == "A":
        manifest_path = ACROFORM_MANIFEST
        ground_truth_dir = GROUND_TRUTH_DIR
    else:
        manifest_path = FLAT_MANIFEST
        ground_truth_dir = GROUND_TRUTH_FLAT_DIR

    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found", file=sys.stderr)
        sys.exit(1)
    if not ground_truth_dir.exists():
        print(f"ERROR: {ground_truth_dir} not found.", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    manifest_by_id = {e["id"]: e for e in manifest}

    gt_files = sorted(p for p in ground_truth_dir.glob("*.json") if not p.name.startswith("_") and not p.name.endswith(".draft.json"))
    if args.pdf:
        gt_files = [p for p in gt_files if p.stem == args.pdf]
        if not gt_files:
            print(f"ERROR: no ground truth for pdf_id '{args.pdf}' in lane {args.lane}", file=sys.stderr)
            sys.exit(1)

    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_id = f"{run_timestamp}_{args.backend}_lane{args.lane}"
    run_dir = REPORTS_DIR / run_id

    backend_fn = get_backend(args.backend)
    backend_metadata = get_backend_metadata(args.backend)
    schema_version = backend_metadata["schema_version"]

    print(f"{'='*72}")
    print(f"run_benchmark.py {BENCHMARK_VERSION}")
    if args.dry_run:
        print("MODE: DRY RUN -- no reports will be written")
    print(f"Backend: {args.backend}")
    print(f"Lane: {args.lane}")
    print(f"Schema version: {schema_version}")
    print(f"IoU threshold: {args.iou}")
    print(f"Manifest: {manifest_path}")
    print(f"Ground truth dir: {ground_truth_dir}")
    print(f"PDFs to benchmark: {len(gt_files)}")
    print(f"Run ID: {run_id}")
    print(f"{'='*72}")

    start_time = time.perf_counter()
    results = []

    for gt_path in gt_files:
        gt = json.loads(gt_path.read_text())
        pdf_id = gt["pdf_id"]
        manifest_entry = manifest_by_id.get(pdf_id)
        if not manifest_entry:
            print(f"SKIP {pdf_id}: no manifest entry")
            results.append({
                "pdf_id": pdf_id, "pdf": gt["pdf"],
                "page_count": gt["page_count"], "error": "no manifest entry",
            })
            continue
        pdf_path = ROOT / manifest_entry["filename"]
        if not pdf_path.exists():
            print(f"SKIP {pdf_id}: PDF not found at {pdf_path}")
            results.append({
                "pdf_id": pdf_id, "pdf": gt["pdf"],
                "page_count": gt["page_count"], "error": "PDF not found",
            })
            continue

        print(f"Benchmarking {pdf_id:30s} ... ", end="", flush=True)
        result = benchmark_pdf(pdf_path, gt, backend_fn, args.iou)
        results.append(result)

        if result.get("error"):
            print(f"ERROR: {result['error']}")
        else:
            m = result["metrics"]
            tag = "OK"
            if m["precision"] == 1.0 and m["recall"] == 1.0:
                tag = "PERFECT"
            elif m["precision"] >= 0.95 and m["recall"] >= 0.95:
                tag = "high"
            elif m["recall"] < 0.5:
                tag = "low-recall"
            print(
                f"P={m['precision']:.4f} R={m['recall']:.4f} F1={m['f1']:.4f} "
                f"(TP={m['tp']:4d} FP={m['fp']:3d} FN={m['fn']:3d}) "
                f"[{tag}] {result['detect_seconds']:.2f}s"
            )

    total_duration = time.perf_counter() - start_time

    print(f"{'='*72}")
    n_perfect = sum(1 for r in results if "metrics" in r
                    and r["metrics"]["precision"] == 1.0 and r["metrics"]["recall"] == 1.0)
    n_errors = sum(1 for r in results if r.get("error"))
    total_tp = sum(r["metrics"]["tp"] for r in results if "metrics" in r)
    total_detected = sum(r["metrics"]["detected_count"] for r in results if "metrics" in r)
    total_gt = sum(r["metrics"]["ground_truth_count"] for r in results if "metrics" in r)
    agg_precision = total_tp / total_detected if total_detected > 0 else 0.0
    agg_recall = total_tp / total_gt if total_gt > 0 else 0.0

    print(f"PDFs processed: {len(results)}")
    print(f"PDFs perfect (P=1.0, R=1.0): {n_perfect}")
    print(f"PDFs with errors: {n_errors}")
    print(f"Aggregate precision: {agg_precision:.4f}")
    print(f"Aggregate recall:    {agg_recall:.4f}")
    print(f"Total duration: {total_duration:.2f}s")

    if not args.dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
        write_reports(results, run_dir, args.backend, args.iou, run_id, total_duration, args.lane, schema_version)
        print(f"\nReports written to: {run_dir.relative_to(ROOT)}")
    else:
        print(f"\n(dry-run: no reports written)")


if __name__ == "__main__":
    main()
