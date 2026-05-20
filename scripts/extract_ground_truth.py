#!/usr/bin/env python3
"""
extract_ground_truth.py

Walks samples/acroforms/raw/ and extracts AcroForm widget metadata from
each PDF, producing canonical ground truth JSON files in:

    benchmarks/ground_truth/<original_filename>.json

For AcroForm PDFs the ground truth is essentially "free" because the
PDF itself declares every form field's name, type, position, and page.
The PDF IS the authoritative source — we're not labeling, we're reading
metadata that the PDF publisher already encoded.

Schema (matches docs/legacy/detection-measurement-guide.md):

    {
        "pdf": "filename.pdf",
        "pdf_id": "irs_w9",
        "source": "government" | "local",
        "page_count": 6,
        "labeled_at": "2026-05-21",
        "labeled_by": "extract_ground_truth.py v2",
        "review_status": "draft",
        "extraction_method": "acroform_widgets",
        "coordinate_convention": "top-left origin, PDF points",
        "fields": [
            {
                "id": "f1",
                "page": 1,
                "type": "text",       // or "checkbox", "radio", "choice", "signature", "pushbutton"
                "bbox": [x, y, width, height],   // PDF points, top-left origin
                "label": "fully_qualified_field_name",
                "group_id": "radio_group_name"   // only for radio buttons
            }
        ],
        "warnings": []
    }

Guardrails enforced:
- Read-only: PDFs are opened with pikepdf but NEVER saved or modified
- No production-repo paths: all operations stay within detection-lab
- One JSON per source PDF (no merged outputs)
- Field counts cross-checked against samples/acroforms/manifest.json
- XFA-only PDFs flagged in warnings
- Missing bbox / orphan widgets flagged in warnings
- Coordinates normalized to top-left origin, PDF points (matches production)
- Dry-run mode supported (--dry-run prints what would be extracted, no writes)
- Strict mode supported (--strict exits non-zero if any warnings)
- Output paths asserted to be inside benchmarks/ground_truth/ (no escapes)

Usage:
    python scripts/extract_ground_truth.py             # standard run
    python scripts/extract_ground_truth.py --dry-run   # report only, no writes
    python scripts/extract_ground_truth.py --strict    # fail on any warning

Output:
    benchmarks/ground_truth/<pdf_filename>.json        (one per AcroForm PDF)
    benchmarks/ground_truth/_extraction_summary.json   (machine-readable)
    benchmarks/ground_truth/_extraction_summary.csv    (human-readable)
"""

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

try:
    import pikepdf
except ImportError:
    print("ERROR: pikepdf not installed.", file=sys.stderr)
    sys.exit(1)


EXTRACTOR_VERSION = "v2"


# ---------------------------------------------------------------------------
# Paths (all within detection-lab; guardrail: no production-repo refs)
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ACROFORM_RAW = ROOT / "samples" / "acroforms" / "raw"
ACROFORM_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"
GROUND_TRUTH_DIR = ROOT / "benchmarks" / "ground_truth"
SUMMARY_JSON = GROUND_TRUTH_DIR / "_extraction_summary.json"
SUMMARY_CSV = GROUND_TRUTH_DIR / "_extraction_summary.csv"


def assert_safe_output_path(path: Path) -> None:
    """Guardrail: refuse to write outside benchmarks/ground_truth/."""
    resolved = path.resolve()
    expected = GROUND_TRUTH_DIR.resolve()
    if expected not in resolved.parents and resolved.parent != expected:
        raise RuntimeError(f"Refused to write outside {expected}: {resolved}")


# ---------------------------------------------------------------------------
# Field type mapping
# ---------------------------------------------------------------------------

def field_type_from_node(node) -> str:
    """
    Map PDF field type codes to canonical schema.

    PDF field type codes:
      /Tx  - text
      /Btn - button (checkbox/radio/pushbutton via /Ff bits)
      /Ch  - choice
      /Sig - signature

    /Ff flag bits for /Btn:
      bit 16 (0x10000) - Radio
      bit 17 (0x20000) - Pushbutton
      otherwise        - Checkbox
    """
    try:
        ft = node.get("/FT", None)
    except Exception:
        return "unknown"
    if ft is None:
        return "unknown"
    ft_str = str(ft)

    if ft_str == "/Tx":
        return "text"
    elif ft_str == "/Btn":
        try:
            ff = node.get("/Ff", 0)
            ff_int = int(ff)
        except (TypeError, ValueError, AttributeError):
            ff_int = 0
        if ff_int & 0x10000:
            return "radio"
        elif ff_int & 0x20000:
            return "pushbutton"
        else:
            return "checkbox"
    elif ft_str == "/Ch":
        return "choice"
    elif ft_str == "/Sig":
        return "signature"
    else:
        return ft_str.lstrip("/").lower()


def resolve_type_via_parent_chain(node) -> str:
    """Walk /Parent chain until a node with resolvable /FT is found."""
    cursor = node
    safety = 20
    while safety > 0:
        ft = field_type_from_node(cursor)
        if ft != "unknown":
            return ft
        try:
            parent = cursor.get("/Parent", None)
        except Exception:
            break
        if parent is None:
            break
        cursor = parent
        safety -= 1
    return "unknown"


def resolve_full_field_name(node) -> str:
    """Walk /Parent chain assembling /T values into dotted full name."""
    parts = []
    cursor = node
    safety = 20
    while safety > 0:
        try:
            t = cursor.get("/T", None)
        except Exception:
            break
        if t is not None:
            parts.append(str(t))
        try:
            parent = cursor.get("/Parent", None)
        except Exception:
            break
        if parent is None:
            break
        cursor = parent
        safety -= 1
    return ".".join(reversed(parts)) if parts else ""


def get_rect(annot) -> list | None:
    """Extract /Rect [x_ll, y_ll, x_ur, y_ur] in PDF points, or None."""
    try:
        rect = annot.get("/Rect", None)
    except Exception:
        return None
    if rect is None:
        return None
    try:
        return [float(v) for v in rect]
    except (TypeError, ValueError):
        return None


def rect_to_bbox_top_left(rect: list, page_height: float) -> list:
    """
    Convert PDF native [x_ll, y_ll, x_ur, y_ur] (bottom-left origin)
    to canonical [x, y, width, height] (top-left origin, PDF points).

    GUARDRAIL: assert all output values are finite, width/height positive.
    """
    x_ll, y_ll, x_ur, y_ur = rect
    x = min(x_ll, x_ur)
    width = abs(x_ur - x_ll)
    height = abs(y_ur - y_ll)
    y_bottom = min(y_ll, y_ur)
    y_top = page_height - y_bottom - height

    bbox = [round(x, 2), round(y_top, 2), round(width, 2), round(height, 2)]

    for v in bbox:
        if not isinstance(v, (int, float)):
            raise ValueError(f"bbox value not numeric: {bbox}")
        if v != v:  # NaN
            raise ValueError(f"bbox contains NaN: {bbox}")
    if bbox[2] <= 0 or bbox[3] <= 0:
        raise ValueError(f"bbox has non-positive width/height: {bbox}")

    return bbox


def check_xfa_presence(pdf) -> bool:
    """Detect XFA forms via /AcroForm /XFA entry."""
    try:
        root = pdf.Root
        if "/AcroForm" in root:
            af = root["/AcroForm"]
            return "/XFA" in af
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Per-PDF extraction
# ---------------------------------------------------------------------------

def extract_pdf(pdf_path: Path, pdf_id: str, source: str) -> dict:
    """
    Extract ground truth for one PDF.
    Guardrail: PDF is opened read-only and never saved.
    """
    result = {
        "pdf": pdf_path.name,
        "pdf_id": pdf_id,
        "source": source,
        "page_count": 0,
        "labeled_at": date.today().isoformat(),
        "labeled_by": f"extract_ground_truth.py {EXTRACTOR_VERSION}",
        "review_status": "draft",
        "extraction_method": "acroform_widgets",
        "coordinate_convention": "top-left origin, PDF points",
        "fields": [],
        "warnings": [],
        "error": None,
    }

    try:
        # GUARDRAIL: read-only open. No pdf.save() anywhere in this function.
        with pikepdf.open(pdf_path) as pdf:
            result["page_count"] = len(pdf.pages)

            if check_xfa_presence(pdf):
                result["warnings"].append(
                    "XFA dictionary present alongside AcroForm — possible hybrid form"
                )

            field_counter = 0
            seen_widgets = set()
            widgets_without_rect = 0
            widgets_with_unknown_type = 0

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
                    result["warnings"].append(
                        f"Page {page_idx+1}: could not read page height; skipping page"
                    )
                    continue

                for annot in annots:
                    try:
                        subtype = annot.get("/Subtype", None)
                    except Exception:
                        continue
                    if subtype is None or str(subtype) != "/Widget":
                        continue

                    try:
                        key = annot.objgen
                        if key in seen_widgets:
                            continue
                        seen_widgets.add(key)
                    except Exception:
                        pass

                    rect = get_rect(annot)
                    if rect is None:
                        widgets_without_rect += 1
                        continue

                    field_type = resolve_type_via_parent_chain(annot)
                    if field_type == "unknown":
                        widgets_with_unknown_type += 1
                        field_type = "text"

                    full_name = resolve_full_field_name(annot)
                    if not full_name:
                        full_name = f"unnamed_widget_{field_counter+1}"

                    try:
                        bbox = rect_to_bbox_top_left(rect, page_height)
                    except ValueError as e:
                        result["warnings"].append(
                            f"Page {page_idx+1}: invalid bbox for field '{full_name}': {e}"
                        )
                        continue

                    field_counter += 1
                    entry = {
                        "id": f"f{field_counter}",
                        "page": page_idx + 1,
                        "type": field_type,
                        "bbox": bbox,
                        "label": full_name,
                    }

                    if field_type in ("radio", "checkbox"):
                        try:
                            as_state = annot.get("/AS", None)
                            if as_state is not None:
                                entry["state"] = str(as_state).lstrip("/")
                        except Exception:
                            pass
                        if field_type == "radio" and "." in full_name:
                            entry["group_id"] = full_name.rsplit(".", 1)[0]

                    result["fields"].append(entry)

            if widgets_without_rect > 0:
                result["warnings"].append(
                    f"{widgets_without_rect} widget(s) had no /Rect and were skipped"
                )
            if widgets_with_unknown_type > 0:
                result["warnings"].append(
                    f"{widgets_with_unknown_type} widget(s) had unresolvable type, defaulted to 'text'"
                )

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Extract and report, but do not write any output files")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero if any PDF produces warnings")
    args = parser.parse_args()

    if not ACROFORM_MANIFEST.exists():
        print(f"ERROR: {ACROFORM_MANIFEST} not found.", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(ACROFORM_MANIFEST.read_text())

    if not args.dry_run:
        GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)

    summary = {
        "extracted_at": date.today().isoformat(),
        "extractor_version": EXTRACTOR_VERSION,
        "coordinate_convention": "top-left origin, PDF points",
        "total_pdfs": 0,
        "total_fields": 0,
        "total_warnings": 0,
        "per_pdf": [],
        "errors": [],
    }

    print(f"{'='*72}")
    print(f"extract_ground_truth.py {EXTRACTOR_VERSION}")
    if args.dry_run:
        print("MODE: DRY RUN -- no files will be written")
    if args.strict:
        print("MODE: STRICT -- any warnings will cause non-zero exit")
    print(f"Manifest: {ACROFORM_MANIFEST}")
    print(f"Output dir: {GROUND_TRUTH_DIR}")
    print(f"{'='*72}")

    any_warnings = False

    for entry in manifest:
        pdf_id = entry["id"]
        rel_path = entry["filename"]
        pdf_path = ROOT / rel_path
        source = entry.get("source", "government")

        if not pdf_path.exists():
            print(f"SKIP {pdf_id}: file not found at {pdf_path}")
            summary["errors"].append({"pdf_id": pdf_id, "error": "file not found"})
            continue

        if not entry.get("has_acroform", False):
            print(f"SKIP {pdf_id}: not an AcroForm per manifest")
            continue

        print(f"Extracting {pdf_id:30s} ... ", end="", flush=True)
        gt = extract_pdf(pdf_path, pdf_id, source)

        if gt["error"]:
            print(f"ERROR: {gt['error']}")
            summary["errors"].append({"pdf_id": pdf_id, "error": gt["error"]})
            continue

        manifest_count = entry.get("acroform_field_count", 0)
        extracted_count = len(gt["fields"])
        match_status = ""
        if manifest_count > 0:
            diff = extracted_count - manifest_count
            if diff == 0:
                match_status = "OK"
            else:
                match_status = f"({diff:+d} vs manifest {manifest_count})"

        type_breakdown = {}
        for f in gt["fields"]:
            type_breakdown[f["type"]] = type_breakdown.get(f["type"], 0) + 1

        per_page = {}
        for f in gt["fields"]:
            p = str(f["page"])
            per_page[p] = per_page.get(p, 0) + 1

        gt_filename = f"{pdf_path.stem}.json"
        gt_path = GROUND_TRUTH_DIR / gt_filename
        if not args.dry_run:
            assert_safe_output_path(gt_path)
            gt_path.write_text(json.dumps(gt, indent=2))

        summary["per_pdf"].append({
            "pdf_id": pdf_id,
            "pdf": gt["pdf"],
            "page_count": gt["page_count"],
            "field_count": extracted_count,
            "manifest_count": manifest_count,
            "match_manifest": extracted_count == manifest_count,
            "types": type_breakdown,
            "per_page": per_page,
            "warnings_count": len(gt["warnings"]),
            "warnings": gt["warnings"],
            "ground_truth_file": str(gt_path.relative_to(ROOT)) if not args.dry_run else "(dry-run)",
        })

        summary["total_pdfs"] += 1
        summary["total_fields"] += extracted_count
        summary["total_warnings"] += len(gt["warnings"])
        if gt["warnings"]:
            any_warnings = True

        types_str = ", ".join(f"{t}:{n}" for t, n in sorted(type_breakdown.items()))
        warn_str = f" [WARNS: {len(gt['warnings'])}]" if gt["warnings"] else ""
        print(f"{extracted_count:4d} fields  {match_status:30s} {types_str}{warn_str}")

    print(f"{'='*72}")
    print(f"Total PDFs processed: {summary['total_pdfs']}")
    print(f"Total fields extracted: {summary['total_fields']}")
    print(f"Total warnings: {summary['total_warnings']}")
    print(f"Errors: {len(summary['errors'])}")

    mismatches = [p for p in summary["per_pdf"] if not p["match_manifest"]]
    if mismatches:
        print(f"\nField count mismatches (extracted vs manifest):")
        for m in mismatches:
            diff = m["field_count"] - m["manifest_count"]
            print(f"  {m['pdf_id']:30s} extracted {m['field_count']:4d}, manifest {m['manifest_count']:4d}  (diff {diff:+d})")

    warned = [p for p in summary["per_pdf"] if p["warnings_count"] > 0]
    if warned:
        print(f"\nPDFs with warnings:")
        for w in warned:
            print(f"  {w['pdf_id']}:")
            for msg in w["warnings"]:
                print(f"    - {msg}")

    if not args.dry_run:
        assert_safe_output_path(SUMMARY_JSON)
        assert_safe_output_path(SUMMARY_CSV)
        SUMMARY_JSON.write_text(json.dumps(summary, indent=2))

        with SUMMARY_CSV.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "pdf_id", "pdf", "page_count", "field_count", "manifest_count",
                "match_manifest", "warnings_count",
                "n_text", "n_checkbox", "n_radio", "n_choice", "n_signature", "n_pushbutton",
            ])
            for p in summary["per_pdf"]:
                t = p["types"]
                writer.writerow([
                    p["pdf_id"], p["pdf"], p["page_count"], p["field_count"],
                    p["manifest_count"], p["match_manifest"], p["warnings_count"],
                    t.get("text", 0), t.get("checkbox", 0), t.get("radio", 0),
                    t.get("choice", 0), t.get("signature", 0), t.get("pushbutton", 0),
                ])

        print(f"\nWrote {SUMMARY_JSON.relative_to(ROOT)}")
        print(f"Wrote {SUMMARY_CSV.relative_to(ROOT)}")
    else:
        print(f"\n(dry-run: no files written)")

    if args.strict and any_warnings:
        print("\nStrict mode: warnings detected. Exiting non-zero.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
