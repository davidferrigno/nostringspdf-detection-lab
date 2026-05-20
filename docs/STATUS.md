# Detection Lab Status

## v0 Bootstrap — COMPLETE (May 20, 2026)

### Infrastructure
- Vultr VPS, Ubuntu 24.04, 4 vCPU, 8 GB RAM, 180 GB NVMe
- New Jersey location
- User: lab (sudo, SSH key auth)

### Software
- Python 3.12.3 in `.venv`
- 50+ packages installed and verified (see requirements.txt)
- Heaviest: paddle 3.3.1, paddleocr 3.5.0
- All imports tested and passing

### Repo
- Private GitHub repo
- Folder structure per detection-lab-kickoff.md

## Next: Task 1 — Curated AcroForm Corpus

### Approach
Curate, don't rush. Start with 15-20 high-quality AcroForms.

### Folder Structure
### Manifest Schema (per PDF)
```json
{
  "filename": "i-9.pdf",
  "source_url": "https://www.uscis.gov/sites/default/files/document/forms/i-9.pdf",
  "agency": "USCIS",
  "form_name": "Form I-9 Employment Eligibility Verification",
  "category": "uscis",
  "downloaded_at": "2026-05-21T00:00:00Z",
  "file_sha256": "...",
  "page_count": 4,
  "acroform_field_count": 130,
  "license_notes": "U.S. government work, public domain"
}
```

### Quality Criteria
- Must be actual AcroForm (has embedded form fields)
- Publicly downloadable from government source
- Variety of complexity: short (W-9), medium (I-9), long (Form 1040)
- Variety of field types: text, checkbox, radio, signature
- Variety of layouts: single column, tabular, complex

## Roadmap

- v0: Benchmark infrastructure measuring current detection (in progress)
- v1: Telemetry-informed improvements (post-launch)
- v2: Scanned document normalization
- v3: ML-assisted ranking
- v4: API tier

See ../detection-lab-kickoff.md in main NoStringsPDF repo for full strategy.
 
## Workflow verified May 20 PM 
Clone-to-Windows workflow active. Source of truth = GitHub. 
