# Detection Lab Workflow

## Architecture

The detection lab uses two scoring lanes because AcroForm widgets and flat PDFs answer different questions.

Lane A is AcroForm widget scoring. Ground truth comes from widget annotations extracted into `benchmarks/ground_truth/<pdf_id>.json`. This lane tests whether a backend reproduces the form author's widget segmentation. It is the right sanity check for `acroform_self` and the historical AcroForm heuristic baseline.

Lane B is flat-PDF usable-fill-zone scoring. Ground truth lives in `benchmarks/ground_truth_flat/<pdf_id>.json` after human review. This lane tests whether a backend finds user-meaningful fill zones on PDFs with no widgets.

See `docs/char_box_finding.md` for the architectural finding behind this split: AcroForm char-box widget bboxes encode author/editor choices, not visible geometry. A heuristic may correctly detect one visible SSN row while the AcroForm author split the same row into multiple widgets. That should be a Lane A mismatch, not a detector failure.

`docs/FIELD_SCHEMA.md` is the integration contract. Every backend emits schema version `1.0` fields with `id`, `page`, `type`, `bbox`, and optional `label` using top-left-origin point coordinates.

## Adding A Backend

1. Add the backend module under `scripts/backends/<backend_name>.py`.
2. Expose a `detect(pdf_path: Path) -> list[dict]` function that returns `FIELD_SCHEMA.md` fields.
3. Register it in `scripts/backend_registry.py` under `BACKEND_METADATA`.
4. Set `lanes` to the scoring lanes where the backend is valid.
5. Set `description` and `schema_version: "1.0"`.

`BACKENDS` is still populated for older scripts, but `BACKEND_METADATA` is the source of truth for lane-aware automation.

## Adding An AcroForm PDF

1. Add or import the PDF under `samples/acroforms/raw/...`.
2. Add a manifest entry in `samples/acroforms/manifest.json` with `lane: "acroform"` and `expected_lane: "A"`.
3. Run `python scripts/extract_ground_truth.py --pdf <pdf_id>` to create `benchmarks/ground_truth/<pdf_id>.json`.
4. Run `python scripts/verify_corpus.py`.
5. Run a Lane A benchmark such as `python scripts/run_benchmark.py --backend acroform_self --lane A --pdf <pdf_id>`.

## Adding A Flat PDF

1. Add the PDF under `samples/flat/...`.
2. Add or refresh `samples/flat/manifest.json` with `lane: "flat"` and `expected_lane: "B"`.
3. Run `python scripts/extract_flat_pdf_ground_truth.py --pdf <pdf_id>`.
4. Confirm the draft `benchmarks/ground_truth_flat/<pdf_id>.draft.json` has `needs_review: true`.
5. Hand-review the draft against rendered overlays, adjust fields, and mark kept or adjusted fields.
6. Promote only after review with `python scripts/extract_flat_pdf_ground_truth.py --pdf <pdf_id> --promote`.

Draft files are not scored. Lane B benchmarks use only final `benchmarks/ground_truth_flat/<pdf_id>.json` files.

## Running Benchmarks

Run a single AcroForm benchmark:

```bash
python scripts/run_benchmark.py --backend heuristic_lab_v1 --lane A
```

Run one PDF:

```bash
python scripts/run_benchmark.py --backend acroform_self --lane A --pdf irs_w9
```

Run a flat-PDF backend after reviewed Lane B ground truth exists:

```bash
python scripts/run_benchmark.py --backend heuristic_lab_v2 --lane B
```

The benchmark refuses lane mismatches by default. Use `--force-lane-mismatch` only for diagnostics.

Run the whole lab:

```bash
python scripts/run_detection_lab.py --all
```

Plan without writing reports:

```bash
python scripts/run_detection_lab.py --dry-run
```

Run one lane:

```bash
python scripts/run_detection_lab.py --lane A
python scripts/run_detection_lab.py --lane B
```

## Regression Detection

`scripts/compare_to_baseline.py` compares benchmark scorecards and reports aggregate and per-PDF precision/recall deltas. The orchestrator runs it when a Lane A `acroform_self` baseline and a non-self Lane A candidate exist, then writes `reports/latest/regressions.md`.

A regression report is diagnostic context. For heuristic backends compared against `acroform_self`, lower scores are expected because `acroform_self` re-extracts the same widget layer used as ground truth.

## Reports

Single benchmark reports go to:

```text
reports/benchmarks/<timestamp>_<backend>_lane<lane>/
```

Each benchmark directory contains:

```text
scorecard.json
scorecard.csv
scorecard.md
per_pdf/<pdf_id>.json
```

Full lab summaries go to:

```text
reports/latest/summary.md
reports/latest/lane_a_scorecard.md
reports/latest/lane_b_scorecard.md
reports/latest/regressions.md
```

Generated integrity reports, benchmark runs, comparisons, and overlays are regenerable. The reviewed ground truth files are the durable scoring inputs.
