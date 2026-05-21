# Codex Prompt — Detection Lab Automation Runner

**Send this to a FRESH Codex session. Not the production frontend session.**

---

## Identity check (run BEFORE any code changes)

You are working ONLY on the **detection-lab repository on the VPS**.

Before changing anything, run these commands and paste output:

```bash
cd ~/detection-lab
pwd
git remote -v
git branch --show-current
git status
ls scripts/backends/
cat docs/STATUS.md 2>/dev/null | head -50 || echo "no STATUS.md"
cat docs/failure_analysis_v1.md 2>/dev/null | head -30 || echo "no failure analysis"
cat docs/char_box_finding.md 2>/dev/null | head -30 || echo "no char-box finding"
```

**Expected:**
- Directory: `/home/lab/detection-lab`
- Remote: `github.com:davidferrigno/nostringspdf-detection-lab.git`
- Backend files exist: `heuristic_lab_v1.py`, `heuristic_lab_v2.py`, `__init__.py`
- Three docs above all exist (failure_analysis_v1.md and char_box_finding.md
  are required reading; STATUS.md is optional)

**If ANY of these are wrong: STOP. Do not proceed. Report which check failed.**

---

## Repository boundaries (HARD limits)

You are working in `/home/lab/detection-lab` ONLY.

Do NOT:
- Touch any path outside `/home/lab/detection-lab/`
- Modify `/mnt/...`, `/home/lab/<anything-else>`, or anything in production
- Reference the main production repo (`github.com:davidferrigno/nostringspdf.git`)
- Modify production detection logic, backends, or APIs
- Modify frontend code, React/JSX, or `index.html`
- Push to `main` branch

Do:
- Create and work on branch `lab/automation-runner`
- Push the branch to `origin` so the user can review
- Open no PR — let the user merge manually

---

## Create the branch

```bash
cd ~/detection-lab
git checkout main
git pull
git checkout -b lab/automation-runner
git push -u origin lab/automation-runner
```

Confirm: `git branch --show-current` outputs `lab/automation-runner`.

If `lab/automation-runner` already exists locally or remotely, STOP and
report; do not force-overwrite.

---

## Required reading (do not skip)

Read these THREE documents in full before writing any code:

1. **`docs/FIELD_SCHEMA.md`** — the integration contract between the lab
   and production. Every backend MUST emit this schema. (This file is
   added by the user before launching you; if it is not present, STOP
   and report.)

2. **`docs/failure_analysis_v1.md`** — explains the five failure
   categories observed in the v1 benchmark and the predictive recall
   model. Backend lanes derive from these categories.

3. **`docs/char_box_finding.md`** — explains why the lab needs two
   scoring lanes (AcroForm widget scoring vs flat-PDF usable-fill-zone
   scoring). This is the architectural reason behind everything you're
   about to build.

After reading, confirm by writing a 3-bullet summary in your response.
This is the proof you read the docs.

---

## Goal

Implement lane-aware automated benchmark runner.

The lab benchmark currently conflates AcroForm and flat PDFs into one
scoring lane. The char-box finding proves this is incorrect: AcroForm
widget bboxes encode editorial author choices, not geometry, so
heuristic backends cannot fairly score against them. Flat PDFs need
separate ground truth and separate scoring.

---

## Scope (milestones in order)

### M0: Verify FIELD_SCHEMA.md exists and is current

Run:
```bash
ls docs/FIELD_SCHEMA.md
head -20 docs/FIELD_SCHEMA.md
grep -c "schema_version" docs/FIELD_SCHEMA.md  # should be >= 3
```

If FIELD_SCHEMA.md is missing or doesn't reference `schema_version`:
STOP. Tell the user to add the schema first. Do not invent one.

### M1: Lane classification in AcroForm manifest

The AcroForm manifest already exists at
`samples/acroforms/manifest.json`. Each entry has `id`, `filename`, etc.

Add to each entry:
```json
{
  "lane": "acroform",
  "expected_lane": "A"
}
```

Lane A = AcroForm widget scoring (existing behavior).

Commit:
```
M1: feat(lab): add lane metadata to AcroForm manifest
```

### M2: Flat-PDF manifest with auto-discovered ids

Create new manifest `samples/flat/manifest.json` for flat PDFs.

Search `samples/flat/` recursively for `.pdf` files. For each one create:
```json
{
  "id": "<derived from filename>",
  "filename": "samples/flat/<subpath>/<file>.pdf",
  "source": "local",
  "lane": "flat",
  "expected_lane": "B"
}
```

The `id` should be a snake_case slug derived from the filename. Examples:
- `local_marriage_civil_union_license_application_form_pdf.pdf` →
  `marriage_license`
- `Eden_Lane_Ballot_Old.pdf` → `eden_lane_ballot`
- `edited_sp650_non_fill_6.pdf` → `sp650`

If unsure about an id derivation: emit `"_id_derivation_uncertain":
true` in the manifest entry. Continue.

Commit:
```
M2: feat(lab): add flat-PDF manifest with auto-discovered ids
```

### M3: Backend lane declarations

In `scripts/backend_registry.py`, augment each backend with metadata.

Change from current `BACKENDS` dict to:
```python
BACKEND_METADATA: dict = {
    "acroform_self": {
        "fn": _backend_acroform_self,
        "lanes": ["A"],
        "description": "Re-extracts AcroForm widgets via pikepdf - sanity check",
        "schema_version": "1.0",
    },
    "heuristic_lab_v1": {
        "fn": _backend_heuristic_lab_v1,
        "lanes": ["A", "B"],
        "description": "Generic content-stream heuristic (v1 baseline)",
        "schema_version": "1.0",
    },
    "heuristic_lab_v2": {
        "fn": _backend_heuristic_lab_v2,
        "lanes": ["B"],
        "description": "v1 + char-box detection (flat-PDF candidate)",
        "schema_version": "1.0",
    },
}
```

Keep `BACKENDS` dict for backward compatibility — populate it from
`BACKEND_METADATA`. Add helpers:
```python
def get_lanes_for_backend(name: str) -> list[str]:
    return BACKEND_METADATA[name]["lanes"]

def list_backends_for_lane(lane: str) -> list[str]:
    return sorted([n for n, m in BACKEND_METADATA.items() if lane in m["lanes"]])

def get_backend_metadata(name: str) -> dict:
    return BACKEND_METADATA[name]
```

Commit:
```
M3: feat(lab): backend_registry now declares lanes per backend
```

### M4: Lane-aware run_benchmark

Add `--lane A|B` argument to `scripts/run_benchmark.py`. Behavior:

- If `--lane A` (default): read AcroForm manifest, score against
  `benchmarks/ground_truth/<pdf_id>.json` (existing GT dir)
- If `--lane B`: read flat manifest, score against
  `benchmarks/ground_truth_flat/<pdf_id>.json` (new GT dir)

The benchmark MUST refuse to run a backend outside its declared lanes:
```python
if args.lane not in get_lanes_for_backend(args.backend):
    print(f"ERROR: backend '{args.backend}' is not declared for lane '{args.lane}'.")
    print(f"  Declared lanes: {get_lanes_for_backend(args.backend)}")
    print(f"  To force anyway: --force-lane-mismatch")
    sys.exit(2)
```

Include `--force-lane-mismatch` escape hatch.

Run IDs become `{timestamp}_{backend}_lane{A|B}`.
Reports go to `reports/benchmarks/{run_id}/` (unchanged path scheme).

Scorecard JSON output must include the lane and `schema_version` (read
from `get_backend_metadata(backend)`) in the aggregate section.

Commit:
```
M4: feat(lab): run_benchmark.py supports --lane flag
```

### M5: Flat-PDF GT bootstrap (DRAFT ONLY, NO PROMOTION)

A `scripts/extract_flat_pdf_ground_truth.py` script exists already from
the prior session — verify it works.

For every entry in `samples/flat/manifest.json`, run:
```bash
python scripts/extract_flat_pdf_ground_truth.py --pdf <id>
```

This produces `benchmarks/ground_truth_flat/<id>.draft.json` files.

**CRITICAL:** Each draft MUST contain `"needs_review": true` at the top
level. Do NOT promote any draft. Do NOT remove the needs_review marker.

If `extract_flat_pdf_ground_truth.py` does not exist or fails: do NOT
write a replacement. Report the failure, leave Lane B without GT, and
proceed with the rest of scope. Lane B benchmarks will gracefully skip
in M6.

Commit:
```
M5: feat(lab): generate flat-PDF GT drafts (needs_review)
```

### M6: Orchestrator: scripts/run_detection_lab.py

New script. Top-level interface:
```bash
python scripts/run_detection_lab.py --all       # run everything
python scripts/run_detection_lab.py --lane A    # AcroForm lane only
python scripts/run_detection_lab.py --lane B    # flat-PDF lane only
python scripts/run_detection_lab.py --dry-run   # report plan only
```

Behavior of `--all`:

```
1. Verify corpus integrity (call verify_corpus.py)
2. For each lane in [A, B]:
   - For each backend declared for that lane:
     - If lane B and no GT exists for that pdf: skip with warning
     - Otherwise: run run_benchmark.py --backend <b> --lane <l>
3. Generate per-lane aggregate report
4. Generate combined summary at reports/latest/summary.md
5. Optionally render comparison overlays (call render_detection_comparison.py)
```

`reports/latest/` directory contents (cleared and re-populated each run):
- `summary.md` — combined Lane A + Lane B aggregate scores
- `lane_a_scorecard.md` — copy of the latest Lane A scorecard
- `lane_b_scorecard.md` — copy of the latest Lane B scorecard (if GT exists)
- `regressions.md` — output of compare_to_baseline.py if baseline exists

Summary format:

```markdown
# Detection Lab Run — 2026-05-21 09:15:42

## Lane A (AcroForm widget scoring) — 30 PDFs

| Backend | P | R | F1 | TPs | FPs | FNs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| acroform_self | 1.0000 | 1.0000 | 1.0000 | 3047 | 0 | 0 |
| heuristic_lab_v1 | 0.6834 | 0.3032 | 0.4201 | 924 | 428 | 2123 |

## Lane B (flat-PDF usable-fill-zone scoring)

⚠️  No flat-PDF ground truth available. Bootstrap drafts exist but
require human review before scoring.

Drafts pending review:
- marriage_license  (X candidate fields)
- eden_lane_ballot  (Y candidate fields)
- sp650             (Z candidate fields)

## Regressions vs baseline

None.
```

Commit:
```
M6: feat(lab): run_detection_lab.py orchestrator
```

### M7: Documentation

Write `docs/detection_lab_workflow.md`. Cover:
- The two-lane architecture (why; reference char_box_finding.md)
- How to add a new backend (edit `backend_registry.py`, set lanes)
- How to add a new AcroForm PDF (add to manifest, run extract_ground_truth.py)
- How to add a new flat PDF (add to manifest, run bootstrap, hand-review,
  promote)
- How to run a single benchmark vs the full lab
- How regression detection works
- Where reports go
- Reference to FIELD_SCHEMA.md as the integration contract

Commit:
```
M7: docs: detection_lab_workflow.md
```

### M8: Smoke test

Add `scripts/test_lab_smoke.py` that:
- Imports all backends without error
- Verifies BACKEND_METADATA structure (each entry has fn, lanes, description,
  schema_version)
- Asserts `schema_version` of each backend equals "1.0"
- Runs `run_benchmark.py --backend acroform_self --lane A --pdf irs_w9` and
  asserts aggregate P=1.0, R=1.0
- Asserts that running `run_benchmark.py --backend heuristic_lab_v2 --lane A`
  (without --force-lane-mismatch) exits with code 2
- Reports `PASS` or `FAIL <reason>` per test

The smoke test is the canary. If it fails after any earlier commit, STOP
and report.

Commit:
```
M8: test: add test_lab_smoke.py
```

---

## Out of scope (DO NOT DO)

- DO NOT modify any backend's detection logic
- DO NOT delete or rewrite any existing backend
- DO NOT promote any flat-PDF draft GT to final
- DO NOT modify production heuristic in main NoStringsPDF repo
- DO NOT change paths in existing scripts unless necessary for lane
  support
- DO NOT add Azure, Textract, OCR backends
- DO NOT enable CI hooks; just produce the reports
- DO NOT add a new schema version
- DO NOT add `reports/latest` symlink magic if it complicates Windows
  workflows — a directory copy is fine

---

## Commit discipline

After EACH milestone, commit and push to `lab/automation-runner`:

```bash
git add <files>
git commit -m "<message from milestone>"
git push origin lab/automation-runner
```

If any milestone breaks the smoke test or any existing benchmark
command, STOP. Do not proceed. Report the failure.

---

## Final deliverables (paste back to the user)

After all milestones land:

1. `git log --oneline lab/automation-runner ^main` — what changed
2. `git diff --stat main..lab/automation-runner` — file change summary
3. `python scripts/test_lab_smoke.py` output (all PASS)
4. `python scripts/run_detection_lab.py --dry-run` output
5. `python scripts/run_detection_lab.py --all` output
6. `cat reports/latest/summary.md` output
7. `ls benchmarks/ground_truth_flat/` output
8. List of flat-PDF drafts created (each with field count)
9. Any issues encountered or scope decisions made

---

## What to do if something is ambiguous

Stop and ask. Do not improvise around contract-affecting decisions.
Specifically:
- Unsure of lane assignment for a PDF → mark `expected_lane: unknown`,
  emit `_lane_assignment_uncertain: true`, continue
- Backend import fails → leave the failed backend out of the registry,
  emit a log line, continue
- Existing script needs modification beyond `--lane` support → describe
  the change in your final deliverables; do NOT modify silently
- FIELD_SCHEMA.md disagrees with current backend behavior → STOP. The
  schema is the contract. Backend behavior must match the schema. Do
  NOT modify the schema; report the discrepancy.

---

## End-of-task checklist

- [ ] M0: FIELD_SCHEMA.md verified
- [ ] M1: AcroForm manifest updated with lane metadata
- [ ] M2: Flat manifest created
- [ ] M3: backend_registry updated with metadata + helpers
- [ ] M4: run_benchmark.py supports --lane flag
- [ ] M5: Flat-PDF drafts created (all with needs_review: true)
- [ ] M6: run_detection_lab.py orchestrator works
- [ ] M7: detection_lab_workflow.md written
- [ ] M8: smoke test passes
- [ ] Branch `lab/automation-runner` exists on origin
- [ ] All milestone commits pushed
- [ ] Lane A scores match v1 baseline (aggregate P=0.6834 R=0.3032)
- [ ] No production code touched
- [ ] No frontend code touched
- [ ] No backend detection logic touched
- [ ] No flat-PDF draft promoted to final

Report completion. Do not merge yourself.
