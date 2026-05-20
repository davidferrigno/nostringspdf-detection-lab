# Detection Lab Backlog

## Overlay renderer improvements

### Two render modes
Add `--mode diagnostic` (current) and `--mode subtle` (thin outlines, low-opacity fills, no labels).
Rationale: heavy fills can mask 2-5px drift. Subtle mode makes misalignment immediately obvious.

### Interactive HTML review
Make `_index.html` clickable — hovering or clicking a field on the overlay shows:
- field type
- bbox coordinates
- source JSON path
- page
- dimensions
Becomes the foundation for human-in-the-loop ground truth review.

## Detection backends (Task 3)

### acroform_self (sanity)
Re-extract via pikepdf, route through benchmark interface, expect precision=1.0 recall=1.0.

### heuristic_baseline
Reimplement core pdfplumber heuristic from main repo (or import as module).
First real measurement against 12C-B-post baseline.

### azure_document_intelligence
Plug in Azure for selective measurement (cost-aware, sparing use).

## Comparison overlay mode
Side-by-side or single-page comparison:
- ground truth = green
- candidate detection = red
- overlap = yellow
Immediate visual scoring intuition.

## Corpus expansion (future)
- Synthetic degradation pipeline: skew, blur, contrast, JPEG noise applied to flat AcroForm flattens
- Scanned PDF corpus
- Photo-of-document corpus
- Additional state forms beyond NJ/CA/NY

## Automation (Level 1+)
Once benchmark runner exists:
- Nightly cron: git pull, run full benchmark, write timestamped report
- Comparison report: today vs N days ago
- Regression alerter
