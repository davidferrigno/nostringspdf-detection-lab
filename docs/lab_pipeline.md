# Lab Pipeline

The continuous lab pipeline wraps the privacy-aware queue and writes a
timestamped benchmark package on each run. It is for controlled benchmarking
and experiment routing only. It does not deploy detector changes.

## Run

```powershell
py -3.13 scripts/run_lab_pipeline.py --manifest corpus/manifest.json --out runs
```

The scheduler wrappers call the same command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_lab_pipeline.ps1
```

```bash
./scripts/run_lab_pipeline.sh
```

## Outputs

Each run writes:

```text
runs/YYYYMMDD-HHMMSS/
  scorecard.md
  summary.csv
  results/<pdf_id>.json
  compare.md
  compare.json
  pipeline_summary.json
```

`runs/latest/` is refreshed as a directory copy of the newest timestamped run.
Generated `runs/` output is ignored by git.

## Scorecards

`scorecard.md` summarizes:

- total documents
- counts by lane
- missing documents
- sensitive/local-only skipped documents
- detector field counts
- known failures
- scanned/image-only candidates
- recommended next experiments

`summary.csv` is a compact machine-readable table for the same queue status.
Per-document JSON files are the best place to inspect lane signals and detector
counts.

## Comparison

`compare.md` and `compare.json` compare the current run to the previous
`runs/latest/` when one exists. They report:

- total document changes
- lane count changes
- detector field count changes
- missing document changes
- sensitive/local-only skip changes
- known failure changes
- scanned/image-only candidates
- AcroForm baseline status
- regressions and improvements

The first run without a previous latest reports that no comparison baseline was
available.

## Scanned/OCR Routing

The queue marks a document as an OCR/line-box candidate when it has no text, no
widgets, and image-heavy pages, or when the manifest includes `scanned_image`.
Those documents are routed to `docs/ocr_linebox_plan.md` and
`experiments/ocr_linebox/`.

Full OCR is intentionally out of scope for this pipeline slice.

## Privacy Rule

The committed corpus may contain only blank PDFs, public blank forms, or
synthetic-value test PDFs. Real filled forms or uncertain files must be marked
`sensitive_do_not_store`, referenced only as local paths if needed, skipped by
default when unavailable, and never copied into `samples/` or committed.

## Promotion Gate

A detector experiment is eligible for production review only if:

- AcroForm lane does not regress.
- Known failure improves.
- False positives do not materially increase.
- Alignment score improves or remains stable.
- Scanned/flat improvements are supported by screenshots/overlays.
- No sensitive data is stored.

Production review is not production promotion. Merge/deploy decisions remain
outside this lab pipeline.
