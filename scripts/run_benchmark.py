#!/usr/bin/env python3
"""
run_benchmark.py

Detection benchmark runner. Runs a detection backend against the corpus,
scores its output against ground truth using IoU matching, and produces
per-PDF and aggregate scorecards.

This is the core measurement infrastructure. The scoring methodology
matches docs/legacy/detection-measurement-guide.md:
- Greedy match by highest IoU
- IoU threshold 0.5 (configurable)
- Page-aware (matches only consider same-page fields)
- Metrics: TP, FP, FN, precision, recall, F1, type mismatches

Backends are pluggable. Each backend implements:
    def detect(pdf_path: Path) -> list[Field]

where Field is a dict matching the ground truth schema:
    {"id": str, "page": int, "type": str,
     "bbox": [x, y, w, h], "label": str (optional)}

V1 ships ONE backend:
    acroform_self - re-extracts AcroForm widgets via pikepdf, identical
                    to what extract_ground_truth.py produced.

Expected V1 result: precision=1.0, recall=1.0 across all 30 AcroForm PDFs.
This is the sanity check that proves IoU scoring, matching, and report
generation are all correct before more interesting backends are added.

V2+ backends (next):
    heuristic_baseline - pdfplumber-based detection (the production heuristic)
    azure_doc_intel    - Azure Document Intelligence (cost-aware)
    custom_ml_v1       - future ML-assisted ranking

Guardrails:
- READ-ONLY access to PDFs, ground truth, and corpus manifests
- All writes confined to reports/benchmarks/
- assert_safe_output_path() refuses path traversal
- Idempotent: re-running produces fresh timestamped reports
- --dry-run mode reports what would be measured without writes
- --pdf <id> mode benchmarks a single PDF
- --backend <name> selects which backend to use

Usage:
    python scripts/run_benchmark.py                    # acroform_self, all PDFs
    python scripts/run_benchmark.py --dry-run          # report only
    python scripts/run_benchmark.py --pdf irs_w9       # one PDF
    python scripts/run_benchmark.py --iou 0.5          # custom IoU threshold
    python scripts/run_benchmark.py --backend acroform_self

Output:
    reports/benchmarks/<timestamp>_<backend>/
        scorecard.json     Aggregate + per-PDF metrics (machine-readable)
        scorecard.csv      Per-PDF table (spreadsheet-friendly)
        scorecard.md       Human-readable markdown report
        per_pdf/<pdf_id>.json   Detailed match data per PDF
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import pikepdf
except ImportError:
    print("ERROR: pikepdf not installed.", file=sys.stderr)
    sys.exit(1)


BENCHMARK_VERSION = "v1"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ACROFORM_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"
GROUND_TRUTH_DIR = ROOT / "benchmarks" / "ground_truth"
REPORTS_DIR = ROOT / "reports" / "benchmarks"


def assert_safe_output_path(path: Path) -> None:
    """Guardrail: refuse to write outside reports/benchmarks/."""
    resolved = path.resolve()
    expected = REPORTS_DIR.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError:
        raise RuntimeError(f"Refused to write outside {expected}: {resolved}")


# ---------------------------------------------------------------------------
# IoU + matching
# ---------------------------------------------------------------------------

def iou(box_a: list, box_b: list) -> float:
    """
    Intersection-over-Union for two bboxes in [x, y, w, h] format
    (top-left origin, same units).
    Returns 0.0 if no overlap.
    """
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b

    # Compute overlap rectangle
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
    """
    Greedy IoU matching, page-aware.

    For each ground truth field, find the detected field with highest IoU
    (on same page, above threshold) that hasn't been claimed yet.

    Returns dict with:
        tp:           list of (gt_idx, det_idx, iou, type_match) tuples
        fp:           list of det_idx (detected fields with no match)
        fn:           list of gt_idx (ground truth fields with no match)
        type_mismatches: list of (gt_idx, det_idx, gt_type, det_type)
        iou_threshold: float (passed through for reporting)
    """
    # Build per-page index for fast filtering
    detected_by_page = {}
    for i, d in enumerate(detected):
        detected_by_page.setdefault(d["page"], []).append(i)

    # Score all candidate pairs on the same page
    candidates = []  # (iou, gt_idx, det_idx)
    for gt_idx, gt in enumerate(ground_truth):
        candidate_det_indices = detected_by_page.get(gt["page"], [])
        for det_idx in candidate_det_indices:
            score = iou(gt["bbox"], detected[det_idx]["bbox"])
            if score >= iou_threshold:
                candidates.append((score, gt_idx, det_idx))

    # Sort by IoU descending, greedy claim
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
            "gt_idx": gt_idx,
            "det_idx": det_idx,
            "iou": round(score, 4),
            "gt_id": ground_truth[gt_idx]["id"],
            "det_id": detected[det_idx]["id"],
            "gt_type": gt_type,
            "det_type": det_type,
            "type_match": type_match,
        })
        if not type_match:
            type_mismatches.append({
                "gt_idx": gt_idx,
                "det_idx": det_idx,
                "gt_id": ground_truth[gt_idx]["id"],
                "det_id": detected[det_idx]["id"],
                "gt_type": gt_type,
                "det_type": det_type,
            })

    fp = [i for i in range(len(detected)) if i not in claimed_det]
    fn = [i for i in range(len(ground_truth)) if i not in claimed_gt]

    return {
        "iou_threshold": iou_threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "type_mismatches": type_mismatches,
    }


def compute_metrics(match_result: dict, detected_count: int, ground_truth_count: int) -> dict:
    """Compute precision, recall, F1 from match result."""
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
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "detected_count": detected_count,
        "ground_truth_count": ground_truth_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "type_correct": type_correct,
        "type_mismatches": type_mismatches,
        "type_accuracy": round(type_accuracy, 4),
    }


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def backend_acroform_self(pdf_path: Path) -> list:
    """
    Re-extract AcroForm widgets via pikepdf. Should produce results
    identical to extract_ground_truth.py — used to validate scoring
    infrastructure with expected perfect precision/recall.

    Coordinate convention: top-left origin, PDF points (same as ground truth).
    """
    fields = []
    field_counter = 0

    try:
        with pikepdf.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                try:
                    annots = page.get("/Annots", None)
                except Exception:
                    annots = None
                if annots is None:
                    continue

                try:
                    page_height = float(page.mediabox[3])
                except Exception:
                    continue

                seen = set()
                for annot in annots:
                    try:
                        subtype = annot.get("/Subtype", None)
                    except Exception:
                        continue
                    if subtype is None or str(subtype) != "/Widget":
                        continue

                    try:
                        key = annot.objgen
                        if key in seen:
                            continue
                        seen.add(key)
                    except Exception:
                        pass

                    # Get rect
                    try:
                        rect = annot.get("/Rect", None)
                        if rect is None:
                            continue
                        rect_vals = [float(v) for v in rect]
                    except (TypeError, ValueError, Exception):
                        continue

                    # Resolve type via /Parent chain
                    field_type = "unknown"
                    cursor = annot
                    safety = 20
                    while safety > 0 and field_type == "unknown":
                        try:
                            ft = cursor.get("/FT", None)
                        except Exception:
                            ft = None
                        if ft is not None:
                            ft_str = str(ft)
                            if ft_str == "/Tx":
                                field_type = "text"
                            elif ft_str == "/Btn":
                                try:
                                    ff = int(cursor.get("/Ff", 0))
                                except (TypeError, ValueError):
                                    ff = 0
                                if ff & 0x10000:
                                    field_type = "radio"
                                elif ff & 0x20000:
                                    field_type = "pushbutton"
                                else:
                                    field_type = "checkbox"
                            elif ft_str == "/Ch":
                                field_type = "choice"
                            elif ft_str == "/Sig":
                                field_type = "signature"
                        if field_type == "unknown":
                            try:
                                cursor = cursor.get("/Parent", None)
                            except Exception:
                                break
                            if cursor is None:
                                break
                        safety -= 1
                    if field_type == "unknown":
                        field_type = "text"

                    # bbox conversion: PDF native bottom-left → top-left
                    x_ll, y_ll, x_ur, y_ur = rect_vals
                    x = min(x_ll, x_ur)
                    width = abs(x_ur - x_ll)
                    height = abs(y_ur - y_ll)
                    y_bottom = min(y_ll, y_ur)
                    y_top = page_height - y_bottom - height

                    if width <= 0 or height <= 0:
                        continue

                    field_counter += 1
                    fields.append({
                        "id": f"d{field_counter}",
                        "page": page_idx + 1,
                        "type": field_type,
                        "bbox": [round(x, 2), round(y_top, 2), round(width, 2), round(height, 2)],
                    })
    except Exception:
        pass

    return fields


BACKENDS = {
    "acroform_self": backend_acroform_self,
}


# ---------------------------------------------------------------------------
# Per-PDF benchmark
# ---------------------------------------------------------------------------

def benchmark_pdf(pdf_path: Path, ground_truth: dict, backend_fn, iou_threshold: float) -> dict:
    """
    Run a single PDF through the detection backend and score against ground truth.
    """
    pdf_id = ground_truth["pdf_id"]
    result = {
        "pdf_id": pdf_id,
        "pdf": ground_truth["pdf"],
        "page_count": ground_truth["page_count"],
        "detect_seconds": 0.0,
        "score_seconds": 0.0,
        "error": None,
    }

    # Detect
    t0 = time.perf_counter()
    try:
        detected = backend_fn(pdf_path)
    except Exception as e:
        result["error"] = f"detect: {type(e).__name__}: {e}"
        return result
    result["detect_seconds"] = round(time.perf_counter() - t0, 3)

    # Score
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

    # Per-type detected counts (for sanity reporting)
    type_counts_det = {}
    for f in detected:
        type_counts_det[f["type"]] = type_counts_det.get(f["type"], 0) + 1
    result["detected_type_counts"] = type_counts_det

    return result


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def write_reports(results: list, run_dir: Path, backend_name: str, iou_threshold: float,
                  run_id: str, total_duration: float) -> None:
    """Write scorecard.json, scorecard.csv, scorecard.md, and per_pdf/*.json."""

    # Aggregate metrics
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
        "run_id": run_id,
        "backend": backend_name,
        "benchmark_version": BENCHMARK_VERSION,
        "iou_threshold": iou_threshold,
        "pdfs_processed": len(results),
        "pdfs_perfect": n_perfect,
        "pdfs_with_errors": n_errors,
        "total_tp": total_tp,
        "total_fp": total_fp,
        "total_fn": total_fn,
        "total_detected": total_detected,
        "total_ground_truth": total_gt,
        "aggregate_precision": round(agg_precision, 4),
        "aggregate_recall": round(agg_recall, 4),
        "aggregate_f1": round(agg_f1, 4),
        "total_type_correct": total_type_correct,
        "total_type_mismatches": total_type_mismatches,
        "aggregate_type_accuracy": round(agg_type_accuracy, 4),
        "total_duration_seconds": round(total_duration, 2),
    }

    # scorecard.json
    scorecard = {"aggregate": aggregate, "per_pdf": []}
    for r in results:
        if r.get("error"):
            scorecard["per_pdf"].append({
                "pdf_id": r["pdf_id"], "pdf": r["pdf"],
                "page_count": r["page_count"],
                "error": r["error"],
            })
            continue
        scorecard["per_pdf"].append({
            "pdf_id": r["pdf_id"],
            "pdf": r["pdf"],
            "page_count": r["page_count"],
            "metrics": r["metrics"],
            "detected_type_counts": r["detected_type_counts"],
            "detect_seconds": r["detect_seconds"],
            "score_seconds": r["score_seconds"],
        })

    scorecard_path = run_dir / "scorecard.json"
    assert_safe_output_path(scorecard_path)
    scorecard_path.write_text(json.dumps(scorecard, indent=2))

    # scorecard.csv
    csv_path = run_dir / "scorecard.csv"
    assert_safe_output_path(csv_path)
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "pdf_id", "pdf", "page_count",
            "ground_truth_count", "detected_count",
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

    # scorecard.md
    md_path = run_dir / "scorecard.md"
    assert_safe_output_path(md_path)
    lines = []
    lines.append(f"# Detection Benchmark Scorecard")
    lines.append("")
    lines.append(f"**Run ID:** `{run_id}`")
    lines.append(f"**Backend:** `{backend_name}`")
    lines.append(f"**Benchmark version:** `{BENCHMARK_VERSION}`")
    lines.append(f"**IoU threshold:** {iou_threshold}")
    lines.append(f"**Total duration:** {aggregate['total_duration_seconds']}s")
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"| --- | ---: |")
    lines.append(f"| PDFs processed | {aggregate['pdfs_processed']} |")
    lines.append(f"| PDFs with precision=1.0 AND recall=1.0 | {aggregate['pdfs_perfect']} |")
    lines.append(f"| PDFs with errors | {aggregate['pdfs_with_errors']} |")
    lines.append(f"| Total ground truth fields | {aggregate['total_ground_truth']} |")
    lines.append(f"| Total detected fields | {aggregate['total_detected']} |")
    lines.append(f"| True positives | {aggregate['total_tp']} |")
    lines.append(f"| False positives | {aggregate['total_fp']} |")
    lines.append(f"| False negatives | {aggregate['total_fn']} |")
    lines.append(f"| Aggregate precision | **{aggregate['aggregate_precision']}** |")
    lines.append(f"| Aggregate recall | **{aggregate['aggregate_recall']}** |")
    lines.append(f"| Aggregate F1 | **{aggregate['aggregate_f1']}** |")
    lines.append(f"| Type accuracy (over TPs) | {aggregate['aggregate_type_accuracy']} |")
    lines.append(f"| Type mismatches | {aggregate['total_type_mismatches']} |")
    lines.append("")
    lines.append("## Per-PDF Results")
    lines.append("")
    lines.append("| PDF | GT | Det | TP | FP | FN | Precision | Recall | F1 | Type acc |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
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

    # per_pdf/<pdf_id>.json with full match detail
    per_pdf_dir = run_dir / "per_pdf"
    per_pdf_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        if r.get("error") or "match_detail" not in r:
            continue
        detail_path = per_pdf_dir / f"{r['pdf_id']}.json"
        assert_safe_output_path(detail_path)
        detail_path.write_text(json.dumps({
            "pdf_id": r["pdf_id"],
            "pdf": r["pdf"],
            "metrics": r["metrics"],
            "match_detail": r["match_detail"],
        }, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="acroform_self",
                        choices=list(BACKENDS.keys()),
                        help="Detection backend (default: acroform_self)")
    parser.add_argument("--iou", type=float, default=0.5,
                        help="IoU threshold for match (default: 0.5)")
    parser.add_argument("--pdf", default=None,
                        help="Benchmark only the PDF with this pdf_id")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run measurement but do not write reports")
    args = parser.parse_args()

    if not (0.0 < args.iou <= 1.0):
        print(f"ERROR: --iou must be in (0.0, 1.0], got {args.iou}", file=sys.stderr)
        sys.exit(1)

    if not ACROFORM_MANIFEST.exists():
        print(f"ERROR: {ACROFORM_MANIFEST} not found", file=sys.stderr)
        sys.exit(1)
    if not GROUND_TRUTH_DIR.exists():
        print(f"ERROR: {GROUND_TRUTH_DIR} not found. Run extract_ground_truth.py first.", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(ACROFORM_MANIFEST.read_text())
    manifest_by_id = {e["id"]: e for e in manifest}

    # Find ground truth files
    gt_files = sorted(p for p in GROUND_TRUTH_DIR.glob("*.json") if not p.name.startswith("_"))
    if args.pdf:
        gt_files = [p for p in gt_files if p.stem == args.pdf]
        if not gt_files:
            print(f"ERROR: no ground truth for pdf_id '{args.pdf}'", file=sys.stderr)
            sys.exit(1)

    # Set up run directory
    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_id = f"{run_timestamp}_{args.backend}"
    run_dir = REPORTS_DIR / run_id

    backend_fn = BACKENDS[args.backend]

    print(f"{'='*72}")
    print(f"run_benchmark.py {BENCHMARK_VERSION}")
    if args.dry_run:
        print("MODE: DRY RUN -- no reports will be written")
    print(f"Backend: {args.backend}")
    print(f"IoU threshold: {args.iou}")
    print(f"Ground truth dir: {GROUND_TRUTH_DIR}")
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
                "page_count": gt["page_count"],
                "error": "no manifest entry",
            })
            continue

        pdf_path = ROOT / manifest_entry["filename"]
        if not pdf_path.exists():
            print(f"SKIP {pdf_id}: PDF not found at {pdf_path}")
            results.append({
                "pdf_id": pdf_id, "pdf": gt["pdf"],
                "page_count": gt["page_count"],
                "error": "PDF not found",
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
            print(
                f"P={m['precision']:.4f} R={m['recall']:.4f} F1={m['f1']:.4f} "
                f"(TP={m['tp']:4d} FP={m['fp']:3d} FN={m['fn']:3d}, "
                f"types={m['type_accuracy']:.4f}) [{tag}] {result['detect_seconds']:.2f}s"
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
        write_reports(results, run_dir, args.backend, args.iou, run_id, total_duration)
        print(f"\nReports written to: {run_dir.relative_to(ROOT)}")
        print(f"  - scorecard.json")
        print(f"  - scorecard.csv")
        print(f"  - scorecard.md")
        print(f"  - per_pdf/<pdf_id>.json")
    else:
        print(f"\n(dry-run: no reports written)")


if __name__ == "__main__":
    main()
