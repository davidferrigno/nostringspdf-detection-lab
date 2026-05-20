# Provider Evaluation Result — April 21, 2026

**Status:** Prompt A (Detection Engine Evaluation Spike) — COMPLETE
**Decision:** Azure Document Intelligence selected as Pro auto-detect provider for flat PDFs

---

## What was evaluated

A 25-PDF benchmark suite was run through five providers via the harness in `evaluation/spike.py`:

- Google Document AI (Form Parser)
- Azure Document Intelligence (prebuilt-layout)
- AWS Textract (analyze_document, synchronous mode)
- Adobe PDF Services (Extract API)
- Mistral OCR 3 (detect disabled due to hangs; convert tested only)

The 25 PDFs included 14 fillable forms with embedded AcroForm widgets and 11 flat PDFs of varying complexity (government forms, intake forms, multi-page documents, scanned-style layouts).

---

## Results summary

| Provider | Total fields detected | Total cost | PDFs handled successfully |
|---|---|---|---|
| Azure Document Intelligence | 1,422 | $0.39 | 23 / 25 |
| Google Document AI | 1,974 | $2.34 | 25 / 25 (but undercounts fillable by ~57%, wild over-detection on some flat PDFs) |
| AWS Textract | 410 | $0.50 | 10 / 25 (failed on multi-page with `UnsupportedDocumentException`) |
| Adobe PDF Services | 14 (3-PDF smoke test only) | $0.30 | Returns paragraphs and document structure, not form fields — wrong tool for this job |
| Mistral OCR 3 | n/a (detect disabled) | $0.16 (convert only) | n/a |

---

## Decision: Azure wins

Azure Document Intelligence is selected as the production OCR provider for Pro auto-detect on flat PDFs.

**Why Azure:**
- Highest accuracy across the 25-PDF set on flat PDFs (the actual production use case)
- Cheapest at $0.01/page vs Google's $0.03/page (3x cost reduction)
- Most reliable: handled every PDF except 1 oversized file and 1 weirdly-structured form
- Best precision/recall balance: occasional over-detection (which users can delete easily) is preferable to Google's under-detection (which forces manual placement)

**Why not the others:**
- **Google** undercounts real fields significantly on fillable PDFs (would never see this in production since fillable PDFs use widgets, but Google's behavior on flat PDFs was inconsistent — produced 0 fields on some, 1,270 fields on others)
- **Textract** in synchronous mode rejects 60% of multi-page real-world PDFs. Async mode would work but requires substantial additional implementation (job submission, polling, S3 staging)
- **Adobe** is a document-structure extractor, not a form parser. It identifies paragraphs and tables, not fillable fields. Best of class for OCR → Word conversion (Tier 2 future feature)
- **Mistral** detect hangs indefinitely on content-heavy PDFs; coordinates from convert mode are fabricated and unusable for field placement

---

## What this means for production

### Free tier (no change)
- AcroForm widget detection via PyMuPDF / PDF.js — client-side, free, perfect accuracy on fillable PDFs
- Manual field placement for flat PDFs — the conversion engine

### Pro tier — Auto-Detect (the "magic button")
- Backend route: `POST /detect-fields` calls Azure Document Intelligence
- Per-call cost: ~$0.01-0.04 depending on page count
- At scale (10k Pro auto-detects/month, ~3 pages avg): ~$120/month total OCR cost
- Well within Pro tier economics

### Tier 2 features (future)
- **Word conversion** → Adobe PDF Services (best-in-class for structured extraction)
- **Text extraction / scanned PDFs** → Mistral OCR 3 (cheap, reliable for content; not for field placement)
- **Defense-in-depth fallback** → keep Textract integration for edge cases where Azure fails

---

## Required code changes

These changes are queued for the next session, not yet applied:

1. **`evaluation/routing.py`** — change flat-PDF fallback from `google` to `azure`. Update summary printout language.

2. **`main.py`** — when Prompt C (AI integration) is implemented, the `POST /detect-fields` endpoint should call Azure Document Intelligence for the AI path. Existing heuristic detection stays as the free-tier path.

3. **Hardcoded form-specific branches** (`marriage_license`, `eden_nomination`, `field_trip` in `apply_form_specific_cleanup()`) — per Prompt 0, leave in place until Azure path validates correctly on these forms post-Prompt C, then delete.

---

## What was kept (for future use)

- Adobe PDF Services credentials and integration (for Tier 2 Word conversion)
- AWS Textract credentials and integration (defense-in-depth fallback)
- Mistral OCR 3 credentials and integration (Tier 2 text extraction, OCR-to-searchable-PDF)
- Google Document AI credentials (deprovision after one billing cycle if not needed)

All five providers remain integrated in `evaluation/providers/` for future reference and benchmarking. Only Azure becomes the production default.

---

## Files referenced

- `evaluation/spike.py` — the harness that produced these results
- `evaluation/output/` — per-PDF detection JSON, overlay PNGs, summary CSV
- `evaluation/routing.py` — current router (still routes to Google; needs update)
- `NEW_HANDOFF.md` Section 13 — current project state with this decision included
- `NoStringsPDF-Codex-Prompts_Apr_20.md` — Prompt C plan needs Google → Azure references updated before execution

---

## Sign-off

**Prompt A status:** COMPLETE
**Next active prompt:** Prompt B (Supabase + Stripe + auth) per the Codex Prompts roadmap
**Provider decision:** Final, based on data from 25-PDF evaluation
