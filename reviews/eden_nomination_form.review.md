# Review: eden_nomination_form

This Markdown is generated from the JSON review file. Edit the JSON only.

- Packet manifest: `reports/review_packets/eden_nomination_form/form_manifest.json`
- Source PDF SHA-256: `fa9ad760cc636cbbc783aa9b92c9d986599e00758391286535c2b9cc65f4ec42`
- Source GT SHA-256: `b0872e35c9116966c06e59f00e64e4848827cddd4d14cb64ae579bb3fd7db1d8`
- Source GT provenance: `detector-bootstrapped draft via heuristic_lab_v2`
- Reviewer: ``
- Reviewed at: ``
- Document decision: `pending`

| Done | Field | Decision | New type | New geometry | Comment |
| --- | --- | --- | --- | --- | --- |
| [ ] | `g1` | `pending` | `None` | `null` |  |
| [ ] | `g2` | `pending` | `None` | `null` |  |
| [ ] | `g3` | `pending` | `None` | `null` |  |

Additions recorded in JSON: 0

## Document-level zero-field decision

`document_decision` normally remains `pending`.

Set `document_decision` to `confirmed_zero_fields` only after inspecting the source form and affirmatively deciding that it genuinely contains zero fillable fields.

Do not use `confirmed_zero_fields` merely because the detector found nothing, the draft contains nothing, fields were difficult to identify, or the form is confusing.

If fillable regions exist, record them in the structured `additions` array instead.

## Review instructions

1. Edit the JSON review file, not this generated Markdown companion.
2. Resolve every pending field as accept, update, or delete.
3. Add reviewer and reviewed_at in ISO-8601 format.
4. Leave document_decision pending unless source inspection affirmatively confirms zero fillable fields.
5. If fillable regions exist, record additions with field_id, page, type, geometry, label, and comment.
6. Generate a candidate without approval:

`python scripts/apply_gt_review.py --review reviews/eden_nomination_form.review.json`

7. Inspect every page of the candidate confirmation overlay.
8. Only the owner may run the separate approval command with the printed token and inspection assertion.
