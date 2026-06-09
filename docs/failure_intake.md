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
- Run lane benchmark:
- Render overlays:
- Other:

## Privacy Rule

Real filled forms with personal data must be marked `sensitive_do_not_store`.
They must not be committed, copied into `samples/`, or used to generate
reusable templates from filled user values.
