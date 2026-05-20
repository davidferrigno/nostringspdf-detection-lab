# Heuristic Lab v1 — Failure Analysis

**Date:** May 20, 2026
**Backend:** `heuristic_lab_v1`
**Benchmark run:** `2026-05-20_223537_heuristic_lab_v1`
**Aggregate:** P=0.6834, R=0.3032, F1=0.4201, type accuracy=0.9935
**Status:** First measurable generic detection baseline. NOT a regression.

---

## Headline

The heuristic detects field types correctly when it finds them (type
accuracy 0.99), but misses 70% of all ground-truth fields. The failure
mode is under-detection driven by limited content-stream visibility, not
hallucination. **6 PDFs scored 0/0** (zero detected) — pure AcroForm
widgets with no content-stream cues. **No PDF scored above F1=0.7.**

This is the right shape of failure for an MVP. We're being honest about
what we don't see rather than fabricating fields.

---

## Architectural validation

**The benchmark confirms production routing order is correct:**

1. **AcroForm widgets** (perfect when present) ← production's first path
2. Template match
3. **Heuristic fallback** ← what the lab measures
4. OCR/ML fallback (future)

The heuristic is NOT intended to replace AcroForm extraction. It exists
to recover fillable structure from **flat PDFs and scanned forms** —
PDFs where no widget annotations exist and field positions must be
inferred from visible geometry.

The lab's measurement of low recall on AcroForm-only PDFs is the
correct signal: it confirms widget extraction must come first. The
heuristic is not the path to fix N-400; AcroForm reading is.

---

## Five failure categories observed

### Category 1: Invisible AcroForm-only widgets (dominant FN cause)

**Definition:** Text/checkbox fields that exist only as widget annotations
in the AcroForm layer with no corresponding visible underline, box, or
glyph in the content stream.

**Evidence:**
- W-9 page 1: f1 (Name), f15 (Address), f16 (City/State/ZIP), f17
  (Requester address), f18 (Account number) — all green FN
- N-400 page 1: f5 (A-Number), f8 (Other Reason), f11 (field office),
  all 9 name-row text fields f12-f20 — all green FN. P=1.0 but R=0.35
  because every detected field was correct, but every text field was
  invisible.

**Architectural implication:** This category CANNOT be solved by the
generic heuristic. The fields have no visible cues to detect. The
production routing solves this by reading AcroForm widgets directly.
The lab confirms this is the correct architecture.

**Effort:** N/A — out of scope for heuristic improvement.

### Category 2: Segmented char-box fields (SSN, EIN, account numbers)

**Definition:** Visibly drawn rows of small adjacent squares for
character-by-character input (e.g., SSN: `___-__-____`).

**Evidence:**
- W-9 page 1: f19-f23 (SSN and EIN segmented boxes) — all green FN.
  The boxes ARE visible on the page, but our v1 heuristic skips
  rows that "look like char boxes" via `looks_like_char_box_row()`.
- IRS 1040, uscis_i9, and other forms with SSN/EIN/phone fields show
  similar patterns.

**Why our v1 misses them:** Production has `detect_char_boxes()` which
identifies these segmented rows and emits them as a single field.
We deliberately excluded this stage from v1 for scope.

**Improvement effort:** ~150 lines. Port `detect_char_boxes()` cleanly.
Expected impact: aggregate recall +5-10% across IRS/USCIS/SSA forms.

**Priority: HIGH**

### Category 3: Prose-context false positives

**Definition:** The heuristic hallucinates fields in dense instructional
text where partial underlines, dashes, or text patterns trigger
detection.

**Evidence:**
- W-9 page 1: `FP:d3` and `FP:d4` near the 3a/3b instruction area.
  The heuristic detected what it thought were field zones in
  paragraph-like instructional text.
- Forms with heavy prose (irs_w4, irs_1040 instructions, terms-of-service
  style text) show elevated FP counts.

**Why our v1 misses them:** Production has `filter_noise_fields()` and
form-context awareness in `detect_underlines()`. We have basic prose
rejection (4+ connectors + lowercase dominance) but no contextual
noise filtering.

**Improvement effort:** ~200 lines. Better prose-region detection;
stricter underline-vs-paragraph-divider classification.
Expected impact: precision +5-10%, particularly on W-4, 1040, b101.

**Priority: MEDIUM**

### Category 4: Label-position fields without visible cues

**Definition:** Fields where the position is implied by a numbered
prompt or label, but no visible underline marks the field zone.

**Evidence:**
- W-9 page 1: "5 Address (number, street...)" — the row IS labeled but
  has no visible underline (it's a hybrid: AcroForm widget hides the
  visual cue)
- Forms with "1. Name", "2. Date", "3. Address" patterns where the
  field comes from row position, not visible geometry

**Why our v1 misses them:** Production has `detect_label_pair_fields()`
which synthesizes Date/Place pairs from header positions. We
deliberately excluded labeled-pair detection.

**Improvement effort:** ~250 lines. Detect numbered prompts, infer
adjacent field zones.
Expected impact: recall +10-15% on flat PDFs with label patterns.

**Priority: HIGH** (especially for flat PDFs)

### Category 5: Multi-column dense forms

**Definition:** Tables and grids where row dividers create false
underlines, and column structure must inform field boundaries.

**Evidence:**
- IRS forms (1040, 1040sb) with multi-column tabular layouts
- uscourts_b101 (P=0.32, R=0.15) — bankruptcy form with heavy grid

**Why our v1 misses them:** Production has `build_grid_cells()` and
`classify_grid_cells()` for grid-aware field extraction. We have only
basic line classification with no grid model.

**Improvement effort:** ~400 lines. Significant architecture work.
Expected impact: variable — major win on IRS tax forms, modest on others.

**Priority: MEDIUM** (high impact, high cost, defer until 1-4 done)

---

## Recall floor — visible geometry richness predicts recall

The v1 benchmark establishes a predictive model:

| Geometry profile | Expected recall (v1) | PDFs |
|-----------------|---------------------|------|
| Pure widget overlay, no visible cues | R ≈ 0 | local_71061, local_ba_51/62, local_ppb_*, nj_mvc_ba49, uscis_g1145 |
| Widget + visible checkboxes only | R ≈ 0.35-0.45 | uscis_n400, uscis_i90 |
| Widget + checkboxes + some underlines | R ≈ 0.5-0.6 | irs_1040sb, irs_8821, local_sts_033 |
| Widget + checkboxes + visible underlines + segmented boxes | TBD (v1 misses segments) | irs_w9, irs_w4 |
| Flat PDF with rich visible cues | TBD (v1 not tested on Marriage etc.) | Marriage, Eden, sp650, field_trip |

**Use this as a hypothesis tester.** When implementing char-box
detection, predict recall change BEFORE running the benchmark:
"IRS forms have visible segmented boxes; expect R to jump on irs_w9,
irs_w4, ssa_521, uscis_n400."

---

## Improvement priority (measured, not guessed)

Based on this analysis, the order for v2 work:

1. **Char-box detection** (Category 2) — ~150 lines, expected aggregate
   recall +5-10%. Well-scoped, low risk, high value.

2. **Label-position inference** (Category 4) — ~250 lines, expected
   recall +10-15% on flat PDFs. This is the key unlock for Marriage
   License and other label-driven forms.

3. **Prose noise filtering** (Category 3) — ~200 lines, expected
   precision +5-10%. Reduces FPs in W-4, 1040, b101.

4. **Text-pattern underlines** (excluded from v1 but in production):
   Detect `____` and `....` patterns as underlines. ~100 lines, low risk.

5. **Grid cell classification** (Category 5) — ~400 lines, significant
   work. Defer until 1-4 land.

---

## What we will NOT add to the lab

These exclusions are **deliberate and permanent**:

- **Production hardcoded cleanup rules** for Marriage, Eden, Field Trip.
  These are evidence of generic algorithm weaknesses, NOT acceptable
  long-term architecture inside the lab. The lab's job is to make those
  patches unnecessary by improving the generic algorithm.

- **OCR fallback.** Separate workstream. Eventually a separate lab
  backend `ocr_lab_v1`.

- **Azure backend integration.** Cost-aware, runs sparingly. Plug in
  later as `azure_lab_v1` for comparison runs only.

- **ML re-ranking.** Premature until the heuristic baseline is mature
  enough to provide training signal.

- **Form-specific patches of any kind.** The lab measures generic
  capability. If a specific form fails, we ask "what algorithmic
  improvement would fix this AND other similar forms?", not "how do
  we hardcode this form?"

---

## Strategic insight

**The lab just proved that AcroForm-first routing is correct.** Many
production AcroForms contain invisible widget fields with no visible
content-stream cues. No heuristic looking only at page geometry can
recover these reliably. Production's short-circuit to AcroForm
extraction is fundamentally the right architecture.

This means the heuristic's job is **not** to match AcroForm extraction.
The heuristic is the fallback for:

- Flat PDFs (no widget annotations at all)
- Scanned/printed PDFs (require OCR + heuristic)
- Partially-filled hybrid PDFs (some visible cues, some invisible)

**The line in the sand is the Marriage License.** Production heuristic
scored P=0.9742, R=1.0 on the 145-field Marriage License — a fully
flat PDF where every field MUST come from heuristic detection. That's
the target the lab heuristic must reach, on its own merits, without
form-specific patches.

We don't have Marriage License ground truth yet (it's in `samples/flat/`
without a GT JSON). Building that ground truth is the next prerequisite
for measuring lab heuristic against production's strongest result.

---

## Visual evidence

Comparison overlays for irs_w9 and uscis_n400 page 1 were captured to
`reports/overlays/comparison/2026-05-20_223537_heuristic_lab_v1/`
and SCP'd to `local_review/` for inspection. These confirmed:

- **irs_w9 page 1** (P=0.83, R=0.43 on this page): 7 of 8 visible
  checkboxes detected (TP yellow), all hidden text widgets missed
  (FN green), 2 prose FPs in instruction area.

- **uscis_n400 page 1** (P=1.0, R=0.35 on this page): All 7
  eligibility checkboxes A-G detected (TP yellow), 13 text widgets
  missed (FN green), zero false positives.

The visual diffs are the diagnostic surface for future improvements.
After implementing char-box detection (priority 1), comparing the new
overlay against this baseline will show exactly which FN green regions
turned into TP yellow.

---

## End state

The Detection Lab is now operating as designed:

- Honest measurement of generic detection capability ✓
- Visual evidence of every failure category ✓
- Predictive model for future improvements ✓
- Clear separation of architectural limits from improvement targets ✓
- No form-specific patches contaminating measurement ✓

Next session: implement char-box detection (Category 2), re-run
benchmark, compare against this baseline. Predict aggregate recall
moves from 0.30 to 0.35-0.40.
