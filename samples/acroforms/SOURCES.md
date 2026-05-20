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

URLs in this list are best-effort. The `scripts/download_acroforms.py` script will:
1. Attempt download
2. Verify the PDF actually has AcroForm metadata via pikepdf
3. Count pages and fields
4. Update the manifest with verified data

URLs that fail download or have no AcroForm metadata are flagged in the manifest and noted here.

---

## Candidate Forms

### IRS (Tax Forms)

URL pattern: `https://www.irs.gov/pub/irs-pdf/f{form}.pdf` (current version, always latest revision)

| ID | Form | URL | Expected Complexity | Notes |
|----|------|-----|---------------------|-------|
| irs_w9 | W-9 (Request for Taxpayer ID) | https://www.irs.gov/pub/irs-pdf/fw9.pdf | Short (1 page, ~10 fields, checkboxes + text) | Most common tax form, classic AcroForm |
| irs_w4 | W-4 (Employee Withholding Certificate) | https://www.irs.gov/pub/irs-pdf/fw4.pdf | Short (4 pages, mostly text + checkboxes) | Has multi-jobs worksheet |
| irs_1040 | Form 1040 (Individual Income Tax Return) | https://www.irs.gov/pub/irs-pdf/f1040.pdf | Long (multi-page, many text fields, signatures, complex layout) | Flagship complex form |
| irs_1040sb | Schedule B (Interest and Dividends) | https://www.irs.gov/pub/irs-pdf/f1040sb.pdf | Medium (tabular layout, mostly text) | Good tabular test case |
| irs_2848 | Form 2848 (Power of Attorney) | https://www.irs.gov/pub/irs-pdf/f2848.pdf | Medium (text-heavy, signatures, checkboxes) | Authority/legal context |
| irs_8821 | Form 8821 (Tax Information Authorization) | https://www.irs.gov/pub/irs-pdf/f8821.pdf | Medium (similar to 2848, simpler) | Good comparison to 2848 |
| irs_4506t | Form 4506-T (Request for Transcript) | https://www.irs.gov/pub/irs-pdf/f4506t.pdf | Short (1 page, mixed fields) | Common transcript request |

### USCIS (Immigration Forms)

URL pattern: `https://www.uscis.gov/sites/default/files/document/forms/{form}.pdf` (some forms use specific filenames)

| ID | Form | URL | Expected Complexity | Notes |
|----|------|-----|---------------------|-------|
| uscis_i9 | I-9 (Employment Eligibility Verification) | https://www.uscis.gov/sites/default/files/document/forms/i-9-paper-version.pdf | Medium (2-4 pages, mixed text + checkboxes + signatures) | Most common immigration form |
| uscis_g1145 | G-1145 (E-Notification of Application/Petition Acceptance) | https://www.uscis.gov/sites/default/files/document/forms/g-1145.pdf | Short (1 page) | Simple opt-in form |
| uscis_i90 | I-90 (Application to Replace Permanent Resident Card) | https://www.uscis.gov/sites/default/files/document/forms/i-90.pdf | Long (many pages, complex) | Heavy form, lots of field variety |
| uscis_n400 | N-400 (Application for Naturalization) | https://www.uscis.gov/sites/default/files/document/forms/n-400.pdf | Very long (~20 pages, hundreds of fields) | Most complex USCIS form |

### VA (Veterans Affairs)

URL pattern: `https://www.vba.va.gov/pubs/forms/VBA-{number}-ARE.pdf` (older) or `https://www.va.gov/find-forms/about-form-{number}/` (newer)

| ID | Form | URL | Expected Complexity | Notes |
|----|------|-----|---------------------|-------|
| va_21526ez | VA Form 21-526EZ (Disability Compensation Claim) | https://www.vba.va.gov/pubs/forms/VBA-21-526EZ-ARE.pdf | Long (12+ pages, complex) | Major benefits claim form |
| va_1010ez | VA Form 10-10EZ (Application for Health Benefits) | https://www.va.gov/vaforms/medical/pdf/10-10EZ-fillable.pdf | Long (8+ pages, mixed fields) | Health enrollment |

### SSA (Social Security)

URL pattern: `https://www.ssa.gov/forms/ssa-{number}.pdf`

| ID | Form | URL | Expected Complexity | Notes |
|----|------|-----|---------------------|-------|
| ssa_521 | SSA-521 (Request for Withdrawal of Application) | https://www.ssa.gov/forms/ssa-521.pdf | Short (1-2 pages) | Common SS request |
| ssa_1696 | SSA-1696 (Appointment of Representative) | https://www.ssa.gov/forms/ssa-1696.pdf | Short (2-3 pages, signatures) | Legal representation form |

### Federal Courts / Federal Misc

| ID | Form | URL | Expected Complexity | Notes |
|----|------|-----|---------------------|-------|
| uscourts_ao240 | AO-240 (Application to Proceed Without Prepaying Fees) | https://www.uscourts.gov/sites/default/files/ao240.pdf | Medium (financial disclosure, tabular) | Federal courts standard form |
| uscourts_b101 | B 101 (Voluntary Petition for Individuals - Bankruptcy) | https://www.uscourts.gov/sites/default/files/form_b101_0.pdf | Long (8+ pages) | Bankruptcy filing |

### State (Variety from a few states)

Note: State PDF URL patterns are highly variable and less stable than federal. These are best-effort candidates.

| ID | Form | URL | Expected Complexity | Notes |
|----|------|-----|---------------------|-------|
| nj_mvc_ba49 | NJ MVC BA-49 (Application for License Plates) | https://www.state.nj.us/mvc/pdf/license/BA-49.pdf | Short-medium | NJ state DMV |
| ca_dmv_reg256 | CA DMV REG 256 (Statement of Facts) | https://www.dmv.ca.gov/portal/file/statement-of-facts-reg-256-pdf/ | Medium | CA DMV, complex layout |
| ny_dtf_it201 | NY DTF IT-201 (Resident Income Tax Return) | https://www.tax.ny.gov/pdf/current_forms/it/it201.pdf | Long | NY state tax return |

---

## Total candidates: 22

If all 22 verify as actual AcroForms, that's well within the 15-20 target with room to drop ones that fail. If several fail, we expand from the same agencies.

## Process

1. Commit this SOURCES.md
2. Run `scripts/download_acroforms.py`
3. Review manifest.json for failures and AcroForm-vs-flat-PDF results
4. Update this SOURCES.md with verified status per form
5. For failures, find replacement URLs and re-run

## License notes

All forms listed are U.S. government works (federal) or state-government works produced for public use. U.S. federal government works are in the public domain (17 U.S.C. § 105). State government forms are generally publicly distributable but specific licensing varies; we use them only for benchmark/research purposes, not redistribution.
