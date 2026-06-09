# OCR Linebox Reviews

This folder stores manual review files for OCR/linebox experiment candidates.
Review files are small JSON annotations; generated runs and overlays stay under
`experiments/ocr_linebox/runs/` and remain ignored.

## Create A Review Template

```powershell
py -3.13 scripts/create_linebox_review_template.py `
  --result experiments/ocr_linebox/runs/latest/results/municipal_court_complaint_blank.json `
  --out experiments/ocr_linebox/reviews/municipal_court_complaint_blank.review.json
```

The template copies candidate metadata only. It does not copy PDFs or modify
generated run outputs.

## Open Overlays

Open the PNGs under:

```text
experiments/ocr_linebox/runs/latest/overlays/
```

For the municipal packet, start with:

```text
municipal_court_complaint_blank_p3.png
municipal_court_complaint_blank_p4.png
municipal_court_complaint_blank_p5.png
```

## Candidate Labels

Edit `candidate_reviews[].label`:

- `good`: candidate is usable as-is.
- `bad`: false positive or junk candidate.
- `duplicate`: duplicates another candidate; set `group_id` when useful.
- `needs_adjustment`: right target, but bbox/type needs correction.
- `uncertain`: needs another pass.
- `unreviewed`: default.

Optional fields:

- `expected_type`: corrected type, such as `checkbox` or `signature_line`.
- `corrected_bbox`: adjusted PDF-coordinate bbox.
- `notes`: reviewer comment.
- `matched_ground_truth_id`: future GT link.

## Missing Fields

Until scanned ground truth exists, use page-level notes:

```json
"expected_missing_notes": [
  "signature line missed",
  "checkboxes in top paragraph missing",
  "large narrative box should be one field"
]
```

## Score A Review

```powershell
py -3.13 scripts/score_linebox_review.py `
  --review experiments/ocr_linebox/reviews/municipal_court_complaint_blank.review.json `
  --out experiments/ocr_linebox/reviews/municipal_court_complaint_blank.score.md
```

This writes Markdown, JSON, and CSV score summaries.

## Municipal Pages 3-5 Checklist

- Mark real empty name/address/phone/email lines as `good` or
  `needs_adjustment`.
- Mark real printed checkboxes as `good`.
- Mark text glyph fragments and logos as `bad`.
- Mark repeated boxes on the same target as `duplicate` and share a `group_id`.
- Use page missing notes for missed checkbox pairs, signature/date lines, and
  large narrative regions.
- Do not promote candidates to ground truth from this review alone.
