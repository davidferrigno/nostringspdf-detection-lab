# Public PDF Corpus Plan

This plan describes safe future acquisition of blank/public/synthetic PDFs for
the detection lab. Do not scrape randomly in this slice.

## Allowed Categories

- USCIS blank forms.
- IRS blank forms.
- CMS blank forms.
- State and municipal court blank forms.
- DMV blank forms.
- Public school or medical intake forms only when clearly blank and public.
- Synthetic generated forms with fake values or empty fill zones.

## Acquisition Rules

- Use only public blank forms or synthetic forms.
- Record the source URL and download timestamp when a file is acquired.
- Run privacy review before commit.
- Do not commit filled user data.
- Do not commit real names, addresses, SSNs, signatures, phone numbers,
  emails, employer data, medical data, legal data, or customer/user PII.
- Do not scrape broad sites without an explicit allowlist.
- Mark uncertain files for manual review before adding them to the committed
  corpus.

## Manifest Requirements

Every new entry should include:

- `id`
- `filename`
- `path`
- `lanes`
- `expected_lane`
- `ground_truth_path`, if available
- `needs_ground_truth`
- `needs_manual_review`
- `known_failure`
- `notes`
- `privacy_status`

## Privacy Status

- `blank`: public blank form or blank local form reviewed for commit.
- `synthetic`: generated or fake-value test form reviewed for commit.
- `sensitive_do_not_store`: real filled form or uncertain file; local-only,
  skipped by default, never copied into `samples/`, and never committed.

## Intake Flow

1. Record the candidate in `docs/failure_intake.md`.
2. Confirm privacy status.
3. Add only blank/public/synthetic PDFs to `samples/`.
4. Add or update `corpus/manifest.json`.
5. Run `py -3.13 scripts/run_lab_pipeline.py --manifest corpus/manifest.json --out runs`.
6. Review the scorecard and generated signals before opening detector work.
