# Geometry Alignment Plan

## Purpose

The `geometry_alignment` lane tracks flat/digital forms where field counts can
look acceptable while visual placement is still wrong. This is separate from
scanned/OCR failures: the PDF has extractable text and visible geometry, but
detected boxes may drift away from printed underlines, paragraph locations,
checkboxes, or signature/date targets.

## Priority Case: Eden Nomination Form

- Manifest id: `eden_nomination_form`
- Source PDF: `samples/flat/digital/local_post_5330469_2026_el_nomination_form_1.pdf`
- Current status: draft ground truth only, needs manual review.
- Known failure class: geometry/alignment, not image-only OCR.
- Existing notes: historical measurements recorded strong field counts, while
  known geometry issues remained separate from count quality.

## Future Experiment Goals

- Underline baseline alignment: detected text boxes should sit on or just above
  printed underlines, not below them.
- Paragraph checkbox detection: checkbox boxes embedded in sentence text should
  align to the printed square, not the surrounding paragraph baseline.
- Field y-position correction: tune vertical placement against visible field
  geometry rather than only nearby text.
- Multiline region alignment: long narrative regions should align to the full
  writable line set.
- Signature/date targeting: signature and date fields should align to their
  printed lines and labels.
- Overlay screenshots: every geometry experiment should produce visual QA
  overlays before any production review.

## Future Metrics

- Field IoU against reviewed ground truth when available.
- Baseline-distance error for underlined text fields.
- Checkbox center distance from printed checkbox geometry.
- False positives introduced by geometry correction.
- Per-field type stability.

## Non-Goals

- No production detector changes in this planning slice.
- No automatic promotion of draft ground truth.
- No filled or sensitive PDFs in the committed corpus.
