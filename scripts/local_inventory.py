#!/usr/bin/env python3
"""
local_inventory.py

Inventories user-supplied PDFs in ~/staging/ and produces a JSON report
describing what was found. Does NOT copy any PDFs into the corpus — that
decision happens after review.

For each PDF, captures:
- file metadata (sha256, size)
- pdf structure (page count, has_acroform, field count, xfa flag)
- content fingerprint (text length, first 200 chars heuristic)
- PII risk indicators (any non-empty AcroForm field default values?)
- corpus dedup (matches sha256 against samples/acroforms/manifest.json)

Usage:
    cd ~/detection-lab
    source .venv/bin/activate
    python scripts/local_inventory.py

Output:
    samples/local_inventory.json
    samples/local_inventory_report.txt    (human-readable)

Important: any PDF that has filled-in AcroForm field values is flagged as
"may_contain_pii". You should review those before deciding to commit them
into the corpus (or strip the field values during import).
"""

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


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
STAGING_DIRS = [
    (Path.home() / "staging" / "fillable", "fillable"),
    (Path.home() / "staging" / "flat",     "flat"),
]
OUT_JSON   = ROOT / "samples" / "local_inventory.json"
OUT_REPORT = ROOT / "samples" / "local_inventory_report.txt"
EXISTING_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_str(v) -> str:
    """Best-effort string from a pikepdf value."""
    try:
        if v is None:
            return ""
        s = str(v)
        return s
    except Exception:
        return ""


def inspect_pdf(path: Path) -> dict:
    """
    Open the PDF and gather structural + content fingerprints.
    """
    result = {
        "page_count": 0,
        "has_acroform": False,
        "acroform_field_count": 0,
        "is_xfa_only": False,
        "filled_field_count": 0,
        "filled_field_samples": [],
        "may_contain_pii": False,
        "error": None,
    }

    try:
        with pikepdf.open(path) as pdf:
            result["page_count"] = len(pdf.pages)
            root = pdf.Root

            if "/AcroForm" in root:
                acroform = root["/AcroForm"]
                if "/Fields" in acroform:
                    fields = acroform["/Fields"]

                    filled_count = 0
                    samples = []

                    def walk(node):
                        nonlocal filled_count
                        if "/Kids" in node:
                            for kid in node["/Kids"]:
                                walk(kid)
                        else:
                            # leaf field
                            name = safe_str(node.get("/T", ""))
                            value = node.get("/V", None)
                            if value is not None:
                                val_str = safe_str(value).strip()
                                if val_str and val_str not in ("/Off", "Off", "<null>", "(null)"):
                                    filled_count += 1
                                    if len(samples) < 5:
                                        # Show only field name + first 3 chars of value (redacted)
                                        redacted = val_str[:3] + "..." if len(val_str) > 3 else val_str
                                        samples.append(f"{name}={redacted}")

                    def count_leaves(node):
                        c = 0
                        if "/Kids" in node:
                            for kid in node["/Kids"]:
                                c += count_leaves(kid)
                        else:
                            c += 1
                        return c

                    total = 0
                    for f in fields:
                        total += count_leaves(f)
                        walk(f)

                    result["acroform_field_count"] = total
                    result["has_acroform"] = total > 0
                    result["filled_field_count"] = filled_count
                    result["filled_field_samples"] = samples
                    result["may_contain_pii"] = filled_count > 0

                # XFA check
                if "/XFA" in acroform and result["acroform_field_count"] == 0:
                    result["is_xfa_only"] = True

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


def load_existing_corpus_hashes() -> dict:
    """
    Returns {sha256: existing_id} so we can detect duplicates.
    """
    if not EXISTING_MANIFEST.exists():
        return {}
    try:
        data = json.loads(EXISTING_MANIFEST.read_text())
        return {entry["file_sha256"]: entry["id"] for entry in data if entry.get("file_sha256")}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = load_existing_corpus_hashes()
    print(f"Loaded {len(existing)} existing corpus hashes for dedup")

    inventory = []
    classification_counts = {
        "acroform_clean":        0,
        "acroform_with_pii":     0,
        "flat_pdf":              0,
        "xfa_only":              0,
        "error":                 0,
        "duplicate_of_corpus":   0,
    }

    for staging_dir, source_label in STAGING_DIRS:
        if not staging_dir.exists():
            print(f"WARN: {staging_dir} not found, skipping")
            continue
        pdfs = sorted(staging_dir.glob("*.pdf")) + sorted(staging_dir.glob("*.PDF"))
        print(f"\n=== {source_label}: {len(pdfs)} PDFs ===")
        for pdf_path in pdfs:
            try:
                size = pdf_path.stat().st_size
                sha = sha256_of(pdf_path)
                info = inspect_pdf(pdf_path)

                dup_of = existing.get(sha)
                entry = {
                    "filename": pdf_path.name,
                    "source_folder": source_label,
                    "staging_path": str(pdf_path),
                    "file_size_bytes": size,
                    "file_sha256": sha,
                    "page_count": info["page_count"],
                    "has_acroform": info["has_acroform"],
                    "acroform_field_count": info["acroform_field_count"],
                    "is_xfa_only": info["is_xfa_only"],
                    "filled_field_count": info["filled_field_count"],
                    "filled_field_samples": info["filled_field_samples"],
                    "may_contain_pii": info["may_contain_pii"],
                    "duplicate_of_existing_corpus": dup_of,
                    "error": info["error"],
                    "inspected_at": timestamp,
                }

                # Classify
                if info["error"]:
                    cls = "error"
                elif dup_of:
                    cls = "duplicate_of_corpus"
                elif info["is_xfa_only"]:
                    cls = "xfa_only"
                elif info["has_acroform"]:
                    cls = "acroform_with_pii" if info["may_contain_pii"] else "acroform_clean"
                else:
                    cls = "flat_pdf"
                entry["classification"] = cls
                classification_counts[cls] += 1

                # Compact summary line
                tag = {
                    "acroform_clean":      "ACROFORM",
                    "acroform_with_pii":   "ACROFORM*PII",
                    "flat_pdf":            "flat",
                    "xfa_only":            "XFA",
                    "error":               "ERROR",
                    "duplicate_of_corpus": "DUP",
                }[cls]
                print(f"  [{tag:13}] {pdf_path.name}: {info['page_count']}p, {info['acroform_field_count']} fields"
                      + (f" -> dup of {dup_of}" if dup_of else "")
                      + (f"; {info['filled_field_count']} filled" if info['filled_field_count'] else "")
                      + (f"; err: {info['error']}" if info['error'] else ""))

                inventory.append(entry)
            except Exception as e:
                print(f"  ERROR processing {pdf_path.name}: {e}")

    # Save outputs
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(inventory, indent=2))
    print(f"\nWrote {OUT_JSON}")

    # Human-readable report
    lines = []
    lines.append(f"Local PDF Inventory Report")
    lines.append(f"Generated: {timestamp}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Summary by classification:")
    for cls, n in classification_counts.items():
        lines.append(f"  {cls:24} {n:3d}")
    lines.append("")
    lines.append(f"Total inventoried: {len(inventory)}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("DETAILS")
    lines.append("=" * 60)

    for entry in inventory:
        lines.append("")
        lines.append(f"[{entry['classification']}] {entry['filename']}")
        lines.append(f"  source:      {entry['source_folder']}")
        lines.append(f"  pages:       {entry['page_count']}")
        lines.append(f"  size:        {entry['file_size_bytes']:,} bytes")
        lines.append(f"  acroform:    {entry['has_acroform']} ({entry['acroform_field_count']} fields)")
        if entry['is_xfa_only']:
            lines.append(f"  XFA-only:    True")
        if entry['filled_field_count']:
            lines.append(f"  FILLED:      {entry['filled_field_count']} fields contain values (POSSIBLE PII)")
            for s in entry['filled_field_samples']:
                lines.append(f"               {s}")
        if entry['duplicate_of_existing_corpus']:
            lines.append(f"  duplicate of:  {entry['duplicate_of_existing_corpus']} (already in corpus)")
        if entry['error']:
            lines.append(f"  ERROR:       {entry['error']}")
        lines.append(f"  sha256:      {entry['file_sha256']}")

    lines.append("")
    lines.append("=" * 60)
    lines.append("RECOMMENDATIONS")
    lines.append("=" * 60)
    lines.append("")
    lines.append("acroform_clean:     candidates to import as-is into samples/acroforms/raw/local/")
    lines.append("acroform_with_pii:  REVIEW before import — strip field values during import")
    lines.append("flat_pdf:           candidates for samples/flat/digital/")
    lines.append("xfa_only:           samples/flat/xfa/ — important edge case, browsers can't render")
    lines.append("duplicate_of_corpus: skip (already in corpus from government download)")
    lines.append("error:              investigate manually before deciding")

    OUT_REPORT.write_text("\n".join(lines) + "\n")
    print(f"Wrote {OUT_REPORT}")

    print(f"\nClassification summary:")
    for cls, n in classification_counts.items():
        print(f"  {cls:24} {n:3d}")


if __name__ == "__main__":
    main()
