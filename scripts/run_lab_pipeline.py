#!/usr/bin/env python3
"""Continuous benchmark pipeline for the detection lab queue."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "corpus" / "manifest.json"
DEFAULT_OUT = ROOT / "runs"
QUEUE_SCRIPT = ROOT / "scripts" / "run_lab_queue.py"
PROMOTION_GATE = [
    "AcroForm lane does not regress",
    "Known failure improves",
    "False positives do not materially increase",
    "Alignment score improves or remains stable",
    "Scanned/flat improvements are supported by screenshots/overlays",
    "No sensitive data is stored",
]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def assert_under_root(path: Path, label: str) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        raise RuntimeError(f"{label} must be inside {ROOT}: {resolved}")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def result_files(run_dir: Path) -> list[Path]:
    results_dir = run_dir / "results"
    if not results_dir.exists():
        return []
    return sorted(results_dir.glob("*.json"))


def load_results(run_dir: Path) -> list[dict[str, Any]]:
    return [load_json(path) for path in result_files(run_dir)]


def detector_count(result: dict[str, Any], detector: str) -> int | None:
    data = result.get("detectors", {}).get(detector)
    if not data:
        return None
    count = data.get("detected_count")
    return count if isinstance(count, int) else None


def all_detector_counts(result: dict[str, Any]) -> dict[str, int]:
    counts = {}
    for name, data in result.get("detectors", {}).items():
        count = data.get("detected_count")
        if isinstance(count, int):
            counts[name] = count
    return counts


def summarize_run(run_dir: Path) -> dict[str, Any]:
    results = load_results(run_dir)
    lane_counts = Counter(lane for r in results for lane in r.get("lanes", []))
    status_counts = Counter(r.get("status", "unknown") for r in results)
    missing = sorted(r["id"] for r in results if r.get("status") == "missing")
    sensitive = sorted(r["id"] for r in results if r.get("status") == "skipped_sensitive_local_only")
    known_failures = sorted(r["id"] for r in results if r.get("known_failure"))
    scanned = sorted(
        r["id"]
        for r in results
        if r.get("signals", {}).get("scanned_image_likely") or "scanned_image" in r.get("lanes", [])
    )
    acroform_results = [r for r in results if "acroform" in r.get("lanes", [])]
    acroform_baseline_failures = []
    for r in acroform_results:
        gt_count = r.get("ground_truth_field_count")
        baseline_count = detector_count(r, "acroform_self")
        if r.get("status") != "ok" or gt_count is None or baseline_count != gt_count:
            acroform_baseline_failures.append({
                "id": r.get("id"),
                "status": r.get("status"),
                "ground_truth_field_count": gt_count,
                "acroform_self_detected_count": baseline_count,
            })

    detector_totals: dict[str, int] = {}
    per_doc_detector_counts: dict[str, dict[str, int]] = {}
    for r in results:
        counts = all_detector_counts(r)
        per_doc_detector_counts[r["id"]] = counts
        for name, count in counts.items():
            detector_totals[name] = detector_totals.get(name, 0) + count

    return {
        "run_dir": rel(run_dir),
        "total_docs": len(results),
        "docs_by_lane": dict(sorted(lane_counts.items())),
        "docs_by_status": dict(sorted(status_counts.items())),
        "missing_docs": missing,
        "sensitive_local_only_skips": sensitive,
        "known_failures": known_failures,
        "scanned_image_candidates": scanned,
        "detector_totals": dict(sorted(detector_totals.items())),
        "per_doc_detector_counts": per_doc_detector_counts,
        "acroform_baseline": {
            "status": "pass" if not acroform_baseline_failures else "fail",
            "failures": acroform_baseline_failures,
        },
    }


def list_delta(previous: list[str], current: list[str]) -> dict[str, list[str]]:
    prev = set(previous)
    cur = set(current)
    return {
        "added": sorted(cur - prev),
        "removed": sorted(prev - cur),
    }


def count_delta(previous: dict[str, int], current: dict[str, int]) -> dict[str, dict[str, int]]:
    keys = sorted(set(previous) | set(current))
    return {
        key: {
            "previous": previous.get(key, 0),
            "current": current.get(key, 0),
            "delta": current.get(key, 0) - previous.get(key, 0),
        }
        for key in keys
        if previous.get(key, 0) != current.get(key, 0)
    }


def compare_summaries(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if previous is None:
        return {
            "has_previous": False,
            "message": "No previous latest run was available for comparison.",
            "regressions": [],
            "improvements": [],
            "scanned_image_candidates": current["scanned_image_candidates"],
            "acroform_baseline_status": current["acroform_baseline"]["status"],
        }

    regressions = []
    improvements = []

    missing_delta = list_delta(previous["missing_docs"], current["missing_docs"])
    if missing_delta["added"]:
        regressions.append(f"New missing documents: {', '.join(missing_delta['added'])}")
    if missing_delta["removed"]:
        improvements.append(f"Missing documents restored: {', '.join(missing_delta['removed'])}")

    sensitive_delta = list_delta(previous["sensitive_local_only_skips"], current["sensitive_local_only_skips"])
    if sensitive_delta["added"]:
        regressions.append(f"New sensitive/local-only skips: {', '.join(sensitive_delta['added'])}")
    if sensitive_delta["removed"]:
        improvements.append(f"Sensitive/local-only skips resolved: {', '.join(sensitive_delta['removed'])}")

    if previous["acroform_baseline"]["status"] == "pass" and current["acroform_baseline"]["status"] != "pass":
        regressions.append("AcroForm baseline regressed")
    elif previous["acroform_baseline"]["status"] != "pass" and current["acroform_baseline"]["status"] == "pass":
        improvements.append("AcroForm baseline recovered")

    field_count_changes = []
    previous_docs = previous.get("per_doc_detector_counts", {})
    current_docs = current.get("per_doc_detector_counts", {})
    for doc_id in sorted(set(previous_docs) | set(current_docs)):
        detectors = sorted(set(previous_docs.get(doc_id, {})) | set(current_docs.get(doc_id, {})))
        for detector in detectors:
            prev_count = previous_docs.get(doc_id, {}).get(detector)
            cur_count = current_docs.get(doc_id, {}).get(detector)
            if prev_count != cur_count:
                field_count_changes.append({
                    "id": doc_id,
                    "detector": detector,
                    "previous": prev_count,
                    "current": cur_count,
                    "delta": (cur_count or 0) - (prev_count or 0),
                })

    return {
        "has_previous": True,
        "previous_run_dir": previous["run_dir"],
        "current_run_dir": current["run_dir"],
        "total_docs": {
            "previous": previous["total_docs"],
            "current": current["total_docs"],
            "delta": current["total_docs"] - previous["total_docs"],
        },
        "docs_by_lane": count_delta(previous["docs_by_lane"], current["docs_by_lane"]),
        "detector_totals": count_delta(previous["detector_totals"], current["detector_totals"]),
        "detected_field_count_changes": field_count_changes,
        "missing_docs": missing_delta,
        "sensitive_local_only_skips": sensitive_delta,
        "known_failures": list_delta(previous["known_failures"], current["known_failures"]),
        "scanned_image_candidates": current["scanned_image_candidates"],
        "acroform_baseline_status": current["acroform_baseline"]["status"],
        "acroform_baseline_failures": current["acroform_baseline"]["failures"],
        "regressions": regressions,
        "improvements": improvements,
    }


def write_compare_md(compare: dict[str, Any], path: Path) -> None:
    lines = ["# Lab Pipeline Comparison", ""]
    if not compare.get("has_previous"):
        lines.extend([compare["message"], ""])
    else:
        total = compare["total_docs"]
        lines.extend([
            f"Previous: `{compare['previous_run_dir']}`",
            f"Current: `{compare['current_run_dir']}`",
            "",
            "## Totals",
            "",
            f"- Total docs: {total['previous']} -> {total['current']} ({total['delta']:+d})",
            f"- AcroForm baseline: {compare['acroform_baseline_status']}",
            "",
            "## Detector Field Count Changes",
            "",
        ])
        changes = compare.get("detected_field_count_changes", [])
        if changes:
            lines.extend([
                "| Document | Detector | Previous | Current | Delta |",
                "| --- | --- | ---: | ---: | ---: |",
            ])
            for change in changes:
                lines.append(
                    f"| `{change['id']}` | {change['detector']} | "
                    f"{change['previous']} | {change['current']} | {change['delta']:+d} |"
                )
        else:
            lines.append("No detector field count changes.")
        lines.extend(["", "## Regressions", ""])
        if compare["regressions"]:
            lines.extend(f"- {item}" for item in compare["regressions"])
        else:
            lines.append("None.")
        lines.extend(["", "## Improvements", ""])
        if compare["improvements"]:
            lines.extend(f"- {item}" for item in compare["improvements"])
        else:
            lines.append("None.")

    lines.extend(["", "## Scanned/Image-Only Candidates", ""])
    scanned = compare.get("scanned_image_candidates", [])
    if scanned:
        lines.extend(f"- {doc_id}" for doc_id in scanned)
    else:
        lines.append("None.")
    lines.extend(["", "## Promotion Gate", ""])
    lines.extend(f"- {rule}" for rule in PROMOTION_GATE)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_pipeline_summary(run_dir: Path, current: dict[str, Any], compare: dict[str, Any], manifest_path: Path) -> None:
    summary = {
        "pipeline_version": "pipeline_1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "manifest": rel(manifest_path),
        "run_dir": rel(run_dir),
        "scorecard": rel(run_dir / "scorecard.md"),
        "summary_csv": rel(run_dir / "summary.csv"),
        "results_dir": rel(run_dir / "results"),
        "compare_md": rel(run_dir / "compare.md"),
        "compare_json": rel(run_dir / "compare.json"),
        "current": current,
        "comparison": compare,
        "promotion_gate": PROMOTION_GATE,
    }
    (run_dir / "pipeline_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def copy_latest(current_run_dir: Path, latest_dir: Path) -> None:
    temp_dir = latest_dir.with_name("_latest_tmp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    shutil.copytree(current_run_dir, temp_dir)
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    temp_dir.rename(latest_dir)


def run_queue(manifest_path: Path, run_dir: Path) -> None:
    cmd = [
        sys.executable,
        str(QUEUE_SCRIPT),
        "--manifest",
        str(manifest_path),
        "--out",
        str(run_dir),
    ]
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"queue failed with exit {proc.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Queue manifest path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Runs root directory")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = ROOT / out_root

    assert_under_root(manifest_path, "manifest")
    assert_under_root(out_root, "output root")

    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    out_root.mkdir(parents=True, exist_ok=True)
    latest_dir = out_root / "latest"
    previous_summary = summarize_run(latest_dir) if result_files(latest_dir) else None

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = out_root / run_id
    if run_dir.exists():
        raise RuntimeError(f"run directory already exists: {run_dir}")

    print(f"Pipeline run: {run_id}")
    print(f"Manifest: {rel(manifest_path)}")
    print(f"Run directory: {rel(run_dir)}")
    run_queue(manifest_path, run_dir)

    current_summary = summarize_run(run_dir)
    compare = compare_summaries(previous_summary, current_summary)
    (run_dir / "compare.json").write_text(json.dumps(compare, indent=2) + "\n", encoding="utf-8")
    write_compare_md(compare, run_dir / "compare.md")
    write_pipeline_summary(run_dir, current_summary, compare, manifest_path)
    copy_latest(run_dir, latest_dir)

    print("")
    print("Pipeline summary")
    print(f"  Run: {rel(run_dir)}")
    print(f"  Latest: {rel(latest_dir)}")
    print(f"  Scorecard: {rel(latest_dir / 'scorecard.md')}")
    print(f"  Docs: {current_summary['total_docs']}")
    print(f"  Missing: {len(current_summary['missing_docs'])}")
    print(f"  Sensitive/local-only skipped: {len(current_summary['sensitive_local_only_skips'])}")
    print(f"  Scanned/image-only candidates: {len(current_summary['scanned_image_candidates'])}")
    print(f"  AcroForm baseline: {current_summary['acroform_baseline']['status']}")
    if compare.get("has_previous"):
        print(f"  Regressions: {len(compare['regressions'])}")
        print(f"  Improvements: {len(compare['improvements'])}")
    else:
        print("  Comparison: no previous latest run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
