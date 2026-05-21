# Overnight Status Report

Started: Thu May 21 02:42:56 AM UTC 2026
Hostname: detection-lab
Branch at start: lab/automation-runner
HEAD at start: f12aac7

## Pre-flight smoke test
Started: Thu May 21 02:42:56 AM UTC 2026
```
$ python scripts/test_lab_smoke.py
```
```
PASS imports
PASS backend_metadata
PASS schema_versions
PASS acroform_self_w9
PASS lane_mismatch_exit
```
Result: COMPLETED at Thu May 21 02:42:56 AM UTC 2026

## Detection lab dry run
Started: Thu May 21 02:42:56 AM UTC 2026
```
$ python scripts/run_detection_lab.py --dry-run
```
```
Detection lab dry run
1. Verify corpus integrity: python scripts/verify_corpus.py
Lane A (AcroForm widget scoring):
  - RUN python scripts/run_benchmark.py --backend acroform_self --lane A
  - RUN python scripts/run_benchmark.py --backend heuristic_lab_v1 --lane A
Lane B (flat-PDF usable-fill-zone scoring):
  - SKIP heuristic_lab_v1: no reviewed flat-PDF GT JSON files
  - SKIP heuristic_lab_v2: no reviewed flat-PDF GT JSON files
Reports: reports/latest/summary.md, lane scorecards, regressions.md
```
Result: COMPLETED at Thu May 21 02:42:56 AM UTC 2026

## Full detection lab run (Lane A)
Started: Thu May 21 02:42:56 AM UTC 2026
```
$ python scripts/run_detection_lab.py --all
```
```
$ /home/lab/detection-lab/.venv/bin/python scripts/verify_corpus.py
========================================================================
verify_corpus.py v1
Timestamp: 2026-05-21T02:42:57+00:00
========================================================================

Manifests loaded:
  acroform manifest: 30 entries
  flat manifest:     12 entries

--- Verifying AcroForm PDFs ---

--- Verifying flat PDFs ---

--- Cross-checking ground truth ---
  AcroForm manifest entries: 30
  Ground truth files found: 30
  Manifest PDFs without GT: 0
  GT files without manifest: 0
  Field count mismatches: 0

========================================================================
SUMMARY
========================================================================
AcroForm PDFs verified: 30
Flat PDFs verified: 12
Total errors: 0
Total warnings: 0

Report written: reports/integrity/2026-05-21_024257_verify.json

PASS: corpus integrity verified.
$ /home/lab/detection-lab/.venv/bin/python scripts/run_benchmark.py --backend acroform_self --lane A
========================================================================
run_benchmark.py v1.1
Backend: acroform_self
Lane: A
Schema version: 1.0
IoU threshold: 0.5
Manifest: /home/lab/detection-lab/samples/acroforms/manifest.json
Ground truth dir: /home/lab/detection-lab/benchmarks/ground_truth
PDFs to benchmark: 30
Run ID: 2026-05-21_024257_acroform_self_laneA
========================================================================
Benchmarking ca_dmv_reg256                  ... P=1.0000 R=1.0000 F1=1.0000 (TP=  72 FP=  0 FN=  0) [PERFECT] 0.02s
Benchmarking irs_1040                       ... P=1.0000 R=1.0000 F1=1.0000 (TP= 199 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking irs_1040sb                     ... P=1.0000 R=1.0000 F1=1.0000 (TP=  72 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking irs_2848                       ... P=1.0000 R=1.0000 F1=1.0000 (TP=  92 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking irs_4506t                      ... P=1.0000 R=1.0000 F1=1.0000 (TP=  29 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking irs_8821                       ... P=1.0000 R=1.0000 F1=1.0000 (TP=  45 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking irs_w4                         ... P=1.0000 R=1.0000 F1=1.0000 (TP=  48 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking irs_w9                         ... P=1.0000 R=1.0000 F1=1.0000 (TP=  23 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_71061                    ... P=1.0000 R=1.0000 F1=1.0000 (TP=   6 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_ba_51                    ... P=1.0000 R=1.0000 F1=1.0000 (TP=  43 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_ba_62                    ... P=1.0000 R=1.0000 F1=1.0000 (TP=   9 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking local_f1099nec                 ... P=1.0000 R=1.0000 F1=1.0000 (TP=  80 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_njw4                     ... P=1.0000 R=1.0000 F1=1.0000 (TP=  18 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_ppb_11_01_23             ... P=1.0000 R=1.0000 F1=1.0000 (TP=  66 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_ppb_7_2_2025             ... P=1.0000 R=1.0000 F1=1.0000 (TP=  54 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_sp_066                   ... P=1.0000 R=1.0000 F1=1.0000 (TP=  25 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_ss_5                     ... P=1.0000 R=1.0000 F1=1.0000 (TP=  70 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking local_sts_033                  ... P=1.0000 R=1.0000 F1=1.0000 (TP=  86 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking nj_mvc_ba49                    ... P=1.0000 R=1.0000 F1=1.0000 (TP=  58 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking ny_dtf_it201                   ... P=1.0000 R=1.0000 F1=1.0000 (TP= 233 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking ssa_1696                       ... P=1.0000 R=1.0000 F1=1.0000 (TP=  91 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking ssa_521                        ... P=1.0000 R=1.0000 F1=1.0000 (TP=  38 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking uscis_g1145                    ... P=1.0000 R=1.0000 F1=1.0000 (TP=   6 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking uscis_i9                       ... P=1.0000 R=1.0000 F1=1.0000 (TP= 130 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking uscis_i90                      ... P=1.0000 R=1.0000 F1=1.0000 (TP= 195 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking uscis_n400                     ... P=1.0000 R=1.0000 F1=1.0000 (TP= 440 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking uscourts_ao240                 ... P=1.0000 R=1.0000 F1=1.0000 (TP=  34 FP=  0 FN=  0) [PERFECT] 0.00s
Benchmarking uscourts_b101                  ... P=1.0000 R=1.0000 F1=1.0000 (TP= 246 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking va_1010ez                      ... P=1.0000 R=1.0000 F1=1.0000 (TP= 151 FP=  0 FN=  0) [PERFECT] 0.01s
Benchmarking va_21526ez                     ... P=1.0000 R=1.0000 F1=1.0000 (TP= 388 FP=  0 FN=  0) [PERFECT] 0.01s
========================================================================
PDFs processed: 30
PDFs perfect (P=1.0, R=1.0): 30
PDFs with errors: 0
Aggregate precision: 1.0000
Aggregate recall:    1.0000
Total duration: 0.23s

Reports written to: reports/benchmarks/2026-05-21_024257_acroform_self_laneA
$ /home/lab/detection-lab/.venv/bin/python scripts/run_benchmark.py --backend heuristic_lab_v1 --lane A
========================================================================
run_benchmark.py v1.1
Backend: heuristic_lab_v1
Lane: A
Schema version: 1.0
IoU threshold: 0.5
Manifest: /home/lab/detection-lab/samples/acroforms/manifest.json
Ground truth dir: /home/lab/detection-lab/benchmarks/ground_truth
PDFs to benchmark: 30
Run ID: 2026-05-21_024257_heuristic_lab_v1_laneA
========================================================================
Benchmarking ca_dmv_reg256                  ... P=0.8929 R=0.3472 F1=0.5000 (TP=  25 FP=  3 FN= 47) [low-recall] 0.21s
Benchmarking irs_1040                       ... P=0.6887 R=0.3668 F1=0.4787 (TP=  73 FP= 33 FN=126) [low-recall] 0.43s
Benchmarking irs_1040sb                     ... P=0.8000 R=0.6111 F1=0.6929 (TP=  44 FP= 11 FN= 28) [OK] 0.14s
Benchmarking irs_2848                       ... P=0.6290 R=0.4239 F1=0.5065 (TP=  39 FP= 23 FN= 53) [low-recall] 0.22s
Benchmarking irs_4506t                      ... P=0.4444 R=0.2759 F1=0.3404 (TP=   8 FP= 10 FN= 21) [low-recall] 0.35s
Benchmarking irs_8821                       ... P=0.7667 R=0.5111 F1=0.6133 (TP=  23 FP=  7 FN= 22) [OK] 0.12s
Benchmarking irs_w4                         ... P=0.4167 R=0.5208 F1=0.4630 (TP=  25 FP= 35 FN= 23) [OK] 0.72s
Benchmarking irs_w9                         ... P=0.3704 R=0.4348 F1=0.4000 (TP=  10 FP= 17 FN= 13) [low-recall] 0.70s
Benchmarking local_71061                    ... P=0.0000 R=0.0000 F1=0.0000 (TP=   0 FP=  5 FN=  6) [low-recall] 0.06s
Benchmarking local_ba_51                    ... P=0.0000 R=0.0000 F1=0.0000 (TP=   0 FP=  4 FN= 43) [low-recall] 0.14s
Benchmarking local_ba_62                    ... P=0.0000 R=0.0000 F1=0.0000 (TP=   0 FP=  0 FN=  9) [low-recall] 0.05s
Benchmarking local_f1099nec                 ... P=0.4737 R=0.2250 F1=0.3051 (TP=  18 FP= 20 FN= 62) [low-recall] 0.24s
Benchmarking local_njw4                     ... P=0.1667 R=0.2778 F1=0.2083 (TP=   5 FP= 25 FN= 13) [low-recall] 0.30s
Benchmarking local_ppb_11_01_23             ... P=0.0000 R=0.0000 F1=0.0000 (TP=   0 FP=  2 FN= 66) [low-recall] 0.15s
Benchmarking local_ppb_7_2_2025             ... P=0.0000 R=0.0000 F1=0.0000 (TP=   0 FP=  4 FN= 54) [low-recall] 0.16s
Benchmarking local_sp_066                   ... P=0.3333 R=0.0400 F1=0.0714 (TP=   1 FP=  2 FN= 24) [low-recall] 0.10s
Benchmarking local_ss_5                     ... P=0.5686 R=0.4143 F1=0.4793 (TP=  29 FP= 22 FN= 41) [low-recall] 0.34s
Benchmarking local_sts_033                  ... P=0.9057 R=0.5581 F1=0.6906 (TP=  48 FP=  5 FN= 38) [OK] 0.25s
Benchmarking nj_mvc_ba49                    ... P=0.0000 R=0.0000 F1=0.0000 (TP=   0 FP=  0 FN= 58) [low-recall] 0.17s
Benchmarking ny_dtf_it201                   ... P=0.4268 R=0.1502 F1=0.2222 (TP=  35 FP= 47 FN=198) [low-recall] 0.54s
Benchmarking ssa_1696                       ... P=0.6038 R=0.3516 F1=0.4444 (TP=  32 FP= 21 FN= 59) [low-recall] 0.40s
Benchmarking ssa_521                        ... P=0.5000 R=0.3421 F1=0.4063 (TP=  13 FP= 13 FN= 25) [low-recall] 0.15s
Benchmarking uscis_g1145                    ... P=0.0000 R=0.0000 F1=0.0000 (TP=   0 FP=  1 FN=  6) [low-recall] 0.05s
Benchmarking uscis_i9                       ... P=0.4545 R=0.0385 F1=0.0709 (TP=   5 FP=  6 FN=125) [low-recall] 0.50s
Benchmarking uscis_i90                      ... P=0.8351 R=0.4154 F1=0.5548 (TP=  81 FP= 16 FN=114) [low-recall] 0.40s
Benchmarking uscis_n400                     ... P=0.9803 R=0.4523 F1=0.6190 (TP= 199 FP=  4 FN=241) [low-recall] 0.88s
Benchmarking uscourts_ao240                 ... P=0.8000 R=0.2353 F1=0.3636 (TP=   8 FP=  2 FN= 26) [low-recall] 0.06s
Benchmarking uscourts_b101                  ... P=0.3186 R=0.1463 F1=0.2006 (TP=  36 FP= 77 FN=210) [low-recall] 1.05s
Benchmarking va_1010ez                      ... P=0.9610 R=0.4901 F1=0.6491 (TP=  74 FP=  3 FN= 77) [low-recall] 0.59s
Benchmarking va_21526ez                     ... P=0.9029 R=0.2397 F1=0.3788 (TP=  93 FP= 10 FN=295) [low-recall] 1.24s
========================================================================
PDFs processed: 30
PDFs perfect (P=1.0, R=1.0): 0
PDFs with errors: 0
Aggregate precision: 0.6834
Aggregate recall:    0.3032
Total duration: 10.75s

Reports written to: reports/benchmarks/2026-05-21_024257_heuristic_lab_v1_laneA
WARNING: SKIP heuristic_lab_v1: no reviewed flat-PDF GT JSON files
WARNING: SKIP heuristic_lab_v2: no reviewed flat-PDF GT JSON files
$ /home/lab/detection-lab/.venv/bin/python scripts/compare_to_baseline.py --baseline 2026-05-21_024257_acroform_self_laneA --candidate 2026-05-21_024257_heuristic_lab_v1_laneA
========================================================================
compare_to_baseline.py
Baseline:  reports/benchmarks/2026-05-21_024257_acroform_self_laneA
Candidate: reports/benchmarks/2026-05-21_024257_heuristic_lab_v1_laneA
Significance threshold: 0.01
========================================================================

--- Aggregate ---
Precision: 1.0000 -> 0.6834 (-0.3166)
Recall:    1.0000 -> 0.3032 (-0.6968)
F1:        1.0000 -> 0.4201 (-0.5799)

--- Classification ---
  UNCHANGED    :   0
  IMPROVED     :   0
  REGRESSED    :  30  <-- REGRESSIONS
  MIXED        :   0
  NEW_ERROR    :   0
  ERROR_FIXED  :   0
  BOTH_ERROR   :   0
  BOTH_NA      :   0

--- REGRESSED details ---
  ca_dmv_reg256                   ΔP=-0.1071  ΔR=-0.6528
  irs_1040                        ΔP=-0.3113  ΔR=-0.6332
  irs_1040sb                      ΔP=-0.2000  ΔR=-0.3889
  irs_2848                        ΔP=-0.3710  ΔR=-0.5761
  irs_4506t                       ΔP=-0.5556  ΔR=-0.7241
  irs_8821                        ΔP=-0.2333  ΔR=-0.4889
  irs_w4                          ΔP=-0.5833  ΔR=-0.4792
  irs_w9                          ΔP=-0.6296  ΔR=-0.5652
  local_71061                     ΔP=-1.0000  ΔR=-1.0000
  local_ba_51                     ΔP=-1.0000  ΔR=-1.0000
  local_ba_62                     ΔP=-1.0000  ΔR=-1.0000
  local_f1099nec                  ΔP=-0.5263  ΔR=-0.7750
  local_njw4                      ΔP=-0.8333  ΔR=-0.7222
  local_ppb_11_01_23              ΔP=-1.0000  ΔR=-1.0000
  local_ppb_7_2_2025              ΔP=-1.0000  ΔR=-1.0000
  local_sp_066                    ΔP=-0.6667  ΔR=-0.9600
  local_ss_5                      ΔP=-0.4314  ΔR=-0.5857
  local_sts_033                   ΔP=-0.0943  ΔR=-0.4419
  nj_mvc_ba49                     ΔP=-1.0000  ΔR=-1.0000
  ny_dtf_it201                    ΔP=-0.5732  ΔR=-0.8498
  ... and 10 more

Reports written: reports/comparisons/2026-05-21_024308_vs_baseline/
  - comparison.json
  - comparison.csv
  - comparison.md
Latest summary: reports/latest/summary.md
```
Result: COMPLETED at Thu May 21 02:43:08 AM UTC 2026

## Render flat-PDF GT draft overlays
Started: Thu May 21 02:43:08 AM UTC 2026
```
$ python scripts/render_ground_truth_overlays.py --gt-dir benchmarks/ground_truth_flat --output-dir reports/overlays/ground_truth_flat 2>&1 || echo 'render_ground_truth_overlays.py does not yet support --gt-dir argument; skipped — to be added tomorrow'
```
```
usage: render_ground_truth_overlays.py [-h] [--dry-run] [--pdf PDF]
                                       [--dpi DPI]
render_ground_truth_overlays.py: error: unrecognized arguments: --gt-dir benchmarks/ground_truth_flat --output-dir reports/overlays/ground_truth_flat
render_ground_truth_overlays.py does not yet support --gt-dir argument; skipped — to be added tomorrow
```
Result: COMPLETED at Thu May 21 02:43:08 AM UTC 2026

## Geometry richness probe
Started: Thu May 21 02:43:08 AM UTC 2026
```
$ python scripts/probe_geometry_richness.py 2>&1 || echo 'probe_geometry_richness.py not available yet; skipped'
```
```
python: can't open file '/home/lab/detection-lab/scripts/probe_geometry_richness.py': [Errno 2] No such file or directory
probe_geometry_richness.py not available yet; skipped
```
Result: COMPLETED at Thu May 21 02:43:08 AM UTC 2026

## Corpus expansion
Started: Thu May 21 02:43:08 AM UTC 2026
```
$ python scripts/discover_public_pdfs.py 2>&1 || echo 'discover_public_pdfs.py not available yet; skipped'
```
```
python: can't open file '/home/lab/detection-lab/scripts/discover_public_pdfs.py': [Errno 2] No such file or directory
discover_public_pdfs.py not available yet; skipped
```
Result: COMPLETED at Thu May 21 02:43:08 AM UTC 2026

## Final git state
```
## lab/automation-runner...origin/lab/automation-runner
 M reports/latest/lane_a_scorecard.md
 M reports/latest/regressions.md
 M reports/latest/summary.md
?? overnight_runner.sh
?? reports/overnight_status.md
```

## Final commit log
```
f12aac7 chore(lab): refresh latest automation reports
68a1501 M8: test: add test_lab_smoke.py
2ce7fb8 M7: docs: detection_lab_workflow.md
6234dda M6: feat(lab): run_detection_lab.py orchestrator
1e85186 M5: feat(lab): generate flat-PDF GT drafts (needs_review)
4251d61 M4: feat(lab): run_benchmark.py supports --lane flag
b7af77a M3: feat(lab): backend_registry now declares lanes per backend
1da5b39 M2: feat(lab): add flat-PDF manifest with auto-discovered ids
ef1edd5 M1: feat(lab): add lane metadata to AcroForm manifest
c905804 feat(lab): field schema contract + char-box finding + flat-PDF GT bootstrap + automation prompt
```

Completed: Thu May 21 02:43:08 AM UTC 2026
