# Scheduling The Lab Pipeline

The lab pipeline is safe to run repeatedly because generated outputs live under
ignored `runs/` folders. Do not schedule production deploys from this repo.

Recommended cadence: hourly while actively testing detectors, nightly during
normal background monitoring.

## Manual Run

```powershell
py -3.13 scripts/run_lab_pipeline.py --manifest corpus/manifest.json --out runs
```

## Windows Task Scheduler

Program:

```text
powershell.exe
```

Arguments:

```text
-ExecutionPolicy Bypass -File E:\Code\nostringspdf-detection-lab\scripts\run_lab_pipeline.ps1
```

Start in:

```text
E:\Code\nostringspdf-detection-lab
```

Use an hourly or nightly trigger. The wrapper writes logs to `runs/logs/` and
exits nonzero if the pipeline fails.

## Linux Cron

Example nightly run:

```cron
15 2 * * * cd /home/lab/detection-lab && ./scripts/run_lab_pipeline.sh
```

Example hourly run:

```cron
7 * * * * cd /home/lab/detection-lab && ./scripts/run_lab_pipeline.sh
```

## VPS Manual Loop

For a temporary background run without installing services:

```bash
while true; do
  ./scripts/run_lab_pipeline.sh
  sleep 3600
done
```

## Guardrails

- Do not schedule production deploys.
- Do not commit generated `runs/` output unless explicitly approved.
- Do not add filled real-user PDFs to the committed corpus.
- Keep `sensitive_do_not_store` entries local-only and skipped by default.
