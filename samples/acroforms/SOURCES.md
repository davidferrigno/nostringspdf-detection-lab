# AcroForm Corpus Sources

Curated list of government AcroForm PDFs for the Detection Lab benchmark corpus.

## Curation criteria

Each candidate must be:
- An actual AcroForm (has embedded form fields — verified at download time, not just a flat scanned government PDF)
- Publicly downloadable from a government source
- Free to redistribute as a U.S. government work (public domain)
- Reasonably stable URL (avoid query-string URLs that expire)

The corpus must cover variety on:
- **Complexity:** short (1-2 pages, <30 fields), medium (3-5 pages, 30-100 fields), long (6+ pages, 100+ fields)
- **Field types:** text, checkbox, radio, signature, date
- **Layout:** single-column, tabular, multi-column, complex
- **Agency:** IRS, USCIS, VA, SSA, state DMV, federal courts, federal misc

## Verification

URLs in this list are verified by `scripts/download_acroforms.py`, which:
1. Downloads each URL
2. Validates PDF magic bytes
3. Opens with pikepdf
4. Counts leaf-level AcroForm fields recursively
5. Flags XFA-only PDFs (which appear fillable in Acrobat but won't render correctly in pdf-lib / browser PDF engines)
6. Writes manifest.json with verified data

URLs that fail download or have no AcroForm metadata are flagged in the manifest and noted in this file.

---

## Candidate Forms

### IRS (Tax Forms)

URL pattern: `https://www.irs.gov/pub/irs-pdf/f{form}.pdf` (current version, always latest revision)

| ID | Form | URL | Expected Complexity | Verified |
|----|------|-----|---------------------|----------|
| irs_w9 | W-9 (Request for Taxpayer ID) | https://www.irs.gov/pub/irs-pdf/fw9.pdf | Short (6 pages, ~23 fields) | ✓ AcroForm |
| irs_w4 | W-4 (Employee Withholding Certificate) | https://www.irs.gov/pub/irs-pdf/fw4.pdf | Short (5 pages, ~48 fields) | ✓ AcroForm |
| irs_1040 | Form 1040 (Individual Income Tax Return) | https://www.irs.gov/pub/irs-pdf/f1040.pdf | Long (2 pages, ~199 fields) | ✓ AcroForm |
| irs_1040sb | Schedule B (Interest and Dividends) | https://www.irs.gov/pub/irs-pdf/f1040sb.pdf | Medium (1 page, ~72 fields, tabular) | ✓ AcroForm |
| irs_2848 | Form 2848 (Power of Attorney) | https://www.irs.gov/pub/irs-pdf/f2848.pdf | Medium (2 pages, ~92 fields) | ✓ AcroForm |
| irs_8821 | Form 8821 (Tax Information Authorization) | https://www.irs.gov/pub/irs-pdf/f8821.pdf | Short-medium (1 page, ~45 fields) | ✓ AcroForm |
| irs_4506t | Form 4506-T (Request for Transcript) | https://www.irs.gov/pub/irs-pdf/f4506t.pdf | Short (2 pages, ~29 fields) | ✓ AcroForm |

### USCIS (Immigration Forms)

URL pattern: `https://www.uscis.gov/sites/default/files/document/forms/{form}.pdf` (specific filenames vary)

| ID | Form | URL | Expected Complexity | Verified |
|----|------|-----|---------------------|----------|
| uscis_i9 | I-9 (Employment Eligibility Verification) | https://www.uscis.gov/sites/default/files/document/forms/i-9-paper-version.pdf | Medium (4 pages, ~130 fields) | ✓ AcroForm |
| uscis_g1145 | G-1145 (E-Notification of Application Acceptance) | https://www.uscis.gov/sites/default/files/document/forms/g-1145.pdf | Short (1 page, ~6 fields) | ✓ AcroForm |
| uscis_i90 | I-90 (Application to Replace Permanent Resident Card) | https://www.uscis.gov/sites/default/files/document/forms/i-90.pdf | Long (7 pages, ~195 fields) | ✓ AcroForm |
| uscis_n400 | N-400 (Application for Naturalization) | https://www.uscis.gov/sites/default/files/document/forms/n-400.pdf | Very long (14 pages, ~440 fields) | ✓ AcroForm |

### VA (Veterans Affairs)

| ID | Form | URL | Expected Complexity | Verified |
|----|------|-----|---------------------|----------|
| va_21526ez | VA 21-526EZ (Disability Compensation Claim) | https://www.vba.va.gov/pubs/forms/VBA-21-526EZ-ARE.pdf | Long (15 pages, ~388 fields) | ✓ AcroForm |
| va_1010ez | VA 10-10EZ (Application for Health Benefits) | https://www.va.gov/vaforms/medical/pdf/VA%20Form%2010-10EZ.pdf | Long (8+ pages, mixed fields) | pending |

### SSA (Social Security)

URL pattern: `https://www.ssa.gov/forms/ssa-{number}.pdf`

| ID | Form | URL | Expected Complexity | Verified |
|----|------|-----|---------------------|----------|
| ssa_521 | SSA-521 (Request for Withdrawal of Application) | https://www.ssa.gov/forms/ssa-521.pdf | Short (2 pages, ~38 fields) | ✓ AcroForm |
| ssa_1696 | SSA-1696 (Appointment of Representative) | https://www.ssa.gov/forms/ssa-1696.pdf | Medium (6 pages, ~91 fields) | ✓ AcroForm |

### Federal Courts / Federal Misc

| ID | Form | URL | Expected Complexity | Verified |
|----|------|-----|---------------------|----------|
| uscourts_ao240 | AO-240 (Application to Proceed Without Prepaying Fees) | https://www.uscourts.gov/sites/default/files/ao240.pdf | Medium (2 pages, ~34 fields) | ✓ AcroForm |
| uscourts_b101 | B 101 (Voluntary Bankruptcy Petition - Individuals) | https://www.uscourts.gov/sites/default/files/form_b_101_0624_fillable_clean.pdf | Long (multi-page) | pending |

### State (Variety from a few states)

Note: State PDF URLs are highly variable and less stable than federal. URLs may need periodic re-curation.

| ID | Form | URL | Expected Complexity | Verified |
|----|------|-----|---------------------|----------|
| nj_mvc_ba49 | NJ MVC BA-49 (Application for License Plates) | https://www.nj.gov/mvc/pdf/vehicles/BA-49.pdf | Short-medium | pending |
| ca_dmv_reg256 | CA DMV REG 256 (Statement of Facts) | https://www.dmv.ca.gov/portal/file/statement-of-facts-reg-256-pdf/ | Medium (2 pages, ~72 fields) | ✓ AcroForm |
| ny_dtf_it201 | NY DTF IT-201 (Resident Income Tax Return) | https://www.tax.ny.gov/pdf/current_forms/it/it201_fill_in.pdf | Long | pending |

---

## Total candidates: 20

After v1 run (May 20, 2026):
- 16/20 verified AcroForm ✓
- 4/20 failed with 404 (URLs since corrected, awaiting re-run)

Range of complexity (verified): G-1145 (6 fields) → N-400 (440 fields)

## Process

1. Commit this SOURCES.md
2. Run `scripts/download_acroforms.py`
3. Review manifest.json for failures and AcroForm-vs-flat-PDF results
4. Update this SOURCES.md with verified status per form
5. For failures, find replacement URLs and re-run

## License notes

All federal forms listed are U.S. government works in the public domain (17 U.S.C. § 105). State government forms are generally publicly distributable but specific licensing varies; we use them only for benchmark/research purposes, not redistribution.

## Future: local PDF corpus

Users (i.e. Dave's existing test PDFs at `E:\No Strings PDF\Fillable PDFs` and `E:\No Strings PDF\PDF Sample Forms`) represent the "real-world distribution" of documents NoStringsPDF will encounter. A separate `local_inventory.py` script will catalog these, and selected PDFs will be brought into `samples/` with the same manifest schema. See docs/STATUS.md for current state of that workstream.
