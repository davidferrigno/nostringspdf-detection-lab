#!/usr/bin/env python3
"""Run the detection lab queue from a privacy-aware corpus manifest."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pikepdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend_registry import get_backend, list_backends_for_lane


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "corpus" / "manifest.json"
DEFAULT_OUT = ROOT / "runs" / "latest"

ALLOWED_PRIVACY = {"blank", "synthetic", "sensitive_do_not_store"}
LANE_TO_BACKEND_LANE = {
    "acroform": "A",
    "flat_text": "B",
    "comb_fields": "B",
    "checkbox_radio": "B",
    "signature_targets": "B",
    "known_failure": "B",
    "scanned_image": "B",
}


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


def count_ground_truth_fields(path_value: str | None) -> tuple[str, int | None]:
    if not path_value:
        return ("missing", None)
    path = ROOT / path_value
    if not path.exists():
        return ("missing", None)
    try:
        data = load_json(path)
    except Exception:
        return ("unreadable", None)
    status = "draft_needs_review" if path.name.endswith(".draft.json") else "reviewed"
    return (status, len(data.get("fields", [])))


def detect_pdf_signals(pdf_path: Path) -> dict[str, Any]:
    signals: dict[str, Any] = {
        "page_count": 0,
        "widget_count": 0,
        "text_chars": 0,
        "image_xobject_count": 0,
        "has_text": False,
        "has_widgets": False,
        "image_heavy": False,
        "scanned_image_likely": False,
        "error": None,
    }
    try:
        with pikepdf.open(pdf_path) as pdf:
            signals["page_count"] = len(pdf.pages)
            for page in pdf.pages:
                annots = page.get("/Annots", [])
                for annot in annots or []:
                    try:
                        if str(annot.get("/Subtype", "")) == "/Widget":
                            signals["widget_count"] += 1
                    except Exception:
                        continue
                resources = page.get("/Resources", {})
                xobjects = resources.get("/XObject", {}) if resources else {}
                try:
                    values = xobjects.values()
                except Exception:
                    values = []
                for xobj in values:
                    try:
                        if str(xobj.get("/Subtype", "")) == "/Image":
                            signals["image_xobject_count"] += 1
                    except Exception:
                        continue
    except Exception as exc:
        signals["error"] = f"pikepdf: {type(exc).__name__}: {exc}"
        return signals

    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                signals["text_chars"] += len(text.strip())
    except Exception as exc:
        signals["text_error"] = f"pdfplumber: {type(exc).__name__}: {exc}"

    signals["has_text"] = signals["text_chars"] > 0
    signals["has_widgets"] = signals["widget_count"] > 0
    signals["image_heavy"] = (
        signals["page_count"] > 0
        and signals["image_xobject_count"] >= signals["page_count"]
        and signals["text_chars"] < 50
    )
    signals["scanned_image_likely"] = (
        not signals["has_text"]
        and not signals["has_widgets"]
        and signals["image_heavy"]
    )
    return signals


def detector_names_for_entry(entry: dict[str, Any]) -> list[str]:
    backend_lanes = {
        LANE_TO_BACKEND_LANE[lane]
        for lane in entry.get("lanes", [])
        if lane in LANE_TO_BACKEND_LANE
    }
    if not backend_lanes and entry.get("expected_lane") in {"A", "B"}:
        backend_lanes.add(entry["expected_lane"])
    names: set[str] = set()
    for lane in backend_lanes:
        names.update(list_backends_for_lane(lane))
    return sorted(names)


def run_detectors(pdf_path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in detector_names_for_entry(entry):
        started = time.perf_counter()
        try:
            fields = get_backend(name)(pdf_path)
            type_counts = Counter(str(f.get("type", "unknown")) for f in fields)
            results[name] = {
                "status": "ok",
                "detected_count": len(fields),
                "type_counts": dict(sorted(type_counts.items())),
                "seconds": round(time.perf_counter() - started, 3),
            }
        except Exception as exc:
            results[name] = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.perf_counter() - started, 3),
            }
    return results


def resolve_pdf_path(entry: dict[str, Any]) -> Path:
    path_value = entry.get("path") or entry.get("filename")
    if not path_value:
        raise ValueError("entry has no path or filename")
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def evaluate_entry(entry: dict[str, Any]) -> dict[str, Any]:
    privacy = entry.get("privacy_status")
    result: dict[str, Any] = {
        "id": entry.get("id"),
        "lanes": entry.get("lanes", []),
        "expected_lane": entry.get("expected_lane"),
        "privacy_status": privacy,
        "known_failure": bool(entry.get("known_failure")),
        "needs_ground_truth": bool(entry.get("needs_ground_truth")),
        "needs_manual_review": bool(entry.get("needs_manual_review")),
        "status": "pending",
        "warnings": [],
    }

    if privacy not in ALLOWED_PRIVACY:
        result["status"] = "privacy_error"
        result["warnings"].append(f"invalid privacy_status: {privacy!r}")
        return result

    gt_status, gt_count = count_ground_truth_fields(entry.get("ground_truth_path"))
    result["ground_truth_status"] = gt_status
    result["ground_truth_field_count"] = gt_count

    try:
        pdf_path = resolve_pdf_path(entry)
    except Exception as exc:
        result["status"] = "path_error"
        result["warnings"].append(str(exc))
        return result

    result["path"] = rel(pdf_path)

    if privacy == "sensitive_do_not_store":
        if pdf_path.exists():
            try:
                pdf_path.resolve().relative_to(ROOT.resolve())
                result["warnings"].append("sensitive file is inside repo root; do not commit it")
            except ValueError:
                pass
        result["status"] = "skipped_sensitive_local_only"
        result["recommended_next_experiment"] = "Use a blank/public/synthetic surrogate before adding to committed corpus."
        return result

    try:
        assert_under_root(pdf_path, f"entry {entry.get('id')} path")
    except RuntimeError as exc:
        result["status"] = "privacy_error"
        result["warnings"].append(str(exc))
        return result

    if not pdf_path.exists():
        result["status"] = "missing"
        result["recommended_next_experiment"] = "Restore the PDF locally or mark it sensitive_do_not_store if it cannot be committed."
        return result

    signals = detect_pdf_signals(pdf_path)
    result["signals"] = signals
    if signals.get("error"):
        result["status"] = "pdf_error"
        result["warnings"].append(signals["error"])
        return result

    if signals["scanned_image_likely"] or "scanned_image" in result["lanes"]:
        result["lane_status"] = "scanned_image_needs_ocr_line_box_experiment"
        result["recommended_next_experiment"] = "OCR plus line/box detection experiment."
    elif result["ground_truth_status"] == "draft_needs_review":
        result["lane_status"] = "draft_ground_truth_needs_manual_review"
        result["recommended_next_experiment"] = "Hand-review and promote draft GT before scoring."
    elif result["ground_truth_status"] == "missing":
        result["lane_status"] = "needs_ground_truth"
        result["recommended_next_experiment"] = "Bootstrap or extract reviewed ground truth."
    else:
        result["lane_status"] = "ready_or_benchmarkable"
        result["recommended_next_experiment"] = ""

    result["detectors"] = run_detectors(pdf_path, entry)
    result["status"] = "ok"
    return result


def write_reports(results: list[dict[str, Any]], out_dir: Path, manifest_path: Path) -> None:
    results_dir = out_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        result_path = results_dir / f"{result['id']}.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    csv_path = out_dir / "summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "lanes", "status", "privacy_status", "ground_truth_status",
            "ground_truth_fields", "has_text", "has_widgets", "image_heavy",
            "scanned_image_likely", "detectors", "known_failure",
        ])
        for r in results:
            signals = r.get("signals", {})
            detectors = "; ".join(
                f"{name}:{data.get('detected_count', data.get('status'))}"
                for name, data in sorted(r.get("detectors", {}).items())
            )
            writer.writerow([
                r["id"],
                ",".join(r.get("lanes", [])),
                r["status"],
                r.get("privacy_status"),
                r.get("ground_truth_status"),
                r.get("ground_truth_field_count"),
                signals.get("has_text"),
                signals.get("has_widgets"),
                signals.get("image_heavy"),
                signals.get("scanned_image_likely"),
                detectors,
                r.get("known_failure"),
            ])

    md_path = out_dir / "scorecard.md"
    md_path.write_text(build_scorecard(results, manifest_path), encoding="utf-8")


def build_scorecard(results: list[dict[str, Any]], manifest_path: Path) -> str:
    counts_by_lane = Counter(lane for r in results for lane in r.get("lanes", []))
    counts_by_status = Counter(r["status"] for r in results)
    missing = [r for r in results if r["status"] == "missing"]
    sensitive = [r for r in results if r["status"] == "skipped_sensitive_local_only"]
    known_failures = [r for r in results if r.get("known_failure")]
    scanned = [
        r for r in results
        if r.get("signals", {}).get("scanned_image_likely") or "scanned_image" in r.get("lanes", [])
    ]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# Lab Queue Scorecard - {now}",
        "",
        f"Manifest: `{rel(manifest_path)}`",
        "",
        "## Summary",
        "",
        f"- Total documents: {len(results)}",
        f"- Missing documents: {len(missing)}",
        f"- Sensitive/local-only skipped documents: {len(sensitive)}",
        f"- Known failures: {len(known_failures)}",
        "",
        "## Counts by lane",
        "",
    ]
    for lane, count in sorted(counts_by_lane.items()):
        lines.append(f"- {lane}: {count}")
    lines.extend(["", "## Counts by status", ""])
    for status, count in sorted(counts_by_status.items()):
        lines.append(f"- {status}: {count}")

    lines.extend([
        "",
        "## Detector field counts",
        "",
        "| Document | Lanes | GT | Detectors | Lane status |",
        "| --- | --- | ---: | --- | --- |",
    ])
    for r in results:
        detector_summary = ", ".join(
            f"{name}: {data.get('detected_count', data.get('status'))}"
            for name, data in sorted(r.get("detectors", {}).items())
        ) or "-"
        gt_count = r.get("ground_truth_field_count")
        gt_text = "-" if gt_count is None else str(gt_count)
        lines.append(
            f"| `{r['id']}` | {', '.join(r.get('lanes', []))} | {gt_text} | "
            f"{detector_summary} | {r.get('lane_status', r['status'])} |"
        )

    if missing:
        lines.extend(["", "## Missing documents", ""])
        for r in missing:
            lines.append(f"- {r['id']}: `{r.get('path', '')}`")

    if sensitive:
        lines.extend(["", "## Sensitive/local-only skipped", ""])
        for r in sensitive:
            lines.append(f"- {r['id']}: local-only reference, not copied or inspected")

    if scanned:
        lines.extend(["", "## Scanned/image-only lane", ""])
        for r in scanned:
            s = r.get("signals", {})
            lines.append(
                f"- {r['id']}: fields={detector_total(r)}, text={s.get('has_text')}, "
                f"widgets={s.get('has_widgets')}, image_heavy={s.get('image_heavy')}; "
                f"next={r.get('recommended_next_experiment')}"
            )
    else:
        lines.extend([
            "",
            "## Scanned/image-only lane",
            "",
            "No scanned/image-only PDFs are currently present in the committed queue.",
        ])

    lines.extend(["", "## Known failures", ""])
    if known_failures:
        for r in known_failures:
            lines.append(f"- {r['id']}: {r.get('recommended_next_experiment') or 'Review detector performance.'}")
    else:
        lines.append("None.")

    lines.extend([
        "",
        "## Next recommended experiments",
        "",
        "- Review and promote flat-PDF draft ground truth before Lane B scoring.",
        "- Add scanned/image-only public or synthetic examples, then test OCR plus line/box detection.",
        "- Keep sensitive real failures as local-only references until a blank/public/synthetic surrogate exists.",
        "",
        "## Promotion rule",
        "",
        "No detector change can be promoted to production unless it improves lab scorecards and does not regress the AcroForm baseline.",
        "",
    ])
    return "\n".join(lines)


def detector_total(result: dict[str, Any]) -> int:
    return sum(
        data.get("detected_count", 0)
        for data in result.get("detectors", {}).values()
        if isinstance(data.get("detected_count"), int)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Queue manifest path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear the output directory first")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    assert_under_root(manifest_path, "manifest")
    assert_under_root(out_dir, "output directory")

    manifest = load_json(manifest_path)
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        print("ERROR: manifest entries must be a list", file=sys.stderr)
        return 1

    if out_dir.exists() and not args.no_clear:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Lab queue manifest: {rel(manifest_path)}")
    print(f"Output directory: {rel(out_dir)}")
    print(f"Documents: {len(entries)}")

    results = []
    for entry in entries:
        print(f"Queue {entry.get('id')} ... ", end="", flush=True)
        result = evaluate_entry(entry)
        results.append(result)
        if result["status"] == "ok":
            detector_bits = ", ".join(
                f"{name}={data.get('detected_count', data.get('status'))}"
                for name, data in sorted(result.get("detectors", {}).items())
            )
            print(f"OK {detector_bits}")
        else:
            print(result["status"])

    write_reports(results, out_dir, manifest_path)
    print(f"Scorecard: {rel(out_dir / 'scorecard.md')}")
    print(f"CSV: {rel(out_dir / 'summary.csv')}")
    print(f"JSON results: {rel(out_dir / 'results')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
