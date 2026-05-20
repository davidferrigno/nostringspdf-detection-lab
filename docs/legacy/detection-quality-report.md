# Detection Quality Report

Measurement date: 2026-05-05

Scope: Slice 12C-A measurement only. No production detection flow was changed.

## Method

The one-off script `scripts/measure_detection.py` was used to run detector functions directly:

- Heuristic: `services.heuristic_service.run_heuristic_detection`
- Azure: `services.azure_client.azure_detect` plus `services.azure_normalizer.normalize_azure`
- AcroForm verification: `services.acroform_service.extract_acroform_result`

The script bypasses `detect_pipeline`, routes, usage caps, templates, and frontend code.

## Raw Measurement Output

```jsonl
{"detector": "heuristic", "method": "content_stream", "page_count": 2, "pdf": "Marriage--Civil-Union-License-Application-Form-PDF.pdf", "per_page": {"1": 107, "2": 46}, "total": 153, "types": {"radio": 36, "text": 117}}
{"detector": "heuristic", "method": "content_stream", "page_count": 2, "pdf": "sp-650 non fill.pdf", "per_page": {"1": 33, "2": 1}, "total": 34, "types": {"radio": 12, "text": 22}}
{"detector": "heuristic", "method": "content_stream", "page_count": 1, "pdf": "POST_5330469_2026 EL NOMINATION FORM (1).pdf", "per_page": {"1": 21}, "total": 21, "types": {"checkbox": 3, "text": 18}}
{"detector": "heuristic", "method": "content_stream", "page_count": 1, "pdf": "center_travel_field_trip_authorization_form.pdf", "per_page": {"1": 19}, "total": 19, "types": {"text": 19}}
{"detector": "azure", "estimated_cost_usd": 0.02, "page_count": 2, "pdf": "Marriage--Civil-Union-License-Application-Form-PDF.pdf", "per_page": {"1": 34, "2": 5}, "total": 39, "types": {"checkbox": 38, "text": 1}, "warnings": []}
{"detector": "azure", "estimated_cost_usd": 0.02, "page_count": 2, "pdf": "sp-650 non fill.pdf", "per_page": {"1": 12}, "total": 12, "types": {"checkbox": 12}, "warnings": []}
{"detector": "azure", "estimated_cost_usd": 0.01, "page_count": 1, "pdf": "POST_5330469_2026 EL NOMINATION FORM (1).pdf", "per_page": {"1": 3}, "total": 3, "types": {"checkbox": 3}, "warnings": []}
{"detector": "azure", "estimated_cost_usd": 0.01, "page_count": 1, "pdf": "center_travel_field_trip_authorization_form.pdf", "per_page": {"1": 1}, "total": 1, "types": {"text": 1}, "warnings": []}
{"detector": "acroform", "page_count": 4, "pdf": "i-9.pdf", "per_page": {"1": 52, "3": 39, "4": 39}, "total": 130, "types": {"checkbox": 8, "text": 122}}
```

## Summary Table

| PDF | Detector | Detected | Expected | Recall estimate | Precision estimate | Notes |
| --- | --- | ---: | ---: | --- | --- | --- |
| NJ Marriage License | Heuristic | 153 | 145 | ~95-99% | ~90-95% | Best raw coverage. Slight over-detection and wrong type issue: 36 expected checkboxes appear as radio-like controls, but total is close. |
| NJ Marriage License | Azure | 39 | 145 | ~27% | High for checkboxes, unusable overall | Captures nearly all 38 checkboxes but misses ~106 of 107 text fields. |
| SP-650 | Heuristic | 34 | 34 | ~100% | ~100% | Best path. Correctly finds 22 text fields and 12 radios across the expected form. |
| SP-650 | Azure | 12 | 34 | ~35% overall | High for selection marks, poor type fidelity | Finds 12 selection marks but returns them as checkboxes, not radios; misses all text fields. |
| Eden Lane Nomination | Heuristic | 21 | 21 | ~100% | ~100% | Best path by count. Existing known geometry issue remains separate from detection count quality. |
| Eden Lane Nomination | Azure | 3 | 21 | ~14% | High for checkboxes, unusable overall | Finds only the 3 checkboxes and misses all text/signature/date fields. |
| Field Trip Form | Heuristic | 19 | 19 | ~100% | ~100% | Best path by count. |
| Field Trip Form | Azure | 1 | 19 | ~5% | Likely high but unusable | Finds one text field; misses nearly everything. |
| I-9 | AcroForm | 130 | 130 | ~100% | ~100% | AcroForm short-circuit remains the correct path. Not part of heuristic-vs-Azure comparison. |

## Failure Modes

### Over-detection

- Heuristic slightly over-detects on the NJ marriage license: 153 detected vs 145 expected.
- Based on the ground-truth note, this is close enough that the issue is not a field explosion in the current measurement. It is a precision/type/geometry refinement problem.

### Under-detection

- Azure severely under-detects text fields on all flat PDFs measured.
- Azure appears useful for selection marks but unreliable as the primary flat-form detector for text-entry fields.

### Wrong field type

- Heuristic classifies the NJ marriage license selection marks as `radio` in the raw output, while ground truth lists these as checkboxes.
- Azure returns SP-650 radios as `checkbox`, so Azure also lacks usable radio type fidelity on this fixture.

### Geometry / alignment issues

- This measurement script counts fields and types; it does not score geometry IoU.
- Existing known geometry issues remain separate: Eden alignment, first-summary-line sizing, and professional text placement.

### Grid / table confusion

- The NJ marriage license is table-cell dense, but the measured heuristic result is 153 vs expected 145. That suggests the current heuristic is much closer to correct than a blanket grid-suppression strategy.
- Important lesson: for this form, many true fields are inside grid/table cells. Generic grid filters are dangerous because they remove real fields.

## Detector Recommendation Per PDF

| PDF | Recommendation |
| --- | --- |
| NJ Marriage License | Heuristic better |
| SP-650 | Heuristic better |
| Eden Lane Nomination | Heuristic better |
| Field Trip Form | Heuristic better |
| I-9 | AcroForm path correct |

## Overall Recommendation

Choose **Path A: Improve heuristic**.

Do not switch to Azure-first for Pro users based on this corpus. Azure dramatically under-detects text fields on every measured flat PDF:

- Marriage: 39/145
- SP-650: 12/34
- Eden: 3/21
- Field trip: 1/19

Do not raise the heuristic threshold so Azure handles dense forms. The marriage license is the exact dense-form case in question, and heuristic detects 153 against a ground truth of 145 while Azure detects only 39. Raising the threshold would route the form to the worse detector.

Recommended next quality work should be heuristic refinement, not detector replacement:

- Improve checkbox vs radio classification for dense civil/government forms.
- Add geometry scoring / visual review harness, because count alone is not enough.
- Avoid blanket grid suppression. Use table-aware logic that distinguishes real editable table cells from decorative/structural grid lines.
- Preserve AcroForm short-circuit as-is.
