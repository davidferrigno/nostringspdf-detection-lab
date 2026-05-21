# Field Schema — Detection Integration Contract

**Version:** 1.0
**Effective:** May 20, 2026
**Status:** Active. All detection backends in both the lab and production
must conform.

This document defines the shared output contract between detection
backends. Both the **NoStringsPDF detection lab** (research) and the
**NoStringsPDF production backend** (`services/heuristic_service.py`)
implement detectors that return this schema.

The schema is the **only stable contract** between the two repositories.
Everything else — detector algorithms, scoring methodology, pipeline
stages, manifest formats — can change independently in each repo as long
as the output schema is preserved.

---

## 1. The Field object

A detection backend's `detect()` function returns a `list[Field]` where
each `Field` is a dict with these keys:

```python
Field = {
    "id":     str,                  # required, unique within the list
    "page":   int,                  # required, 1-indexed
    "type":   FieldType,            # required, see §2
    "bbox":   [float, float, float, float],  # required, see §3
    "label":  str | None,           # optional, see §4
}
```

### Required fields

#### `id` (string)

A detector-internal identifier unique within the returned list. Used to
trace each detection back to its source.

Convention: `d1`, `d2`, `d3`, ... incremented as fields are emitted.

The id is NOT stable across detector runs. The same field detected by
two different runs may have different ids. Do not use ids to compare
runs — use IoU matching on bboxes (see §3).

#### `page` (int)

1-indexed page number. The first page is `1`, not `0`. Required even on
single-page PDFs (always `1` in that case).

#### `type` (string enum)

One of:

| Value | Meaning | Common source |
|-------|---------|---------------|
| `"text"` | Free-text input field | Underline, AcroForm `/Tx`, char-box row |
| `"checkbox"` | Single binary option | Small visible square, AcroForm `/Btn` |
| `"radio"` | One-of-many selection | AcroForm `/Btn` with `Ff & 0x10000` |
| `"choice"` | Dropdown / select | AcroForm `/Ch` |
| `"signature"` | Signature field | AcroForm `/Sig`, signature line glyph |

A detector that cannot determine the type should default to `"text"`.
A detector should NEVER emit a custom type string. New types require a
schema version bump.

#### `bbox` (list of 4 floats)

Bounding box in **top-left origin, 72 DPI points**, format:

```
[x, y, width, height]
```

Where:
- `x` = horizontal offset from page left edge (points, 1pt = 1/72 inch)
- `y` = vertical offset from page top edge (points)
- `width` = horizontal extent (points)
- `height` = vertical extent (points)

All values are positive floats. Width and height must be > 0.

**The y-axis points DOWN** (top of page is y=0). This is the same
convention as image coordinates, NOT the same as the PDF native
coordinate system (which has y=0 at the bottom).

**Detectors must transform** from PDF-native (bottom-left origin)
to top-left origin before emitting. See §3.1 for the transform.

Values should be rounded to 2 decimal places to keep JSON output stable.

### Optional fields

#### `label` (string or None)

Nearby text that hints at the field's purpose. Examples: `"Name"`,
`"Date of Birth"`, `"SSN"`, `"Signature of Applicant"`.

Optional because not all detection methods produce labels. The acroform
extractor doesn't return labels (widgets don't typically include them in
the bbox extraction); heuristic detectors do.

Maximum length: 256 characters. Longer strings should be truncated to
the most relevant portion (usually the closest text token to the left
or above the field).

### Reserved-but-unused fields

Detector implementations MAY include additional underscore-prefixed
fields in their output for internal tracing or debugging:

```python
{
    "id": "d23",
    "page": 1,
    "type": "text",
    "bbox": [100.5, 200.0, 158.4, 24.0],
    "label": "SSN",
    "_char_box_row": True,        # internal marker (heuristic_lab_v2)
    "_source_widget_id": "f19",   # trace to AcroForm widget
}
```

These fields are NOT part of the contract. Consumers MAY ignore them.
Tools that serialize fields for storage SHOULD strip underscore-prefixed
keys before persistence to keep the data clean.

---

## 2. Field type semantics

### `text`

A field expecting free-text input. The bbox describes the visible area
where text would be entered. Subsumes:
- Single-line text inputs (underline-based or rectangular)
- Multi-line text areas
- Segmented char-box rows (SSN, EIN, account number — one row = one
  field; see §6.1 for lane-specific guidance)
- Date inputs (rendered as text fields)
- Number inputs (rendered as text fields)

### `checkbox`

A field with two states (checked / unchecked). The bbox describes the
visible square or rectangle the user clicks. Each checkbox is one field;
groups of related checkboxes are emitted as separate `checkbox` fields,
not as one `radio` group.

### `radio`

A single radio button within a mutually exclusive group. The bbox
describes the visible circle/square. Each radio button is one field;
the grouping relationship is captured in AcroForm metadata (e.g.,
shared parent) but is NOT preserved in this schema. Consumers that
need group identity must read it from the AcroForm directly.

This is a known limitation. Schema v2 may add a `group_id` field.

### `choice`

A dropdown / select / combobox. The bbox describes the visible field
area where the selected value appears.

### `signature`

A signature field — either a click-to-sign target (AcroForm `/Sig`) or a
detected signature line. Treated as a text field for filling purposes,
but distinguishable for UI rendering (e.g., showing a signature pen
icon).

---

## 3. Coordinate system

### 3.1 Transform from PDF-native to schema bbox

PDF coordinate space:
- Origin at bottom-left
- y-axis points UP
- Units: points (1pt = 1/72 inch)

Schema bbox:
- Origin at top-left
- y-axis points DOWN
- Units: points

Given:
- `page_height` = page MediaBox height in points
- `x_ll, y_ll, x_ur, y_ur` = PDF native rect (lower-left to upper-right)

Transform:
```python
x_schema = min(x_ll, x_ur)
width = abs(x_ur - x_ll)
height = abs(y_ur - y_ll)
y_bottom_native = min(y_ll, y_ur)
y_schema = page_height - y_bottom_native - height
```

### 3.2 Rotation handling

If a page has rotation metadata (90°, 180°, 270°), the detector MUST
return bboxes in the page's rendered orientation (post-rotation, as the
user sees it). The transform from raw widget coordinates to rendered
orientation is the detector's responsibility.

This is a hard requirement. Production rendering uses these bboxes as
overlay coordinates on the rendered page image. A bbox in pre-rotation
coordinates will overlay incorrectly.

### 3.3 Multi-page consistency

Each field's `page` value is the page it lives on. The `bbox` is in
that page's coordinate system (its own y-axis, not a global y-axis
across all pages).

To render a field on page 5: render page 5 to image, overlay using
page 5's bbox directly.

---

## 4. Label conventions

When emitted, labels should be:
- Stripped of leading/trailing whitespace
- Collapsed: internal whitespace normalized to single spaces
- Free of control characters
- Reasonable: prefer "Date of Birth" over "Date of Birth (See Note 2)"

Detectors should NOT include:
- Field numbers or letters (e.g., "1.", "A.") unless they are part of
  the field's official name
- Filler text from the form layout
- Garbled OCR artifacts (if OCR confidence is low, omit label)

---

## 5. Versioning

This is **Schema v1.0**.

Schema versions are bumped when:
- A new required field is added (major bump: v2.0)
- An optional field becomes required (major bump: v2.0)
- A type value is added or removed (major bump: v2.0)
- A coordinate convention changes (major bump: v2.0)
- Documentation clarifications, new optional fields, or new conventions
  for existing fields (minor bump: v1.1, v1.2, ...)

When the schema changes, BOTH the lab repo and the production repo
update their copy of this file simultaneously, with a changelog at the
end of the file.

Backends that emit a particular schema version SHOULD include a
top-level metadata field in any persisted JSON:
```json
{
    "schema_version": "1.0",
    "backend": "heuristic_lab_v1",
    "fields": [...]
}
```

This is REQUIRED for ground truth files and benchmark scorecards. It
is OPTIONAL for ephemeral detector output (the list returned by
`detect()`).

---

## 6. Lane-specific guidance

Detection happens in two lanes (see `docs/char_box_finding.md`):

### Lane A — AcroForm scoring

Ground truth is AcroForm widget bboxes (one widget = one field).
Detectors are scored on whether they reproduce the author's widget
segmentation.

**Char-box rows:** AcroForm authors may segment a visible SSN row as 1,
2, 3, or 9 widgets. Heuristic detectors emit row-as-single-field, which
will NOT score TP against multi-widget ground truth. This is expected;
do not "fix" by emitting per-cell fields.

### Lane B — flat-PDF scoring

Ground truth is human-marked usable-fill-zones (no widgets exist; humans
decide what counts as a field). Detectors are scored on UX-meaningful
detection.

**Char-box rows:** emit ONE field per visible row (entire row width).
This is the convention humans use when marking flat-PDF GT.

**Label-position fields:** when a labeled prompt ("5. Address") has no
visible underline but row position implies a field, emit it as a `text`
field spanning the expected row width.

When a detector is run against the wrong lane (e.g., `heuristic_lab_v2`
which emits row-as-single-field, scored against Lane A ground truth that
has 3-widget SSN), the benchmark will under-score it. This is correctly
flagged by the lab as a lane mismatch, not a detector failure.

---

## 7. Backward compatibility commitments

Once published, Schema v1.0 will be supported for **at least 18 months**
from its effective date (until ~Nov 2027). New schema versions will be
introduced as opt-in via the `schema_version` metadata field.

Backends emitting v1.0 will continue to work even after newer schema
versions exist. Production code MUST handle the v1.0 schema for the
support window.

---

## 8. Example outputs

### Example 1: AcroForm widget extraction (acroform_self backend)

```json
{
    "schema_version": "1.0",
    "backend": "acroform_self",
    "fields": [
        {
            "id": "d1",
            "page": 1,
            "type": "text",
            "bbox": [73.0, 156.0, 350.0, 24.0],
            "label": null
        },
        {
            "id": "d2",
            "page": 1,
            "type": "checkbox",
            "bbox": [73.0, 245.0, 12.0, 12.0],
            "label": null
        }
    ]
}
```

### Example 2: Heuristic detection (heuristic_lab_v1)

```json
{
    "schema_version": "1.0",
    "backend": "heuristic_lab_v1",
    "fields": [
        {
            "id": "d1",
            "page": 1,
            "type": "text",
            "bbox": [120.5, 200.0, 280.0, 12.0],
            "label": "Name:"
        },
        {
            "id": "d2",
            "page": 1,
            "type": "checkbox",
            "bbox": [73.0, 245.0, 8.0, 8.0],
            "label": "Individual"
        }
    ]
}
```

### Example 3: Char-box row (heuristic_lab_v2, flat lane)

```json
{
    "id": "d23",
    "page": 1,
    "type": "text",
    "bbox": [417.6, 372.0, 158.4, 24.0],
    "label": "Social security number",
    "_char_box_row": true
}
```

---

## 9. Implementation checklist for backend authors

When implementing a new backend (in either repo):

- [ ] Implement `detect(pdf_path: Path) -> list[dict]`
- [ ] Use the `Field` dict shape: `id`, `page`, `type`, `bbox`, optional `label`
- [ ] Apply the PDF→schema coordinate transform (§3.1)
- [ ] Handle page rotation (§3.2)
- [ ] Round bbox values to 2 decimal places
- [ ] Emit `type` from the allowed enum only
- [ ] Default unknown types to `"text"`
- [ ] Never raise on malformed PDFs — return `[]` and log internally
- [ ] If persisting output, include `schema_version: "1.0"` and `backend: <name>`

---

## 10. Changelog

### v1.0 (2026-05-20)

Initial schema definition. Extracted from existing production heuristic
output and lab benchmark conventions established 2026-05-20.

Defines:
- Required fields: `id`, `page`, `type`, `bbox`
- Optional fields: `label`
- Type enum: `text`, `checkbox`, `radio`, `choice`, `signature`
- Coordinate convention: top-left origin, 72 DPI points, post-rotation
- Underscore-prefixed reserved field convention
- Lane A vs Lane B guidance for ambiguous cases

Known limitations (deferred to v2):
- No `group_id` for radio button group identity
- No `confidence` score for soft detections
- No `text_alignment` hint for text fields
- No nested field support (e.g., signature with date pair)
