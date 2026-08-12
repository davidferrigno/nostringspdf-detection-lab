# Review Annotations

`review_annotations` is optional detection-lab review metadata. It is not part
of `docs/FIELD_SCHEMA.md`, detector output, matcher input, or benchmark scoring.
The shared Field object and schema version remain unchanged.

## Backward compatibility

A missing `review_annotations` property is equivalent to an empty object. Old
review templates and ordinary unannotated fields continue to work without
modification. Annotated candidates store the validated object at the document
level; annotations are never inserted into `fields[]`.

## Ruled multiline text

This slice supports one annotation kind:

```json
{
  "review_annotations": {
    "summary_field": {
      "kind": "ruled_multiline",
      "line_count": 2,
      "line_guides": [
        {"x1": 50.4, "y": 278.4, "x2": 557.41},
        {"x1": 50.4, "y": 299.52, "x2": 557.41}
      ],
      "wrap": true,
      "vertical_align": "top",
      "max_words": 200
    }
  }
}
```

The annotation key must be a final normalized field ID whose base type is
`text`. A ruled multiline annotation describes one logical response field over
multiple physical writing guides. Each guide is not an independent field.

Guide coordinates use top-left-origin PDF points, matching the Field bbox
coordinate convention. Guides must be ordered from top to bottom, remain
inside the owning field bbox, and contain exactly `x1`, `y`, and `x2`.
`line_count` must equal the number of guides. `wrap` is always `true`,
`vertical_align` is always `top`, and optional `max_words` must be positive.

## Candidate and approval binding

Validated annotations are copied to an annotated candidate as a separate
top-level object. Candidate provenance identifies them as owner-supplied review
metadata rather than detector output. The candidate SHA-256 covers this object,
and the confirmation token binds the candidate hash together with the source
PDF, source ground truth, and review JSON hashes.

Approval independently revalidates the current review and requires the
candidate annotations to equal the normalized review annotations. Changing or
removing an annotation invalidates an earlier candidate and token. A future
human-reviewed output may retain the annotations at document level for
rendering and geometry research.

## Current consumers

Matcher v1, current detectors, overlap navigation, and benchmark metrics ignore
`review_annotations`. The candidate confirmation overlay renders ruled guides
only as owner-inspection evidence.

Promoting this metadata into the shared lab and production field contract would
require a separate coordinated FIELD_SCHEMA version slice in both repositories.
