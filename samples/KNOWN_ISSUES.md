# Known Detection Issues — v0 Corpus

This document captures documented failure modes for specific PDFs in our
corpus, distilled from the main NoStringsPDF repository's accumulated
analysis (April–May 2026). Each entry is a regression test target: when
the detection pipeline runs against the v0 corpus, we measure whether
these specific failure modes have been resolved.

**Source documents** (preserved in `docs/legacy/`):
- `detection-ground-truth.md` — manually counted ground truth for problem PDFs
- `detection-quality-report.md` — measured detector output, 2026-05-05
- `detection-measurement-guide.md` — IoU scoring methodology
- `EVALUATION_RESULT_Apr_21.md` — provider comparison (Azure vs Google vs Textract vs Adobe vs Mistral)
- `FIELD_RENDERING_RULE.md` — system-vs-manual field rendering constraint
- `measurements/baseline-2026-05-06.md`, `12C-B-*.md` — historical scoring tables

**Important context:** The strategic decision (April 20, 2026) was that
hardcoded form-specific template branches in `main.py` (`marriage_license`
at line 1733, `eden_nomination` at line 1806, `field_trip`) would not be
fixed further. They were retained as safety nets until the Azure path
validates correctly, after which they'd be deleted. Subsequent measurement
(May 5) showed Azure under-detects text fields drastically on these forms
(Marriage: 39/145, Eden: 3/21, Field Trip: 1/19) — so the strategic plan
shifted to **heuristic refinement, not detector replacement**.

The Detection Lab's job is to:
1. Re-measure each of these failure modes systematically
2. Track whether heuristic improvements (or future ML-assisted ranking)
   resolve them
3. Preserve regression-test continuity with the historical baselines

---

## Marriage License (NJ REG-77)

**File in lab corpus:** `samples/flat/digital/local_marriage_civil_union_license_application_form_pdf.pdf`

**Ground truth (manually counted 2026-05-05):**
- Page 1: 64 text + 34 checkbox = 98 fields
- Page 2: 43 text + 4 checkbox = 47 fields
- Total: **107 text + 38 checkbox = 145 fields**

**Historical detection measurements:**

| Run | Detector | Detected | TP | FP | FN | Precision | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline 2026-05-06 | heuristic | 153 | — | — | — | — | — |
| post-batch1 | heuristic | 153 | 135 | 18 | 20 | 0.871 | 0.8824 |
| 12C-B-pre | heuristic | 153 | 135 | 18 | 20 | 0.871 | 0.8824 |
| 12C-B-post | heuristic | 151 | 151 | 0 | 4 | **0.9742** | **1.0** |
| 12C-B-verify | heuristic | 151 | 151 | 0 | 4 | 0.9742 | 1.0 |
| Azure (one-off) | azure | 39 | — | — | ~106 | high for checkboxes | ~27% |

**Open documented issues:**
1. **Place + date fields render at 6pt** — Reported May 20, 2026; described
   as "took a ton of iterations" and "in decent shape" but still wrong.
   Root cause: text-overflow handling in the editor's `textFit.ts` floor.
   The transcript at `2026-04-27-slices-10A-10C-rotation.md` references
   "6pt minimum font size floor, allows overflow if still too long."
2. **36 expected checkboxes are detected as `radio` type** — Heuristic raw
   output gives `radio: 36, text: 117`. Ground truth says checkboxes.
   The geometry is right; the type label is wrong.

**Root cause (documented):** "The pdfplumber content stream approach
correctly finds all drawn lines, but the marriage license form has 14
vertical line positions — only 3 of which are actual column dividers
(x=18 left edge, x=306 center, x=594 right edge). The other 11 are short
internal dividers within individual cells (State/Zip separators,
date/place dividers in the domestic status section, etc.)."

**Why generic grid suppression fails on this form:** "The marriage
license is table-cell dense, but the measured heuristic result is 153 vs
expected 145. That suggests the current heuristic is much closer to
correct than a blanket grid-suppression strategy. For this form, many
true fields are inside grid/table cells. Generic grid filters are
dangerous because they remove real fields."

**Hardcoded branch reference:** `apply_form_specific_cleanup()`
in `main.py:1733` (deprecated April 20, retained as safety net).

**iOS comparison:** ~143 detected (~99% recall on visual inspection).
2 SSN segment boxes on page 2 missed by iOS.

---

## Eden Lane Nomination Form

**File in lab corpus:** `samples/flat/digital/local_post_5330469_2026_el_nomination_form_1.pdf`

**Ground truth:** **21 fields total** (3 checkbox + 18 text/signature/date)

**Historical detection measurements:**

| Run | Detector | Detected | TP | FP | FN | Precision | Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline 2026-05-06 | heuristic | 21 | 21 | 0 | 0 | 1.0 | 1.0 |
| 12C-B-pre | heuristic | 21 | 21 | 0 | 0 | 1.0 | 1.0 |
| 12C-B-post | heuristic | 21 | 21 | 0 | 0 | 1.0 | 1.0 |
| 12C-B-verify | heuristic | 21 | 21 | 0 | 0 | 1.0 | 1.0 |
| Azure (one-off) | azure | 3 | — | — | 18 | high for checkboxes | ~14% |

**Open documented issues:**
1. **Geometry/alignment** — Heuristic count is perfect, but "Existing
   known geometry issue remains separate from detection count quality."
   The `eden_nomination` hardcoded template branch at `main.py:1806`
   applies known-form-specific geometry corrections that the generic
   detector does not produce.
2. **Hardcoded cleanup was discontinued** — April 20 decision: "Stop
   spending time on Eden hardcoded cleanup and let the future AI path
   supersede it." Subsequent Azure measurement showed Azure finds only 3
   of 21 fields, so this strategic premise is wrong — heuristic refinement
   is the path, not Azure replacement.

**Specific known producer issue (from HANDOFF.md):** "The raw generic
labeled-underline detector already finds both `Name:` and `Address:` on
the Eden form before any special-case cleanup runs. Producer tracing
showed the long row is coming from a separate text-field producer /
downstream handling on the same line. The three correct checkbox
candidates are already present from `detect_checkboxes(...)`. This points
to a later producer or downstream row handling step as the source of the
long field."

---

## SP-650 (PA State Police, non-fillable variant)

**File in lab corpus:** `samples/flat/digital/local_sp_650_non_fill.pdf`

**Ground truth:** **34 fields total** (22 text + 12 radio across 5 groups)

**Historical detection measurements:**

| Run | Detector | Detected | Precision | Recall | Notes |
|---|---|---:|---:|---:|---|
| 12C-A | heuristic | 34 | ~100% | ~100% | Correctly finds 22 text + 12 radios |
| 12C-A | azure | 12 | high for selection marks | ~35% overall | Returns radios as checkboxes; misses all text |

**Status:** Heuristic detection currently works correctly on this form.
**Regression risk:** Any heuristic refinement targeted at the Marriage
License (where checkbox-vs-radio classification needs fixing in the
opposite direction) could regress SP-650 radio detection. **Cross-form
regression testing is mandatory.**

---

## Field Trip Authorization Form

**File in lab corpus:** `samples/flat/digital/local_center_travel_field_trip_authorization_form.pdf`

**Ground truth:** **19 fields total** (all text)

**Historical detection measurements:**

| Run | Detector | Detected | Precision | Recall | Notes |
|---|---|---:|---:|---:|---|
| 12C-A | heuristic | 19 | ~100% | ~100% | All text fields found |
| 12C-A | azure | 1 | high | ~5% | Finds one text field; misses nearly everything |

**Status:** Heuristic detection works correctly. Hardcoded `field_trip`
branch in `main.py` may be unnecessary now (post-12C-B).

---

## instructions.pdf

**File in lab corpus:** `samples/flat/digital/local_instructions.pdf`

**Open documented issues (reported May 20, 2026):**
- **Underdetection** — only 9 fields detected when there should be many
  more (specific expected count not yet ground-truthed).

**Action required:** Manual ground-truth count needed. This is not yet
in the historical measurement set (it predates the 12C-A measurement
corpus). High-priority addition to v0 lab benchmark.

---

## Medical History Intake Form

**File in lab corpus:** `samples/flat/digital/local_medical_history_intake_form.pdf`

**Open documented issues (reported May 20, 2026):**
- Detection issues, specific failure mode TBD. 14-page form.

**Action required:** Manual ground-truth count + failure-mode
characterization needed. Also not yet in the historical measurement set.

---

## I-9 (AcroForm reference)

**File in lab corpus:** `samples/acroforms/raw/uscis/uscis_i9.pdf`
(government download — duplicate of local file by SHA256)

**Ground truth:** **130 fields via AcroForm widgets** (text: 122, checkbox: 8)
Pages: 1 (52), 3 (39), 4 (39).

**Historical detection:**

| Detector | Detected | Precision | Recall | Notes |
|---|---:|---:|---:|---|
| AcroForm | 130 | ~100% | ~100% | AcroForm short-circuit is the correct path. NOT to be used in heuristic-vs-Azure comparisons. |

**Status:** Reference fixture. AcroForm extraction works; this PDF tests
the AcroForm path, not heuristic detection.

---

## Method: how the lab should re-measure these

Per `detection-measurement-guide.md`:

1. **Ground truth files** live at `benchmarks/ground_truth/<filename>.pdf.json`
   (same schema as historical: `{pdf, page_count, labeled_at, review_status, fields: [{id, page, type, bbox, label?, group_id?}]}`).
   `review_status` is `draft` (bootstrapped) or `human_reviewed` (authoritative).

2. **Scoring uses IoU at threshold 0.5**, page-aware, greedy match by
   highest IoU. Metrics: TP, FP, FN, type mismatches, precision, recall.

3. **Initial bootstrap** runs the heuristic detector and writes
   `review_status: "draft"` ground truth. These are regression tripwires,
   not authoritative truth, until human-reviewed.

4. **Compare runs** by JSON delta: detected count, recall, precision,
   fields gained, fields lost.

5. **Azure measurement** is used sparingly because each call costs money.
   One run per PDF is enough for benchmark purposes.

The Detection Lab benchmark runner should match this schema so historical
baselines (especially `12C-B-post` and `baseline-2026-05-06`) remain
comparable.

---

## Strategic position (May 2026)

From `detection-quality-report.md` overall recommendation:

> Choose **Path A: Improve heuristic**.
>
> Do not switch to Azure-first for Pro users based on this corpus. Azure
> dramatically under-detects text fields on every measured flat PDF.
>
> Do not raise the heuristic threshold so Azure handles dense forms. The
> marriage license is the exact dense-form case in question, and heuristic
> detects 153 against a ground truth of 145 while Azure detects only 39.
> Raising the threshold would route the form to the worse detector.
>
> Recommended next quality work should be heuristic refinement, not
> detector replacement:
> - Improve checkbox vs radio classification for dense civil/government
>   forms.
> - Add geometry scoring / visual review harness, because count alone is
>   not enough.
> - Avoid blanket grid suppression. Use table-aware logic that
>   distinguishes real editable table cells from decorative/structural
>   grid lines.
> - Preserve AcroForm short-circuit as-is.

The Detection Lab's v0 benchmark is the infrastructure that lets us
measure whether each of these improvements actually moves the needle on
the specific known-issue forms above.

---

## What still needs to be ground-truthed

PDFs in the v0 corpus that **do not yet have a ground-truth field count**:

- `local_instructions.pdf` (reported underdetection: 9 found, more expected)
- `local_medical_history_intake_form.pdf` (failure mode TBD)
- `local_publicwatermassmailing.pdf` (8 pages, no historical measurement)
- `local_uoa_intake_paperwork_packet.pdf` (4 pages, no historical measurement)
- `local_71048.pdf`, `local_72010.pdf`, `local_75710.pdf` (NJ numbered forms)
- `local_post_5403785_eden_valid_ballot_2026.pdf`

The next benchmark task is to extract or estimate ground truth for these
so they can join the measurement table above.
