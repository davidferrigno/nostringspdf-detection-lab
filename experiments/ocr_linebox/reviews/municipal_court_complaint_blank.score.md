# Linebox Review Score - municipal_court_complaint_blank

Generated: 2026-06-09 06:50:19
Source result: `experiments/ocr_linebox/runs/latest/results/municipal_court_complaint_blank.json`

## Summary

- Total candidates: 249
- Reviewed candidates: 0
- Unreviewed candidates: 249
- Good: 0
- Bad: 0
- Duplicate: 0
- Needs adjustment: 0
- Uncertain: 0
- Precision-like among reviewed: n/a

**Status:** unreviewed template created. Fill `candidate_reviews[].label` before using this as a quality score.

## Labels

| Label | Count |
| --- | ---: |
| unreviewed | 249 |

## Candidate Types

| Type | Count |
| --- | ---: |
| checkbox | 60 |
| date_field | 31 |
| narrative_box | 30 |
| signature_line | 4 |
| text_box | 33 |
| text_line | 91 |

## Pages

| Page | Candidates | By type |
| ---: | ---: | --- |
| 1 | 20 | checkbox:17, date_field:1, text_line:2 |
| 2 | 18 | checkbox:9, date_field:3, text_line:6 |
| 3 | 102 | checkbox:20, date_field:7, narrative_box:25, text_box:26, text_line:24 |
| 4 | 41 | checkbox:8, date_field:6, narrative_box:2, signature_line:2, text_box:3, text_line:20 |
| 5 | 68 | checkbox:6, date_field:14, narrative_box:3, signature_line:2, text_box:4, text_line:39 |

## Top False-Positive Types

None reviewed yet.

## Pages Needing Review

1, 2, 3, 4, 5

## Missing-Field Notes

None recorded.

## Next Heuristic Recommendations

- Review municipal pages 3-5 first.
- Mark obvious text glyph fragments as `bad`.
- Mark repeated boxes on the same field as `duplicate` and share a `group_id`.
- Use `expected_missing_notes` for missing checkboxes, signature lines, date fields, or narrative boxes.
