#!/usr/bin/env python3
"""
download_acroforms.py

Downloads candidate government AcroForm PDFs and verifies each one has actual
AcroForm metadata. Writes a manifest.json describing what was found.

This script is the ground truth for the corpus, NOT the URL list. A URL is
only included in the final corpus if the downloaded PDF actually has an
AcroForm dictionary with countable form fields.

Usage:
    cd ~/detection-lab
    source .venv/bin/activate
    python scripts/download_acroforms.py

Output:
    samples/acroforms/raw/<category>/<id>.pdf      Downloaded PDFs
    samples/acroforms/manifest.json                Per-PDF verified metadata
    samples/acroforms/download_log.txt             Human-readable log

Re-running is safe: existing files are SHA-verified; only changed/missing
files are re-downloaded.
"""

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

try:
    import pikepdf
except ImportError:
    print("ERROR: pikepdf not installed. Run: pip install pikepdf", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Candidate corpus (matches samples/acroforms/SOURCES.md)
# ---------------------------------------------------------------------------

CANDIDATES = [
    # IRS
    {"id": "irs_w9",      "category": "irs",      "agency": "IRS",        "form_name": "Form W-9 (Request for Taxpayer ID)",                   "url": "https://www.irs.gov/pub/irs-pdf/fw9.pdf"},
    {"id": "irs_w4",      "category": "irs",      "agency": "IRS",        "form_name": "Form W-4 (Employee Withholding Certificate)",          "url": "https://www.irs.gov/pub/irs-pdf/fw4.pdf"},
    {"id": "irs_1040",    "category": "irs",      "agency": "IRS",        "form_name": "Form 1040 (Individual Income Tax Return)",             "url": "https://www.irs.gov/pub/irs-pdf/f1040.pdf"},
    {"id": "irs_1040sb",  "category": "irs",      "agency": "IRS",        "form_name": "Form 1040 Schedule B (Interest and Dividends)",        "url": "https://www.irs.gov/pub/irs-pdf/f1040sb.pdf"},
    {"id": "irs_2848",    "category": "irs",      "agency": "IRS",        "form_name": "Form 2848 (Power of Attorney)",                        "url": "https://www.irs.gov/pub/irs-pdf/f2848.pdf"},
    {"id": "irs_8821",    "category": "irs",      "agency": "IRS",        "form_name": "Form 8821 (Tax Information Authorization)",            "url": "https://www.irs.gov/pub/irs-pdf/f8821.pdf"},
    {"id": "irs_4506t",   "category": "irs",      "agency": "IRS",        "form_name": "Form 4506-T (Request for Transcript)",                 "url": "https://www.irs.gov/pub/irs-pdf/f4506t.pdf"},

    # USCIS
    {"id": "uscis_i9",      "category": "uscis",  "agency": "USCIS",      "form_name": "I-9 (Employment Eligibility Verification)",            "url": "https://www.uscis.gov/sites/default/files/document/forms/i-9-paper-version.pdf"},
    {"id": "uscis_g1145",   "category": "uscis",  "agency": "USCIS",      "form_name": "G-1145 (E-Notification of Application Acceptance)",    "url": "https://www.uscis.gov/sites/default/files/document/forms/g-1145.pdf"},
    {"id": "uscis_i90",     "category": "uscis",  "agency": "USCIS",      "form_name": "I-90 (Application to Replace Permanent Resident Card)","url": "https://www.uscis.gov/sites/default/files/document/forms/i-90.pdf"},
    {"id": "uscis_n400",    "category": "uscis",  "agency": "USCIS",      "form_name": "N-400 (Application for Naturalization)",               "url": "https://www.uscis.gov/sites/default/files/document/forms/n-400.pdf"},

    # VA
    {"id": "va_21526ez",  "category": "va",       "agency": "VA",         "form_name": "VA 21-526EZ (Disability Compensation Claim)",          "url": "https://www.vba.va.gov/pubs/forms/VBA-21-526EZ-ARE.pdf"},
    {"id": "va_1010ez",   "category": "va",       "agency": "VA",         "form_name": "VA 10-10EZ (Application for Health Benefits)",         "url": "https://www.va.gov/vaforms/medical/pdf/10-10EZ-fillable.pdf"},

    # SSA
    {"id": "ssa_521",     "category": "misc",     "agency": "SSA",        "form_name": "SSA-521 (Request for Withdrawal of Application)",      "url": "https://www.ssa.gov/forms/ssa-521.pdf"},
    {"id": "ssa_1696",    "category": "misc",     "agency": "SSA",        "form_name": "SSA-1696 (Appointment of Representative)",             "url": "https://www.ssa.gov/forms/ssa-1696.pdf"},

    # Federal courts
    {"id": "uscourts_ao240", "category": "courts","agency": "US Courts",  "form_name": "AO-240 (Application to Proceed Without Prepaying Fees)","url": "https://www.uscourts.gov/sites/default/files/ao240.pdf"},
    {"id": "uscourts_b101",  "category": "courts","agency": "US Courts",  "form_name": "B 101 (Voluntary Bankruptcy Petition - Individuals)",  "url": "https://www.uscourts.gov/sites/default/files/form_b101_0.pdf"},

    # State
    {"id": "nj_mvc_ba49",    "category": "state", "agency": "NJ MVC",     "form_name": "BA-49 (Application for License Plates)",               "url": "https://www.state.nj.us/mvc/pdf/license/BA-49.pdf"},
    {"id": "ca_dmv_reg256",  "category": "state", "agency": "CA DMV",     "form_name": "REG 256 (Statement of Facts)",                         "url": "https://www.dmv.ca.gov/portal/file/statement-of-facts-reg-256-pdf/"},
    {"id": "ny_dtf_it201",   "category": "state", "agency": "NY DTF",     "form_name": "IT-201 (Resident Income Tax Return)",                  "url": "https://www.tax.ny.gov/pdf/current_forms/it/it201.pdf"},
]


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "samples" / "acroforms" / "raw"
MANIFEST_PATH = ROOT / "samples" / "acroforms" / "manifest.json"
LOG_PATH = ROOT / "samples" / "acroforms" / "download_log.txt"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

def download(url: str, dest: Path, log) -> tuple[bool, str]:
    """
    Download url to dest. Returns (success, message).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"})
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
        if len(data) < 1024:
            msg = f"response too small ({len(data)} bytes)"
            log(f"  FAIL {dest.name}: {msg}")
            return False, msg
        # Validate it looks like a PDF
        if not data.startswith(b"%PDF-"):
            msg = f"response is not a PDF (first bytes: {data[:8]!r})"
            log(f"  FAIL {dest.name}: {msg}")
            return False, msg
        dest.write_bytes(data)
        log(f"  OK   {dest.name}: {len(data):,} bytes")
        return True, f"{len(data)} bytes"
    except HTTPError as e:
        msg = f"HTTP {e.code} {e.reason}"
        log(f"  FAIL {dest.name}: {msg}")
        return False, msg
    except URLError as e:
        msg = f"URL error: {e.reason}"
        log(f"  FAIL {dest.name}: {msg}")
        return False, msg
    except Exception as e:
        msg = f"error: {type(e).__name__}: {e}"
        log(f"  FAIL {dest.name}: {msg}")
        return False, msg


# ---------------------------------------------------------------------------
# AcroForm verification
# ---------------------------------------------------------------------------

def inspect_pdf(path: Path) -> dict:
    """
    Open the PDF with pikepdf and report:
        - page_count
        - has_acroform (bool)
        - acroform_field_count (int)
        - is_xfa_only (bool)  XFA without normal AcroForm
        - error (str or None)
    """
    result = {
        "page_count": 0,
        "has_acroform": False,
        "acroform_field_count": 0,
        "is_xfa_only": False,
        "error": None,
    }
    try:
        with pikepdf.open(path) as pdf:
            result["page_count"] = len(pdf.pages)
            root = pdf.Root
            if "/AcroForm" in root:
                acroform = root["/AcroForm"]
                # Field count
                if "/Fields" in acroform:
                    fields = acroform["/Fields"]
                    # Count leaf fields recursively
                    def count_leaves(node):
                        count = 0
                        if "/Kids" in node:
                            for kid in node["/Kids"]:
                                count += count_leaves(kid)
                        else:
                            count += 1
                        return count
                    total = 0
                    for f in fields:
                        total += count_leaves(f)
                    result["acroform_field_count"] = total
                    result["has_acroform"] = total > 0
                # XFA check
                if "/XFA" in acroform and result["acroform_field_count"] == 0:
                    result["is_xfa_only"] = True
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    log_lines = []
    def log(msg):
        line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}  {msg}"
        print(line)
        log_lines.append(line)

    log(f"Detection Lab corpus downloader starting")
    log(f"Output dir: {RAW_DIR}")
    log(f"Total candidates: {len(CANDIDATES)}")
    log("")

    manifest = []
    stats = {"downloaded": 0, "skipped_existing": 0, "failed_download": 0, "not_acroform": 0, "verified_acroform": 0}

    for i, c in enumerate(CANDIDATES, start=1):
        log(f"[{i}/{len(CANDIDATES)}] {c['id']} ({c['agency']})")
        category_dir = RAW_DIR / c["category"]
        dest = category_dir / f"{c['id']}.pdf"

        entry = {
            "id": c["id"],
            "filename": str(dest.relative_to(ROOT)),
            "source_url": c["url"],
            "agency": c["agency"],
            "form_name": c["form_name"],
            "category": c["category"],
            "downloaded_at": None,
            "file_sha256": None,
            "file_size_bytes": None,
            "page_count": None,
            "acroform_field_count": None,
            "has_acroform": False,
            "is_xfa_only": False,
            "download_status": "pending",
            "download_error": None,
            "license_notes": "U.S. government work, public domain" if c["category"] in ("irs", "uscis", "va", "courts", "misc") else "State government work — research/benchmark use only",
        }

        # Download (or reuse existing)
        if dest.exists() and dest.stat().st_size > 1024:
            log(f"  using existing file: {dest}")
            entry["download_status"] = "existing"
            stats["skipped_existing"] += 1
        else:
            ok, msg = download(c["url"], dest, log)
            if not ok:
                entry["download_status"] = "failed"
                entry["download_error"] = msg
                stats["failed_download"] += 1
                manifest.append(entry)
                time.sleep(0.5)
                continue
            entry["download_status"] = "downloaded"
            entry["downloaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            stats["downloaded"] += 1

        # Hash + size
        entry["file_sha256"] = sha256_of(dest)
        entry["file_size_bytes"] = dest.stat().st_size

        # Inspect
        info = inspect_pdf(dest)
        entry["page_count"] = info["page_count"]
        entry["acroform_field_count"] = info["acroform_field_count"]
        entry["has_acroform"] = info["has_acroform"]
        entry["is_xfa_only"] = info["is_xfa_only"]
        if info["error"]:
            entry["download_error"] = f"inspect: {info['error']}"

        # Classification
        if info["has_acroform"]:
            log(f"  AcroForm OK: {info['page_count']} pages, {info['acroform_field_count']} fields")
            stats["verified_acroform"] += 1
        elif info["is_xfa_only"]:
            log(f"  XFA-only (not classical AcroForm): {info['page_count']} pages")
            stats["not_acroform"] += 1
        else:
            log(f"  NOT an AcroForm: {info['page_count']} pages, no form fields")
            stats["not_acroform"] += 1

        manifest.append(entry)
        time.sleep(0.5)  # be polite to government servers

    # Summary
    log("")
    log("=" * 60)
    log("SUMMARY")
    log("=" * 60)
    log(f"  Total candidates:       {len(CANDIDATES)}")
    log(f"  Newly downloaded:       {stats['downloaded']}")
    log(f"  Used existing:          {stats['skipped_existing']}")
    log(f"  Failed download:        {stats['failed_download']}")
    log(f"  Verified AcroForm:      {stats['verified_acroform']}")
    log(f"  Not an AcroForm:        {stats['not_acroform']}")
    log("")

    # Write manifest
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    log(f"Wrote manifest: {MANIFEST_PATH}")

    # Write log
    LOG_PATH.write_text("\n".join(log_lines) + "\n")
    log(f"Wrote log: {LOG_PATH}")

    # Failures summary
    failed = [e for e in manifest if e["download_status"] == "failed"]
    if failed:
        print("\nFailed downloads — review and update SOURCES.md:")
        for e in failed:
            print(f"  {e['id']}: {e['download_error']}  ({e['source_url']})")

    non_acro = [e for e in manifest if e["download_status"] in ("downloaded", "existing") and not e["has_acroform"]]
    if non_acro:
        print("\nDownloaded but not AcroForm — may need replacement:")
        for e in non_acro:
            tag = "XFA-only" if e["is_xfa_only"] else "no form fields"
            print(f"  {e['id']}: {tag}  ({e['source_url']})")


if __name__ == "__main__":
    main()
