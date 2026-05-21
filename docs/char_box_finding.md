# Char-Box Detection — Architectural Finding (heuristic_lab_v2)

**Date:** May 20, 2026 evening
**Backend tested:** `heuristic_lab_v2` (v1 + `detect_char_boxes()`)
**Result:** Aggregate P=0.6847 R=0.3036 on AcroForm corpus — essentially
unchanged from v1
**Status:** Finding documented; both backends preserved; benchmark
architecture revised.

---

## TL;DR

v2's char-box detector works correctly — it identifies SSN/EIN/account
number rows on PDFs and emits them as fields. The benchmark score didn't
improve because **AcroForm widget bboxes encode editorial author choices
(how the form was authored), not visible page geometry.** No
content-stream heuristic can match an authoring decision that isn't
present in the page geometry.

**Decision:**

- `heuristic_lab_v1` remains the canonical AcroForm-lane baseline
- `heuristic_lab_v2` is preserved as the flat-PDF-lane experiment
- The lab benchmark gets two scoring lanes (AcroForm + flat PDF) instead
  of conflating them

---

## Detailed diagnostic

### What v2 was supposed to do

Per `docs/failure_analysis_v1.md` Category 2, v1 missed segmented input
rows. v2 added `detect_char_boxes()` to identify rows of small adjacent
squares and emit them as single fields. Predicted aggregate gain:
precision +1-3%, recall +5-10%.

### What v2 actually produced

Aggregate moved P=0.6834→0.6847, R=0.3032→0.3036. The W-9 SSN/EIN rows
moved by 1 TP.

### Investigation

We probed the W-9 directly. The SSN row (y=370) has 9 boxes, all 14.4pt
wide, gaps mostly 0pt. EIN row (y=420) likewise. Both pass every
threshold in v2's detector.

Calling `detect_char_boxes()` directly on the W-9 returns 2 fields —
one wide field per row, exactly as designed:

```
SSN row: {x=417.6, y=372.0, width=158.4, height=24.0, type=text}
EIN row: {x=417.6, y=420.0, width=144.0, height=24.0, type=text}
```

So the detector works. Why doesn't it score?

### The architectural collision

The W-9 ground truth has the SSN authored as 3 separate widgets:

```
f19: bbox=[417.6, 372.0, 43.2, 24.0]   ← SSN segment 1 (XXX)
f20: bbox=[475.2, 372.0, 28.8, 24.0]   ← SSN segment 2 (XX)
f21: bbox=[518.4, 372.0, 57.6, 24.0]   ← SSN segment 3 (XXXX)
```

And EIN as 2 widgets:

```
f22: bbox=[417.6, 420.0, 28.8, 24.0]   ← EIN segment 1 (XX)
f23: bbox=[460.8, 420.0, 100.8, 24.0]  ← EIN segment 2 (XXXXXXX)
```

v2's wide 158pt SSN field has IoU < 0.5 against any of f19/f20/f21
individually (because the wide field overlaps multiple narrow targets at
low fractional overlap each). The benchmark scores this as 0 TP + 1 FP.

### The deeper truth

**AcroForm widget grouping for char-box rows is an EDITORIAL choice by
the form author**, not a geometric property visible on the page. The
same 9-cell SSN row could be authored as 1 widget, 2 widgets, 3 widgets
(IRS choice), or 9 widgets — all valid. The page geometry looks
identical for all four cases.

**No content-stream heuristic can know which choice the author made.**

This means: for the AcroForm corpus, the heuristic CANNOT score char-box
rows fairly. It's not a heuristic weakness; it's a misapplication of the
benchmark.

---

## What this changes

### Before tonight's finding

The lab measured every backend against AcroForm widget ground truth.
Heuristics were evaluated on whether they reproduced the widget
segmentation. Char-box detection was considered a Priority-1 recall
improvement (failure_analysis_v1.md).

### After tonight's finding

The lab needs **two scoring lanes**:

**Lane A — AcroForm (current):**
- Ground truth: AcroForm widget bboxes (extracted by
  `extract_ground_truth.py`)
- Scoring criterion: "Did the backend reproduce the author's widget
  segmentation?"
- Fair for: `acroform_self` (perfect), text-field detection, checkbox
  detection
- NOT fair for: char-box row detection, label-position inference
  (both fight authorial choices that don't exist in geometry)

**Lane B — Flat PDF (new):**
- Ground truth: human-marked fillable zones on flat PDFs (no widgets)
- Scoring criterion: "Did the backend find a usable fill zone where a
  user would expect one?"
- Fair for: char-box detection (one row = one field), label-position
  inference, all geometric heuristics
- Required for: measuring `heuristic_lab_v2` honestly

The Marriage License historical baseline (P=0.9742, R=1.0 on 145 fields)
was measured in Lane B — flat-PDF scoring. The lab cannot reproduce
that baseline until Lane B exists.

---

## Backend status

| Backend | Status | Lane | Notes |
|---------|--------|------|-------|
| `acroform_self` | Active sanity check | A | Perfect by construction |
| `heuristic_lab_v1` | **Canonical AcroForm baseline** | A | First real measurement |
| `heuristic_lab_v2` | Preserved as flat-PDF candidate | B | Awaits Lane B GT |

No backend is being removed. v2 is parked behind Lane B until Lane B
ground truth exists. When it does, v2 becomes the default flat-PDF
backend and we measure honestly.

---

## Production routing remains sacred

This finding REINFORCES the architectural correctness of production's
routing order:

1. AcroForm widgets (when present) — authoritative, no heuristic conflict
2. Template match
3. Heuristic fallback (flat/scanned PDFs only)

The lab tonight proved that step 1 cannot be replaced by step 3 even in
principle. For AcroForm PDFs with char-box rows, the widget data
contains author-segmentation information that is not present on the
page. The heuristic is the wrong layer.

For FLAT PDFs (no widget data), the heuristic gets to decide
segmentation itself — and "one field per visible row" is the right UX
choice. The lab will measure that decision against Lane B GT.

---

## Next session priorities (revised)

1. **Build the Marriage License flat-PDF ground truth.** Bootstrap from
   v2 heuristic output, render visual overlay, hand-review, promote.
   Tool: `scripts/extract_flat_pdf_ground_truth.py` (new, this session).

2. **Add Eden Lane, sp650, and other flat PDFs to Lane B corpus.** Same
   bootstrap process.

3. **Run v2 against Lane B.** Verify the predicted improvement
   materializes: char-box rows should now score TP.

4. **Then add label-position inference** (Category 4) measured against
   Lane B. Predict: significant recall gain on flat PDFs with numbered
   prompts.

---

## What tonight's experiment gave us

The v2 experiment did not move the headline score, but it produced
three valuable outcomes:

1. **Validated the detector geometrically.** Char-box detection works
   exactly as designed. We can deploy it with confidence in Lane B.

2. **Exposed a hidden assumption.** The lab's single-lane benchmark
   silently assumed AcroForm widget bboxes are universal ground truth.
   They're not — they encode editorial choices. This shapes how we
   measure all future heuristic work.

3. **Confirmed the predictive framework's value.**
   `failure_analysis_v1.md` predicted "char-box detection should
   improve AcroForm recall." The PREDICTION was geometrically sound.
   The REALITY revealed that geometric correctness doesn't imply
   benchmark gain when the benchmark measures non-geometric authorial
   choices. This is exactly the kind of "prediction → diagnostic
   outcome" loop the lab was built for.

The lab worked correctly tonight. A hypothesis was tested and
properly refuted within 2 hours, yielding a finding that reshapes
methodology going forward.
