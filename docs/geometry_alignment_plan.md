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

## GEOMETRY-ALIGNMENT-1 Baseline

`scripts/score_geometry_alignment.py` adds a standalone scoring pass for the
Eden nomination form. It runs a selected lab backend, compares detections to
the draft flat-PDF ground truth, and writes JSON, CSV, Markdown, and visual
overlay outputs under `experiments/geometry_alignment/runs/`.

Current Eden inputs:

- Corpus id: `eden_nomination_form`
- Backend default: `heuristic_lab_v2`
- Ground truth: `benchmarks/ground_truth_flat/el_nomination_form.draft.json`
- Review status: draft only; do not treat scores as promotion-ready.
- Draft GT field count: three checkbox targets in the paragraph preference
  sentence.

Failure classes tracked by the scorer:

- `aligned`: detector and GT boxes have strong overlap and low center drift.
- `y_shifted`: detector center or visible baseline relation is vertically off.
- `x_shifted`: detector center is horizontally off.
- `wrong_size`: detector overlaps the target but has poor size/IoU.
- `overlaps_label`: detector box materially covers nearby printed text.
- `false_positive`: detector box has no GT match.
- `missed_gt`: GT target has no detector match.

Metric targets for future Eden work:

- Alignment rate should remain 1.0000 for reviewed checkbox targets.
- Mean checkbox distance from visible label-anchored square geometry should
  stay near zero.
- Label-overlap risk should remain below 0.10 for checkbox and line targets.
- Any geometry correction experiment should improve y-offset and baseline
  distance without increasing false positives.

Next experiment:

- Add reviewed ground truth for Eden underline/signature/date targets, then
  rerun the scorer to measure whether field-count success still masks visual
  placement errors.

## Non-Goals

- No production detector changes in this planning slice.
- No automatic promotion of draft ground truth.
- No filled or sensitive PDFs in the committed corpus.
