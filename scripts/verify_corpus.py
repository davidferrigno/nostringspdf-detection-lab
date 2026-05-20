#!/usr/bin/env python3
"""
verify_corpus.py

Corpus integrity check. Re-validates that the 42-PDF corpus matches its
recorded manifests and ground truth. Catches:

- Missing PDFs (manifest references file that no longer exists)
- Corrupted PDFs (SHA256 doesn't match manifest)
- Field count drift (PDF was re-downloaded, fields differ)
- Ground truth orphans (ground truth JSON exists for a PDF not in manifest)
- Manifest orphans (PDF in manifest has no ground truth)
- AcroForm regressions (pikepdf can't read field metadata anymore)

Run this before:
- Each benchmark run (catches "the corpus changed without anyone noticing")
- Adding a new backend (confirms what the backend is being tested against)
- Committing major changes (CI-style guardrail)

Guardrails:
- READ-ONLY access throughout — never modifies any file
- No production-repo paths
- Exits with code 0 if clean, non-zero on any drift
- --strict mode treats warnings as errors (for CI use)
- --verbose mode prints per-file detail
- Output is a JSON report at reports/integrity/<timestamp>_verify.json

Usage:
    python scripts/verify_corpus.py                # standard check
    python scripts/verify_corpus.py --strict       # fail on warnings too
    python scripts/verify_corpus.py --verbose      # print per-file detail
    python scripts/verify_corpus.py --skip-hash    # skip SHA256 (faster)

Exit codes:
    0 = clean (or warnings only without --strict)
    1 = error (file missing, SHA mismatch, manifest corruption, etc.)
    2 = warnings exist and --strict was specified
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import pikepdf
except ImportError:
    print("ERROR: pikepdf not installed.", file=sys.stderr)
    sys.exit(1)


VERIFIER_VERSION = "v1"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ACROFORM_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"
FLAT_MANIFEST = ROOT / "samples" / "flat" / "manifest.json"
GROUND_TRUTH_DIR = ROOT / "benchmarks" / "ground_truth"
REPORTS_DIR = ROOT / "reports" / "integrity"


def assert_safe_output_path(path: Path) -> None:
    """Guardrail: refuse to write outside reports/integrity/."""
    resolved = path.resolve()
    expected = REPORTS_DIR.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError:
        raise RuntimeError(f"Refused to write outside {expected}: {resolved}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def count_acroform_fields(pdf_path: Path) -> tuple[int, str | None]:
    """
    Re-count AcroForm leaf fields by walking /Kids. Same logic as
    download_acroforms.py's verifier. Returns (count, error_str).
    """
    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root
            if "/AcroForm" not in root:
                return (0, None)
            af = root["/AcroForm"]
            if "/Fields" not in af:
                return (0, None)

            def count_leaves(node):
                c = 0
                if "/Kids" in node:
                    for kid in node["/Kids"]:
                        c += count_leaves(kid)
                else:
                    c += 1
                return c

            total = 0
            for f in af["/Fields"]:
                total += count_leaves(f)
            return (total, None)
    except Exception as e:
        return (0, f"{type(e).__name__}: {e}")


def get_page_count(pdf_path: Path) -> tuple[int, str | None]:
    try:
        with pikepdf.open(pdf_path) as pdf:
            return (len(pdf.pages), None)
    except Exception as e:
        return (0, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Per-PDF verification
# ---------------------------------------------------------------------------

def verify_pdf(entry: dict, manifest_kind: str, skip_hash: bool, verbose: bool) -> dict:
    """
    Verify one PDF entry from a manifest. Returns dict with:
        pdf_id: str
        manifest_kind: 'acroform' or 'flat'
        errors:   list of severity-error issues
        warnings: list of severity-warning issues
        info:     dict of resolved values (sha256, field_count, page_count)
    """
    pdf_id = entry["id"]
    rel_path = entry["filename"]
    pdf_path = ROOT / rel_path

    result = {
        "pdf_id": pdf_id,
        "manifest_kind": manifest_kind,
        "filename": rel_path,
        "errors": [],
        "warnings": [],
        "info": {},
    }

    if not pdf_path.exists():
        result["errors"].append(f"PDF file missing at {rel_path}")
        return result

    # Page count check
    page_count, page_err = get_page_count(pdf_path)
    if page_err:
        result["errors"].append(f"Could not open PDF: {page_err}")
        return result
    result["info"]["page_count"] = page_count

    expected_page_count = entry.get("page_count")
    if expected_page_count is not None and page_count != expected_page_count:
        result["errors"].append(
            f"page_count drift: PDF has {page_count}, manifest says {expected_page_count}"
        )

    # SHA256 check (expensive — skippable)
    if not skip_hash:
        actual_sha = sha256_of(pdf_path)
        result["info"]["file_sha256"] = actual_sha
        expected_sha = entry.get("file_sha256")
        if expected_sha and actual_sha != expected_sha:
            result["errors"].append(
                f"SHA256 mismatch: PDF is {actual_sha[:16]}..., manifest says {expected_sha[:16]}..."
            )

    # File size check (cheap)
    actual_size = pdf_path.stat().st_size
    result["info"]["file_size_bytes"] = actual_size
    expected_size = entry.get("file_size_bytes")
    if expected_size and actual_size != expected_size:
        result["errors"].append(
            f"file_size drift: PDF is {actual_size:,}, manifest says {expected_size:,}"
        )

    # Acroform-only checks
    if manifest_kind == "acroform":
        expected_field_count = entry.get("acroform_field_count", 0)
        actual_field_count, field_err = count_acroform_fields(pdf_path)
        if field_err:
            result["errors"].append(f"AcroForm field count failed: {field_err}")
        else:
            result["info"]["acroform_field_count"] = actual_field_count
            if actual_field_count != expected_field_count:
                result["errors"].append(
                    f"acroform_field_count drift: PDF has {actual_field_count}, "
                    f"manifest says {expected_field_count}"
                )

    if verbose:
        print(f"  {pdf_id}: pages={result['info'].get('page_count')} "
              f"size={result['info'].get('file_size_bytes', 0):,} "
              f"fields={result['info'].get('acroform_field_count', '-')} "
              f"errors={len(result['errors'])} warnings={len(result['warnings'])}")

    return result


# ---------------------------------------------------------------------------
# Ground-truth cross-check
# ---------------------------------------------------------------------------

def verify_ground_truth_coverage(acroform_manifest: list, gt_files: list, verbose: bool) -> dict:
    """
    Check correspondence between AcroForm manifest entries and ground
    truth JSONs.

    Every AcroForm in manifest with has_acroform=True should have a
    ground truth JSON. Every ground truth JSON should correspond to a
    PDF in the manifest.

    Field counts in ground truth should match manifest.
    """
    coverage = {
        "errors": [],
        "warnings": [],
        "manifest_acroforms": 0,
        "gt_files_found": 0,
        "manifest_pdfs_without_gt": [],
        "gt_files_without_manifest": [],
        "gt_field_count_mismatches": [],
    }

    # Build lookup: pdf_id -> manifest entry (only AcroForms)
    acroform_by_id = {}
    for e in acroform_manifest:
        if e.get("has_acroform", False):
            acroform_by_id[e["id"]] = e
    coverage["manifest_acroforms"] = len(acroform_by_id)

    # Build lookup: gt stem -> path
    gt_by_stem = {p.stem: p for p in gt_files if not p.name.startswith("_")}
    coverage["gt_files_found"] = len(gt_by_stem)

    # Check: every AcroForm manifest entry should have a GT file
    for pdf_id, manifest_entry in acroform_by_id.items():
        # Ground truth filename is the PDF stem (e.g., irs_w9.pdf -> irs_w9.json)
        pdf_stem = Path(manifest_entry["filename"]).stem
        if pdf_stem not in gt_by_stem:
            coverage["manifest_pdfs_without_gt"].append(pdf_id)
            coverage["errors"].append(
                f"AcroForm {pdf_id} (stem={pdf_stem}) has no ground truth JSON"
            )

    # Check: every GT file should correspond to a manifest entry
    manifest_stems = {Path(e["filename"]).stem for e in acroform_manifest}
    for stem, gt_path in gt_by_stem.items():
        if stem not in manifest_stems:
            coverage["gt_files_without_manifest"].append(stem)
            coverage["warnings"].append(
                f"Ground truth {stem}.json has no matching PDF in manifest"
            )

    # Check: GT field counts should match manifest
    for pdf_id, manifest_entry in acroform_by_id.items():
        pdf_stem = Path(manifest_entry["filename"]).stem
        if pdf_stem not in gt_by_stem:
            continue
        try:
            gt = json.loads(gt_by_stem[pdf_stem].read_text())
            gt_field_count = len(gt.get("fields", []))
            manifest_field_count = manifest_entry.get("acroform_field_count", 0)
            if gt_field_count != manifest_field_count:
                coverage["gt_field_count_mismatches"].append({
                    "pdf_id": pdf_id,
                    "gt_count": gt_field_count,
                    "manifest_count": manifest_field_count,
                })
                coverage["errors"].append(
                    f"Field count mismatch for {pdf_id}: "
                    f"ground truth has {gt_field_count}, manifest says {manifest_field_count}"
                )
        except Exception as e:
            coverage["warnings"].append(
                f"Could not validate ground truth for {pdf_id}: {type(e).__name__}: {e}"
            )

    return coverage


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="Treat warnings as errors (exit non-zero)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-PDF detail during verification")
    parser.add_argument("--skip-hash", action="store_true",
                        help="Skip SHA256 verification (faster, less thorough)")
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"{'='*72}")
    print(f"verify_corpus.py {VERIFIER_VERSION}")
    print(f"Timestamp: {timestamp}")
    if args.strict:
        print("MODE: STRICT -- warnings exit non-zero")
    if args.skip_hash:
        print("MODE: SKIP HASH -- not re-checking SHA256")
    print(f"{'='*72}")

    # Load manifests
    if not ACROFORM_MANIFEST.exists():
        print(f"ERROR: {ACROFORM_MANIFEST} not found", file=sys.stderr)
        sys.exit(1)
    if not FLAT_MANIFEST.exists():
        print(f"ERROR: {FLAT_MANIFEST} not found", file=sys.stderr)
        sys.exit(1)

    acroform_manifest = json.loads(ACROFORM_MANIFEST.read_text())
    flat_manifest = json.loads(FLAT_MANIFEST.read_text())

    print(f"\nManifests loaded:")
    print(f"  acroform manifest: {len(acroform_manifest)} entries")
    print(f"  flat manifest:     {len(flat_manifest)} entries")

    # 1. Verify each acroform PDF
    print(f"\n--- Verifying AcroForm PDFs ---")
    if args.verbose:
        print()
    acroform_results = []
    for entry in acroform_manifest:
        r = verify_pdf(entry, "acroform", args.skip_hash, args.verbose)
        acroform_results.append(r)

    # 2. Verify each flat PDF
    print(f"\n--- Verifying flat PDFs ---")
    if args.verbose:
        print()
    flat_results = []
    for entry in flat_manifest:
        r = verify_pdf(entry, "flat", args.skip_hash, args.verbose)
        flat_results.append(r)

    # 3. Ground truth coverage check
    print(f"\n--- Cross-checking ground truth ---")
    if GROUND_TRUTH_DIR.exists():
        gt_files = sorted(GROUND_TRUTH_DIR.glob("*.json"))
        coverage = verify_ground_truth_coverage(acroform_manifest, gt_files, args.verbose)
        print(f"  AcroForm manifest entries: {coverage['manifest_acroforms']}")
        print(f"  Ground truth files found: {coverage['gt_files_found']}")
        print(f"  Manifest PDFs without GT: {len(coverage['manifest_pdfs_without_gt'])}")
        print(f"  GT files without manifest: {len(coverage['gt_files_without_manifest'])}")
        print(f"  Field count mismatches: {len(coverage['gt_field_count_mismatches'])}")
    else:
        coverage = {
            "errors": [],
            "warnings": [f"Ground truth dir does not exist at {GROUND_TRUTH_DIR}"],
            "manifest_acroforms": 0,
            "gt_files_found": 0,
            "manifest_pdfs_without_gt": [],
            "gt_files_without_manifest": [],
            "gt_field_count_mismatches": [],
        }
        print(f"  WARNING: ground truth dir missing — coverage check skipped")

    # Aggregate
    all_errors = []
    all_warnings = []
    for r in acroform_results + flat_results:
        for e in r["errors"]:
            all_errors.append(f"[{r['pdf_id']}] {e}")
        for w in r["warnings"]:
            all_warnings.append(f"[{r['pdf_id']}] {w}")
    all_errors.extend(coverage["errors"])
    all_warnings.extend(coverage["warnings"])

    # Summary
    print(f"\n{'='*72}")
    print(f"SUMMARY")
    print(f"{'='*72}")
    print(f"AcroForm PDFs verified: {len(acroform_results)}")
    print(f"Flat PDFs verified: {len(flat_results)}")
    print(f"Total errors: {len(all_errors)}")
    print(f"Total warnings: {len(all_warnings)}")

    if all_errors:
        print(f"\n[!] ERRORS:")
        for e in all_errors:
            print(f"  - {e}")

    if all_warnings:
        print(f"\n[!] WARNINGS:")
        for w in all_warnings:
            print(f"  - {w}")

    # Write report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_filename = datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_verify.json"
    report_path = REPORTS_DIR / report_filename
    assert_safe_output_path(report_path)

    report = {
        "verifier_version": VERIFIER_VERSION,
        "timestamp": timestamp,
        "options": {
            "strict": args.strict,
            "skip_hash": args.skip_hash,
        },
        "summary": {
            "acroform_pdfs_verified": len(acroform_results),
            "flat_pdfs_verified": len(flat_results),
            "total_errors": len(all_errors),
            "total_warnings": len(all_warnings),
        },
        "errors": all_errors,
        "warnings": all_warnings,
        "acroform_results": acroform_results,
        "flat_results": flat_results,
        "ground_truth_coverage": coverage,
    }
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport written: {report_path.relative_to(ROOT)}")

    # Exit code
    if all_errors:
        print(f"\nFAIL: {len(all_errors)} error(s) detected.", file=sys.stderr)
        sys.exit(1)
    if args.strict and all_warnings:
        print(f"\nFAIL (strict): {len(all_warnings)} warning(s) detected.", file=sys.stderr)
        sys.exit(2)

    print(f"\nPASS: corpus integrity verified.")
    sys.exit(0)


if __name__ == "__main__":
    main()
