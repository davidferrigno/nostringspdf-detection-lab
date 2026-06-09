# OCR Line/Box Experiment Plan

## Purpose

The lab queue can identify PDFs that look scanned or image-only: no text,
no AcroForm widgets, image-heavy pages, and zero or low detector output. This
experiment will eventually test whether OCR plus geometric line/box detection
can turn those documents into usable fill-zone candidates.

Do not use filled real-user forms. Inputs must be public blank forms,
synthetic forms, or local-only `sensitive_do_not_store` references that are
skipped by default.

## Input

- `scanned_image` lane entries in `corpus/manifest.json`.
- Existing queue results where `signals.scanned_image_likely` is true.
- Public blank or synthetic scanned-style PDFs only.

## Output Targets

- OCR text blocks with page, bbox, text, and confidence.
- Horizontal and vertical line candidates.
- Box candidates for empty fill regions.
- Checkbox candidates.
- Signature-line candidates.
- Candidate field boxes normalized to `docs/FIELD_SCHEMA.md`.
- Overlay screenshots showing candidates on rendered pages.
- Per-document JSON results under ignored run or experiment output folders.

## Future Metrics

- Candidate recall against reviewed ground truth.
- False positives by page and by candidate type.
- Line alignment stability.
- Checkbox count accuracy.
- Field box IoU when reviewed GT exists.
- Runtime per page.

## First Experiment Slice

1. Select 2-3 public blank or synthetic scanned-image PDFs.
2. Render pages to images.
3. Extract OCR text blocks without storing sensitive text from local-only files.
4. Detect long horizontal lines and rectangular boxes.
5. Generate overlays for manual review.
6. Convert candidates to draft fields with `needs_review: true`.

## Priority Case: Municipal Court Complaint

- Manifest id: `municipal_court_complaint_blank`
- Target pages: 3-5.
- Current status: baseline detectors return zero fields.
- Signals: no extractable text, no AcroForm widgets, one image per page.
- Candidate types: text lines, rectangle boxes, checkbox candidates,
  signature lines, date fields, and large narrative boxes.
- Next step: render overlays for pages 3-5 and compare OCR/linebox
  candidates against manually reviewed empty field boxes.

## Non-Goals

- No production detector changes.
- No Azure, Textract, or hosted OCR integration in this slice.
- No automatic promotion of OCR candidates to reviewed ground truth.
- No storage of filled user data.
