# NoStringsPDF Detection Lab

Research workstream for building the Document Intelligence Engine.

This lab is architecturally separate from the main NoStringsPDF product.
It exists to:

1. Establish measurable baselines for current detection quality
2. Provide a benchmark/test harness for any detection improvements
3. Build the foundation for OCR, normalization, and layout intelligence
4. Eventually produce production-grade detection improvements

## Core methodology

AcroForm PDFs are pre-labeled training data. Extract metadata to produce
ground truth, flatten to produce test input, run detection, compare.

See ../nostringspdf/detection-lab-kickoff.md for full plan.

## Setup

Requires Ubuntu 24.04, Python 3.12+, and system packages installed via
`scripts/setup-system.sh` (TODO).

```bash
## Folder structure

- `samples/` - Test corpus (AcroForms, flat PDFs, scanned, photos, synthetic)
- `benchmarks/` - Ground truth files and schemas
- `pipelines/` - Detection pipeline modules
- `reports/` - Benchmark output, failure analysis, visualizations
- `docs/` - Methodology, failure taxonomy, promotion pathway
- `scripts/` - Setup and utility scripts

## Status

v0 in progress. Bootstrap complete. Next: Task 1 (corpus collection).
