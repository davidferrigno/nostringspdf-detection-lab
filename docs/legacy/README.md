# Legacy Documentation Archive

This folder preserves analysis documents from the main NoStringsPDF
repository (`E:\Code\nostringspdf\`) that document detection failure
modes, ground truth methodology, and measurement infrastructure
developed between April–May 2026.

These docs are **read-only references**. They are preserved here so the
Detection Lab has full context for what was tried, what failed, and what
specific failure modes we are still trying to resolve.

**Authoritative summary:** see `../../samples/KNOWN_ISSUES.md` for a
distilled, actionable summary of every documented failure mode against
specific PDFs in the v0 corpus.

---

## Documents

### `detection-ground-truth.md`
Manual field counts for: NJ Marriage License (REG-77), sp-650, Eden Lane
Nomination, Field Trip Form, I-9. Source: David Ferrigno, 2026-05-05.
Includes per-page text/checkbox breakdowns and notes on observed iOS
detection misses.

### `detection-measurement-guide.md`
The IoU-based measurement methodology used by `scripts/measure_detection.py`
in the main repo. Defines:
- Ground truth JSON schema (`{pdf, page_count, labeled_at, review_status, fields: [...]}`)
- `review_status` enum (`draft` vs `human_reviewed`)
- Scoring rules (IoU threshold 0.5, page-aware, greedy by highest IoU)
- Metrics: TP, FP, FN, type mismatches, precision, recall
- Bootstrap workflow (heuristic-derived draft labels for regression
  tripwires)

**The Detection Lab benchmark runner should follow this exact schema and
methodology** so historical baselines remain comparable.

### `detection-quality-report.md`
The 2026-05-05 measurement against the Slice 12C-A corpus
(Marriage License, sp-650, Eden Lane, Field Trip, I-9). Contains:
- Raw measurement output (JSONL)
- Per-PDF summary table with detected counts, expected counts, recall, precision
- Failure mode analysis (over-detection, under-detection, wrong field type,
  geometry/alignment, grid/table confusion)
- Per-PDF detector recommendation (heuristic vs Azure vs AcroForm)
- Overall strategic recommendation: **improve heuristic, do not switch to
  Azure-first** because Azure under-detects text fields catastrophically

### `EVALUATION_RESULT_Apr_21.md`
The provider comparison that produced the Azure-as-Pro-detector decision.
Benchmarks Azure Document Intelligence, Google Document AI, AWS Textract,
Adobe PDF Services, and Mistral OCR 3 across a 25-PDF suite. **Note:**
This decision was later contextualized by `detection-quality-report.md`,
which showed Azure also under-detects on the specific problem PDFs in our
corpus. The current strategic position is heuristic-first with Azure as
an optional augmentation, not a replacement.

### `FIELD_RENDERING_RULE.md`
Architectural constraint (May 18, 2026): system fields (AcroForm,
template-matched, automatically detected) and manual user-created fields
**must use separate rendering, interaction, and state-management logic**.
This is the constraint that gates how the lab's detection output is
allowed to interact with the editor's field rendering. Established after
a regression (commit `ba55fee`) coupled the two render paths and
destroyed AcroForm document readability.

### `measurements/`
Five historical measurement runs against the Slice 12C-A corpus.

- `baseline-2026-05-06.md` — initial post-implementation baseline
- `12C-B-pre.md` — before Slice 12C-B refinements
- `12C-B-post.md` — after Slice 12C-B refinements (best result: marriage
  license precision 0.9742, recall 1.0)
- `12C-B-verify.md` — verification run, identical to 12C-B-post
- `post-batch1.md` — intermediate measurement during 12C-B work

These markdown tables are the historical regression baselines. New
Detection Lab benchmark runs should be diff-able against these to
demonstrate improvement (or detect regression).

---

## What these are NOT

- They are not strategic direction documents. For strategy, see the main
  repo's `product-strategy.md` and `ux-paradigm-shift.md`.
- They are not architecture documents. For architecture, see the main
  repo's `docs/NoStringsPDF-Architecture-V1.md`.
- They are not authoritative ground truth. Numbers in
  `detection-ground-truth.md` are manual counts that may need re-verification.

For everything else, refer to `../../samples/KNOWN_ISSUES.md`.
