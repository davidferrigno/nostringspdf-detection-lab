# Lane B Validation — Decision May 21, 2026

## Status

**Two-lane benchmark architecture validated.** Validation derived from
existing production data plus the May 20 Lane A baseline, not via a
fresh Lane B benchmark run.

The lab is no longer existential risk. It moves to background
optimization infrastructure.

---

## Architectural claim under test

> Backends that depend on visible page geometry (e.g. heuristic_lab_v2's
> char-box detection) will score fundamentally differently between
> Lane A (AcroForm widget scoring) and Lane B (flat-PDF usable-fill-zone
> scoring), because Lane A's ground truth encodes form-author editorial
> choices, not visible page geometry. The same algorithm can score
> badly on Lane A while scoring well on Lane B without any code change.

---

## Existing data already confirms this

### Lane A measurement (lab, 30 AcroForm PDFs, May 20, 2026)

- Backend: `heuristic_lab_v1`
- Aggregate: P=0.6834, R=0.3032, F1=0.4201, type accuracy=0.9935
- Source: `reports/latest/lane_a_scorecard.md`
- Failure mode: under-detection. 6 PDFs scored 0/0 because their fields
  exist only as invisible AcroForm widgets with no content-stream cues.
- No PDF scored above F1=0.7.

### Lane B measurement (production, May 5, 2026)

Source: `detection-quality-report.md`, `detection-ground-truth.md`

| PDF | Detector | Detected | Expected | Recall | Precision |
|-----|----------|---------:|---------:|--------|-----------|
| NJ Marriage License | Heuristic | 153 | 145 | ~95-99% | ~90-95% |
| SP-650 | Heuristic | 34 | 34 | ~100% | ~100% |
| Eden Lane Nomination | Heuristic | 21 | 21 | ~100% | ~100% |
| Field Trip Form | Heuristic | 19 | 19 | ~100% | ~100% |

The Marriage License is the canonical flat-PDF case — table-cell dense,
content-stream-rich. The same algorithm that scores P=0.68 R=0.30 on
the Lane A corpus scores ~P=0.95 R=0.95 on this Lane B form.

The delta is exactly what the two-lane architecture predicts.

---

## Why no fresh Lane B benchmark today

1. The architectural claim is already empirically validated by the
   above two measurements.
2. The bootstrap-generated 82-field draft in
   `benchmarks/ground_truth_flat/marriage_license.draft.json` is
   algorithm-proposed candidates, not the authoritative ~145-field
   ground truth established May 5.
3. Rigorous Lane B ground truth construction requires careful hand
   review and is valuable long-term but not on the critical path for
   launch.
4. Bootstrap labels in the draft are visibly corrupted (e.g.
   "PnuanrrrtuenlneletrdDomestic") because the heuristic's label-
   association layer concatenated overlapping text spans. This is a
   bootstrap-tool quality issue, not a detection-quality issue, but
   it confirms the draft is unfit as final GT.

---

## Decision

1. Two-lane architecture is **validated**. No further benchmark work
   needed before launch.
2. Marriage License Lane B ground truth construction is **deferred**
   to background lab work over the coming weeks.
3. Lab work transitions from "existential R&D" to "parallel
   optimization infrastructure."
4. Engineering attention pivots immediately to production UX/UI work.

---

## Deferred work (background lab, no launch dependency)

- Rigorous Lane B GT construction for all 12 flat PDFs in the corpus.
  One PDF per Codex session over the coming weeks. Marriage License
  first since production GT (145 fields) already exists at
  `detection-ground-truth.md` and can be transcribed into the lab
  schema with minimal re-review.
- Lab queue runner (`scripts/lab_queue_runner.py`) to run safe
  deterministic tasks in parallel with UX work.
- Geometry richness probe.
- Quarantined corpus expansion.
- Bootstrap label-concatenation bug fix in
  `extract_flat_pdf_ground_truth.py`.

---

## Next action

Pivot to production repo (`E:\Code\nostringspdf`). UX/UI work begins.

Priority order (per editor-ux-direction.md and current strategy):

1. **Core editor experience** — overlay alignment, drag/resize feel,
   zoom stability, text input, highlight, signature, undo/redo, page
   navigation, jank reduction.
2. **Auto-Detect experience** — the "form lights up" conversion moment.
3. **Paywall + onboarding** — Stripe friction, free vs Pro clarity.

---

## Validation footprint preserved

- `reports/latest/lane_a_scorecard.md` — Lane A baseline locked
- `reports/latest/summary.md` — orchestrator output
- `benchmarks/ground_truth_flat/marriage_license.draft.json` — draft
  GT (82 candidates), kept as starting point for future rigorous GT
- `reports/overlays/ground_truth_flat/marriage_license/page_001.png`
  and `page_002.png` — visual confirmation that --lane B rendering
  works correctly
- `docs/char_box_finding.md` — original architectural finding
- `docs/FIELD_SCHEMA.md` — integration contract

---

## Sign-off

Decided by: Dave Ferrigno
Date: 2026-05-21
Context: ~9:00 AM EST, after ~17 hours of lab work over May 20-21.
Energy budget: ~13 hours remaining today, allocated to UX/UI.
