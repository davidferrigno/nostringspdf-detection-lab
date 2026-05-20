# Heuristic Backend Architecture — Decision Document

**Status:** PROPOSED — review before implementation
**Date drafted:** May 20, 2026 (late evening)
**Decision needed by:** Start of May 21 session
**Cross-check before coding:** ChatGPT

---

## Context

The detection lab has working measurement infrastructure (corpus, ground
truth, IoU scoring, comparison rendering, delta reporting). The v0 baseline
backend `acroform_self` scores 1.0/1.0 across all 30 AcroForm PDFs, which
validates the scoring math but doesn't measure detection quality — it just
re-reads the same widgets ground truth came from.

To measure actual detection quality, the lab needs a real detection backend.
The production NoStringsPDF heuristic exists in the main repo at
`services/heuristic_service.py`. The question is how to make it (or its
algorithm) available to the lab.

---

## Options

### Option A: Copy production heuristic into lab

Copy `heuristic_service.py` and its dependencies from the main repo into
`scripts/backends/heuristic_v1.py` in the lab.

**Pros:**
- Fastest path to first real measurement (a few hours)
- Lab measures *exactly* what production runs

**Cons:**
- Two copies of the same algorithm, drift inevitable
- Hidden dependencies (FastAPI request models, Stripe entitlement checks,
  Azure DI client init) come along uninvited
- Any production heuristic change requires manual port to lab
- Lab can't test ideas that production hasn't already adopted

**Verdict:** Tempting for speed, but the lab becomes a stale shadow of
production within weeks.

---

### Option B: Import main repo as a Python module

Use `pip install -e ../nostringspdf` or sys.path manipulation to import
the production heuristic directly.

**Pros:**
- Single source of truth — production and lab run identical code
- Production changes automatically reflected in lab measurements
- No copy-paste discipline required

**Cons:**
- Lab tightly coupled to main repo's directory structure
- Main repo refactor breaks lab tests silently
- VPS deployment requires main repo cloned alongside lab (extra ~150 MB,
  more secrets, more attack surface)
- Lab can't safely experiment with algorithm changes — modifying the
  import means modifying production
- Confuses the mental model: "lab measurement" and "production change"
  become indistinguishable

**Verdict:** Sounds clean but breaks the lab's core purpose. The lab
EXISTS to test ideas independently. Importing production undoes that.

---

### Option C: Reimplement clean lab baseline (LEAN)

Build `scripts/backends/heuristic_lab_v1.py` as a fresh implementation
of the same algorithm, owned entirely by the lab.

**Pros:**
- Lab tests ideas independently from production
- Algorithm changes in lab don't affect production
- Algorithm changes in production don't affect lab measurement stability
- Clean abstraction surface — only the `detect(pdf_path) -> list[Field]`
  contract matters
- Forces a deliberate "what is the heuristic, really?" understanding,
  which exposes hidden assumptions in the production version
- Bootstrap point for future variants: heuristic_lab_v2 with tuning,
  heuristic_lab_v3 with ML-augmented ranking, etc.

**Cons:**
- More work upfront (~500-800 lines vs ~100 lines for Option A)
- Two implementations to keep functionally aligned
- Risk of subtle divergence if not careful

**Verdict:** This is the right architectural choice. The cost is real
but pays off every time we want to test a detection improvement.

---

## Recommendation

**Option C.** Reimplement clean lab baseline.

The 4-8 hour cost of building this once is recovered the first time we
want to test a detection idea without touching production. That moment
comes within days, not months.

The "two implementations drifting" risk is mitigated by:
1. Both implementations measured against the same ground truth — any
   divergence shows up in benchmark scores
2. The lab implementation is documented as the *reference* — production
   ports tested improvements from lab, not vice versa
3. Eventually production replaces its heuristic with a port of the
   lab implementation (once lab variants prove themselves)

---

## What the lab heuristic needs to do

Read the production heuristic and document the core algorithm before
implementing it in the lab. Production heuristic responsibilities:

1. **Read PDF content streams** (pdfplumber)
2. **Detect underlines** — horizontal lines below visible text labels
   that suggest "fill in here"
3. **Detect labeled-pair fields** — text like "Name: _______" where
   the underline is the field zone
4. **Detect checkbox squares** — small square outlines, typically 8-15pt
5. **Cluster fields by row** — handle multi-column forms
6. **Classify field types** — text vs checkbox vs (future: radio, choice)
7. **Output bounding boxes** in PDF points, top-left origin

The lab version should match this contract exactly. Field schema:
```python
{
    "id": str,              # auto-generated, format: "d{N}"
    "page": int,            # 1-indexed
    "type": str,            # text | checkbox | radio | choice | signature
    "bbox": [x, y, w, h],   # top-left origin, PDF points
    "label": str | None,    # optional, useful for debugging
}
```

---

## Implementation plan for tomorrow

### Phase 1: Source reading (45 min)

Read the main repo's heuristic implementation. Specifically:
- `services/heuristic_service.py`
- `services/pdf_processing.py` (or wherever pdfplumber wraps)
- Any helper modules called by heuristic_service

Document on paper:
- What does each function do?
- What's the call graph?
- Where are the magic numbers? (thresholds, sizes, etc.)
- What state does it carry?

### Phase 2: Skeleton (30 min)

Write `scripts/backends/heuristic_lab_v1.py` with:
- `def detect(pdf_path: Path) -> list[Field]:` signature
- Empty function body returning `[]`
- Register in `BACKENDS` dict in `run_benchmark.py`
- Run benchmark — expect 0/0/3047, P=0, R=0 (no detection yet)
- Verify the registration plumbing works

### Phase 3: Underline detection (60 min)

Implement underline detection using pdfplumber:
- Find all horizontal lines on each page
- Filter by length (>20pt typical), thinness (<1pt)
- Cluster nearby underlines into single fields if appropriate
- Output Field objects with type="text"

Run benchmark. Expect partial recall on text-heavy forms.

### Phase 4: Checkbox detection (45 min)

Implement checkbox detection:
- Find small square outlines (rectangles where w ≈ h, 8-15pt)
- Filter out actual content squares (table borders, etc.) by isolation
- Output Field objects with type="checkbox"

Run benchmark. Expect significant recall improvement on checkbox-heavy
forms.

### Phase 5: Labeled-pair refinement (60-90 min)

Improve text field detection by:
- Reading text on the page (pdfplumber characters)
- Detecting "Label:" patterns adjacent to underlines
- Merging close underlines into single labeled fields
- Improving bbox precision

Run benchmark. This is the phase that should bring the lab heuristic
closest to the production heuristic's quality.

### Phase 6: Compare and commit (30 min)

Run:
```bash
python scripts/run_benchmark.py
python scripts/compare_to_baseline.py
python scripts/render_detection_comparison.py
```

Look at:
- Aggregate precision/recall vs acroform_self baseline
- Per-PDF deltas — which PDFs are hardest?
- Visual diffs — what kinds of mistakes are being made?

Compare to historical baseline at `docs/legacy/measurements/12C-B-post.md`:
- Marriage License: production heuristic was P=0.9742, R=1.0
- Eden nomination: P=1.0, R=1.0
- SP-650: P=1.0, R=1.0

Lab heuristic doesn't need to match production numbers today. But these
form the reference: if lab heuristic is significantly different from
production on these PDFs, that's diagnostic signal.

---

## Total estimated time

**~4-5 hours of focused work** for Phases 1-6.

This is realistic for a morning session if started by 9 AM. By lunch we
should have a first real measurement. Afternoon is for iteration and
investigation of specific failures.

---

## What we should NOT do tomorrow

1. **Don't import from main repo** (Option B). Even as a quick start.
   The temptation will be strong; resist it.

2. **Don't try to match production exactly on day one.** The lab version
   starts simple and improves through measurement.

3. **Don't add Azure or OCR backends yet.** One backend, one measurement,
   one baseline of comparison. Add more later.

4. **Don't start synthetic degradation pipeline.** Separate workstream.

5. **Don't refactor the existing lab scripts.** They work. Leave them.

6. **Don't optimize the heuristic prematurely.** First get to a working
   measurement. THEN iterate.

---

## Acceptance criteria for end of tomorrow's session

The session is successful if at end of day we have:

1. `scripts/backends/heuristic_lab_v1.py` exists and is registered
2. Benchmark runs against it without errors
3. Scorecard shows non-zero precision/recall (not just zeros)
4. Comparison overlay renderer produces a useful visual diff for at
   least one PDF
5. Either:
   - The numbers are reasonable (within 0.1 of historical baseline on
     forms where production heuristic was tested), OR
   - The numbers are bad but the reasons are visible in the comparison
     overlays — i.e. we KNOW where the next improvement should focus

The session is NOT a failure if the numbers are bad. The lab's job is to
measure and visualize. Bad numbers with clear causes are a productive
day.

---

## Pre-session checklist (tomorrow morning)

Before starting:

- [ ] `git pull` on all three machines
- [ ] Cross-check Option C with ChatGPT — does it agree?
- [ ] Read the main repo heuristic implementation
- [ ] Look at the comparison overlay renderer output for irs_w9
      (to remember what good visual output looks like)
- [ ] Coffee
- [ ] Decide: 4-6 hour focused block, or split across multiple shorter
      sessions?

---

## End of document

If anything in here is unclear or feels wrong, that's the signal to
discuss before implementing. This document exists to make tomorrow's
work easier, not to lock in a decision that should be revisited.
