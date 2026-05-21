========================================================================
compare_to_baseline.py
Baseline:  reports/benchmarks/2026-05-21_020944_acroform_self_laneA
Candidate: reports/benchmarks/2026-05-21_020944_heuristic_lab_v1_laneA
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

Reports written: reports/comparisons/2026-05-21_020955_vs_baseline/
  - comparison.json
  - comparison.csv
  - comparison.md
