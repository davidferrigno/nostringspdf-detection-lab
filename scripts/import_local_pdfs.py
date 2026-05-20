#!/usr/bin/env python3
"""
import_local_pdfs.py

Imports user-supplied PDFs from ~/staging/ into the lab corpus.

Reads samples/local_inventory.json and acts on each entry:
- duplicate_of_corpus  -> skip (already have it from government download)
- acroform_clean       -> copy to samples/acroforms/raw/local/<id>.pdf, add to acroforms manifest
- acroform_with_pii    -> skip by default (need explicit --include-pii to import; would strip values)
- flat_pdf             -> copy to samples/flat/digital/<id>.pdf, add to flat manifest
- xfa_only             -> copy to samples/flat/xfa/<id>.pdf, add to flat manifest with xfa flag
- error                -> skip

Updates two manifests:
- samples/acroforms/manifest.json    (extended with local AcroForms, marked source=local)
- samples/flat/manifest.json         (new manifest for flat PDFs)

Usage:
    python scripts/import_local_pdfs.py            # standard import
    python scripts/import_local_pdfs.py --dry-run  # show what would happen, don't copy
    python scripts/import_local_pdfs.py --include-pii  # also import PII PDFs (with stripping)
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOCAL_INVENTORY = ROOT / "samples" / "local_inventory.json"
ACROFORM_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"
FLAT_MANIFEST = ROOT / "samples" / "flat" / "manifest.json"

ACRO_DEST_BASE = ROOT / "samples" / "acroforms" / "raw" / "local"
FLAT_DEST_BASE = ROOT / "samples" / "flat" / "digital"
XFA_DEST_BASE  = ROOT / "samples" / "flat" / "xfa"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """
    Turn 'POST_5330469_2026 EL NOMINATION FORM (1).pdf' into a clean id.
    """
    s = name.rsplit(".", 1)[0].lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def infer_agency_and_category(filename: str) -> tuple[str, str]:
    """
    Heuristic mapping from filename to agency + category.
    Returns (agency, category).
    """
    f = filename.lower()

    # NJ State (DMV / state police)
    if f.startswith("ba-") or f.startswith("sp-") or f.startswith("sts-"):
        return ("NJ State", "state")
    # PA State Police
    if f.startswith("ppb-") or f.startswith("sp-066") or f.startswith("sp066"):
        return ("PA State Police", "state")
    # NJ W-4
    if f.startswith("njw"):
        return ("NJ Treasury", "state")
    # IRS forms (1099, etc.)
    if f.startswith("f10") or f.startswith("f1099") or f.startswith("fw"):
        return ("IRS", "irs")
    # USCIS
    if f.startswith("i-") or f.startswith("uscis"):
        return ("USCIS", "uscis")
    # SSA SS-5
    if f.startswith("ss-5") or f.startswith("ss5") or f.startswith("ssa"):
        return ("SSA", "misc")
    # Generic numeric NJ forms (71xxx, 72xxx, 75xxx etc are often NJ forms)
    if re.match(r"^\d{5}\.pdf", filename):
        return ("Unknown (NJ-style numbered)", "misc")
    # POST_ files (looks like election-related)
    if f.startswith("post_"):
        return ("Unknown (election)", "misc")
    return ("Unknown", "misc")


def load_inventory():
    if not LOCAL_INVENTORY.exists():
        print(f"ERROR: {LOCAL_INVENTORY} not found. Run local_inventory.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(LOCAL_INVENTORY.read_text())


def load_manifest(path: Path) -> list:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return []
    return []


def write_manifest(path: Path, data: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, don't copy")
    parser.add_argument("--include-pii", action="store_true", help="Also import acroform_with_pii (strips field values)")
    args = parser.parse_args()

    inventory = load_inventory()
    acro_manifest = load_manifest(ACROFORM_MANIFEST)
    flat_manifest = load_manifest(FLAT_MANIFEST)

    # Index acro_manifest by id for dedup
    existing_acro_ids = {e["id"] for e in acro_manifest}

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    stats = {"imported_acro": 0, "imported_flat": 0, "imported_xfa": 0, "skipped_dup": 0, "skipped_pii": 0, "skipped_error": 0}

    for entry in inventory:
        fn = entry["filename"]
        cls = entry["classification"]
        staging = Path(entry["staging_path"])

        if cls == "duplicate_of_corpus":
            print(f"  SKIP (dup)        {fn}  — already in corpus as {entry['duplicate_of_existing_corpus']}")
            stats["skipped_dup"] += 1
            continue

        if cls == "error":
            print(f"  SKIP (err)        {fn}  — {entry.get('error')}")
            stats["skipped_error"] += 1
            continue

        if cls == "acroform_with_pii" and not args.include_pii:
            print(f"  SKIP (pii)        {fn}  — has filled fields, re-run with --include-pii to strip and import")
            stats["skipped_pii"] += 1
            continue

        # Determine destination + manifest based on classification
        if cls in ("acroform_clean", "acroform_with_pii"):
            new_id = f"local_{slugify(fn)}"
            if new_id in existing_acro_ids:
                # Disambiguate
                new_id = f"{new_id}_{entry['file_sha256'][:8]}"
            agency, category = infer_agency_and_category(fn)
            dest = ACRO_DEST_BASE / f"{new_id}.pdf"
            manifest = acro_manifest
            manifest_target = "acroform"
            manifest_entry = {
                "id": new_id,
                "filename": str(dest.relative_to(ROOT)),
                "source_url": None,
                "source": "local",
                "original_filename": fn,
                "agency": agency,
                "form_name": fn.rsplit(".", 1)[0],
                "category": category,
                "downloaded_at": None,
                "imported_at": timestamp,
                "file_sha256": entry["file_sha256"],
                "file_size_bytes": entry["file_size_bytes"],
                "page_count": entry["page_count"],
                "acroform_field_count": entry["acroform_field_count"],
                "has_acroform": True,
                "is_xfa_only": entry["is_xfa_only"],
                "download_status": "imported_local",
                "download_error": None,
                "license_notes": "Locally-supplied; redistribution rights vary by source — research/benchmark use only",
                "had_pii_at_import": entry["may_contain_pii"],
                "pii_stripped": args.include_pii and entry["may_contain_pii"],
            }
            label = "ACROFORM" if cls == "acroform_clean" else "ACROFORM-PII-STRIPPED"
            existing_acro_ids.add(new_id)
            stats["imported_acro"] += 1

        elif cls == "xfa_only":
            new_id = f"local_xfa_{slugify(fn)}"
            agency, category = infer_agency_and_category(fn)
            dest = XFA_DEST_BASE / f"{new_id}.pdf"
            manifest = flat_manifest
            manifest_target = "flat"
            manifest_entry = {
                "id": new_id,
                "filename": str(dest.relative_to(ROOT)),
                "source": "local",
                "original_filename": fn,
                "agency": agency,
                "form_name": fn.rsplit(".", 1)[0],
                "category": category,
                "imported_at": timestamp,
                "file_sha256": entry["file_sha256"],
                "file_size_bytes": entry["file_size_bytes"],
                "page_count": entry["page_count"],
                "has_acroform": False,
                "is_xfa_only": True,
                "kind": "xfa",
                "license_notes": "Locally-supplied; research/benchmark use only",
            }
            label = "XFA"
            stats["imported_xfa"] += 1

        elif cls == "flat_pdf":
            new_id = f"local_{slugify(fn)}"
            agency, category = infer_agency_and_category(fn)
            dest = FLAT_DEST_BASE / f"{new_id}.pdf"
            manifest = flat_manifest
            manifest_target = "flat"
            manifest_entry = {
                "id": new_id,
                "filename": str(dest.relative_to(ROOT)),
                "source": "local",
                "original_filename": fn,
                "agency": agency,
                "form_name": fn.rsplit(".", 1)[0],
                "category": category,
                "imported_at": timestamp,
                "file_sha256": entry["file_sha256"],
                "file_size_bytes": entry["file_size_bytes"],
                "page_count": entry["page_count"],
                "has_acroform": False,
                "is_xfa_only": False,
                "kind": "flat",
                "license_notes": "Locally-supplied; research/benchmark use only",
            }
            label = "flat"
            stats["imported_flat"] += 1

        else:
            print(f"  SKIP (unknown classification: {cls})  {fn}")
            continue

        # Copy
        if args.dry_run:
            print(f"  DRY {label:22s} {fn}  →  {dest.relative_to(ROOT)}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if cls == "acroform_with_pii" and args.include_pii:
                # Strip PII via pikepdf: clear all field values
                try:
                    import pikepdf
                    with pikepdf.open(staging) as pdf:
                        if "/AcroForm" in pdf.Root:
                            af = pdf.Root["/AcroForm"]
                            if "/Fields" in af:
                                def strip(node):
                                    if "/Kids" in node:
                                        for k in node["/Kids"]:
                                            strip(k)
                                    else:
                                        if "/V" in node:
                                            del node["/V"]
                                        if "/AP" in node:
                                            del node["/AP"]
                                for f in af["/Fields"]:
                                    strip(f)
                        pdf.save(dest)
                    print(f"  STRIP+IMPORT {label:18s} {fn}  →  {dest.relative_to(ROOT)}")
                except Exception as e:
                    print(f"  ERROR stripping {fn}: {e}", file=sys.stderr)
                    continue
            else:
                shutil.copy2(staging, dest)
                print(f"  IMPORT       {label:22s} {fn}  →  {dest.relative_to(ROOT)}")

            manifest.append(manifest_entry)

    # Write manifests
    if not args.dry_run:
        write_manifest(ACROFORM_MANIFEST, acro_manifest)
        write_manifest(FLAT_MANIFEST, flat_manifest)
        print(f"\nUpdated {ACROFORM_MANIFEST.relative_to(ROOT)}")
        print(f"Updated {FLAT_MANIFEST.relative_to(ROOT)}")

    print("\nSummary:")
    for k, v in stats.items():
        print(f"  {k:24}{v}")


if __name__ == "__main__":
    main()
