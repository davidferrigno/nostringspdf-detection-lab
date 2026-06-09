# Failure Intake Template

Use this template to record a detector failure without committing sensitive
documents. Do not attach or copy a filled real-user PDF into the repo.

## Document

- Filename:
- Local path, if sensitive local-only:
- Document type:
- Source:
- Lane: acroform / flat_text / scanned_image / comb_fields / checkbox_radio / signature_targets / known_failure
- Expected benchmark lane: A / B / unknown
- Privacy status: blank / synthetic / sensitive_do_not_store
- May the PDF be committed? yes / no

## Failure

- Failure type:
- Detector/backend:
- Observed result:
- Expected result:
- Affected pages:
- Non-sensitive screenshots or notes:

## Corpus Action

- Add blank/public PDF to corpus:
- Create synthetic surrogate:
- Reference sensitive local-only path in manifest:
- Needs ground truth:
- Needs manual review:
- Known failure:

## Next Lab Action

- Bootstrap ground truth:
- Hand-review/promote ground truth:
- Run queue:
- Run pipeline:
- Run lane benchmark:
- Render overlays:
- Route to OCR line/box experiment:
- Other:

## Pipeline Tracking

- Added to `corpus/manifest.json`:
- Latest run id:
- Latest scorecard path:
- Compare result:
- Promotion gate impact:

## Example: Scanned Municipal Complaint

- Filename: `municipal_court_complaint_blank.pdf`
- Document type: municipal court complaint packet
- Lane: scanned_image / checkbox_radio / signature_targets / known_failure
- Failure type: image-only form; baseline detectors return zero fields
- Privacy status: blank
- May the PDF be committed? yes, after visual privacy review
- Next lab action: OCR line/box experiment targeting pages 3-5

## Example: Eden Geometry Alignment

- Filename: `local_post_5330469_2026_el_nomination_form_1.pdf`
- Document type: condominium candidate nomination form
- Lane: flat_text / checkbox_radio / known_failure / geometry_alignment
- Failure type: detected boxes can drift from underlines, paragraph checkboxes,
  signature lines, and date targets
- Privacy status: blank
- May the PDF be committed? already in blank lab corpus
- Next lab action: reviewed geometry ground truth and overlay-based alignment
  metrics

## Privacy Rule

Real filled forms with personal data must be marked `sensitive_do_not_store`.
They must not be committed, copied into `samples/`, or used to generate
reusable templates from filled user values.

Sensitive files may be referenced only by local path when needed for a private
run. The queue and pipeline must skip them when unavailable and must never copy
them into the committed corpus.
