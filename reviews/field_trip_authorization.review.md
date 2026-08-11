# Review: field_trip_authorization

This Markdown is generated from the JSON review file. Edit the JSON only.

- Packet manifest: `reports/review_packets/field_trip_authorization/form_manifest.json`
- Source PDF SHA-256: `4e783cddac59d0227816ad81c3c0f3c631836a30e3964f19aa73392641f84f3a`
- Source GT SHA-256: `440fef685814fc7f6ae9429df64863ed762e08f4a82d6ced7534cc14321621ba`
- Source GT provenance: `detector-bootstrapped draft via heuristic_lab_v2`
- Reviewer: ``
- Reviewed at: ``
- Document decision: `pending`

| Done | Field | Decision | New type | New geometry | Comment |
| --- | --- | --- | --- | --- | --- |

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

`python scripts/apply_gt_review.py --review reviews/field_trip_authorization.review.json`

7. Inspect every page of the candidate confirmation overlay.
8. Only the owner may run the separate approval command with the printed token and inspection assertion.
