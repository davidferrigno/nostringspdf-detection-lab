# Detection Measurement Guide

Slice 12D adds repeatable measurement infrastructure for detection quality. It is intentionally separate from production detection code.

## Goals

- Measure before changing detection.
- Score geometry with IoU, not field count alone.
- Keep draft bootstrap labels visibly separate from human-reviewed ground truth.
- Produce JSON baselines that future slices can compare against.

## Ground Truth Files

Ground truth files live in:

```text
docs/detection-ground-truth/
```

Each PDF has one JSON file named after the original PDF filename plus `.json`, for example:

```text
docs/detection-ground-truth/sp-650 non fill.pdf.json
```

Schema:

```json
{
  "pdf": "filename.pdf",
  "page_count": 2,
  "labeled_at": "2026-05-06",
  "review_status": "draft",
  "fields": [
    {
      "id": "f1",
      "page": 1,
      "type": "text",
      "bbox": [x, y, width, height],
      "label": "optional",
      "group_id": "optional"
    }
  ]
}
```

`review_status` must be one of:

- `draft`: bootstrapped labels; useful for regression detection, not authoritative truth.
- `human_reviewed`: manually reviewed labels; suitable for final quality claims.

## Bootstrap Draft Labels

Bootstrap labels from heuristic output:

```powershell
py -3.13 -B scripts\bootstrap_ground_truth.py test_pdfs\Marriage--Civil-Union-License-Application-Form-PDF.pdf "test_pdfs\sp-650 non fill.pdf"
```

The script refuses to overwrite existing files unless `--force` is passed:

```powershell
py -3.13 -B scripts\bootstrap_ground_truth.py --force "test_pdfs\sp-650 non fill.pdf"
```

Bootstrap output is always marked:

```json
"review_status": "draft"
```

## Run Measurement

Measure heuristic output against available ground truth:

```powershell
py -3.13 -B scripts\measure_detection.py --detectors heuristic --vs-ground-truth --json-output measurements\baseline-2026-05-06.json --markdown-output measurements\baseline-2026-05-06.md "test_pdfs\sp-650 non fill.pdf"
```

Supported detectors:

- `heuristic`
- `azure`
- `acroform`

Multiple detectors can be comma-separated:

```powershell
py -3.13 -B scripts\measure_detection.py --detectors heuristic,azure --vs-ground-truth "test_pdfs\sp-650 non fill.pdf"
```

Use Azure sparingly because it costs money. One run per PDF is enough for measurement slices.

## Scoring

`scripts/measurement/scoring.py` implements:

- `iou(box_a, box_b)`
- `match_fields(detected, ground_truth, iou_threshold=0.5)`

Matching is greedy by highest IoU and page-aware. Metrics:

- True positives: detected fields matched to ground truth above threshold.
- False positives: detected fields with no match.
- False negatives: ground-truth fields with no match.
- Type mismatches: matched geometry where field types differ.
- Recall: `TP / ground_truth_count`.
- Precision: `TP / detected_count`.

## Compare Runs

Compare a future run against a baseline:

```powershell
py -3.13 -B scripts\measure_detection.py --compare measurements\baseline-2026-05-06.json measurements\current.json
```

Comparison output includes:

- detected count delta
- recall delta
- precision delta
- fields gained
- fields lost

Baseline-to-baseline comparison should produce zero deltas.

## I-9

I-9 is AcroForm-based and should not be used for heuristic-vs-Azure comparison. Verify it separately:

```powershell
py -3.13 -B scripts\measure_detection.py --detectors acroform test_pdfs\i-9.pdf
```

Expected result is approximately 130 widgets via the AcroForm path.

## Initial Corpus

The initial Slice 12D corpus is:

- `Marriage--Civil-Union-License-Application-Form-PDF.pdf`
- `sp-650 non fill.pdf`
- `POST_5330469_2026 EL NOMINATION FORM (1).pdf`
- `center_travel_field_trip_authorization_form.pdf`

Do not expand the corpus inside detection-quality slices unless the slice explicitly calls for it.

## Interpreting Draft Results

Draft labels are useful as regression tripwires because a future detector change should explain any large geometry/count delta from the baseline. They are not proof of real-world precision or recall until human review updates `review_status` to `human_reviewed`.
