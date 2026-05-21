#!/usr/bin/env python3
"""
run_detection_lab.py

Lane-aware orchestration for the detection lab benchmark suite.
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend_registry import list_backends_for_lane

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
BENCHMARK_REPORTS_DIR = REPORTS_DIR / "benchmarks"
LATEST_DIR = REPORTS_DIR / "latest"
FLAT_GT_DIR = ROOT / "benchmarks" / "ground_truth_flat"

LANE_LABELS = {
    "A": "AcroForm widget scoring",
    "B": "flat-PDF usable-fill-zone scoring",
}


def run_cmd(args: list[str], *, allow_codes: set[int] | None = None) -> tuple[int, str]:
    allow_codes = allow_codes or {0}
    print("$ " + " ".join(args))
    result = subprocess.run(args, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, end="")
    if result.returncode not in allow_codes:
        raise RuntimeError(f"command failed with exit {result.returncode}: {' '.join(args)}")
    return result.returncode, result.stdout


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def safe_clear_latest() -> None:
    if LATEST_DIR.exists():
        shutil.rmtree(LATEST_DIR)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)


def flat_final_gt_files() -> list[Path]:
    if not FLAT_GT_DIR.exists():
        return []
    return sorted(
        p for p in FLAT_GT_DIR.glob("*.json")
        if not p.name.endswith(".draft.json") and not p.name.startswith("_")
    )


def flat_draft_rows() -> list[tuple[str, int]]:
    rows = []
    if not FLAT_GT_DIR.exists():
        return rows
    for path in sorted(FLAT_GT_DIR.glob("*.draft.json")):
        data = load_json(path)
        rows.append((data.get("pdf_id", path.name.replace(".draft.json", "")), len(data.get("fields", []))))
    return rows


def expected_pdf_count(lane: str) -> int:
    if lane == "A":
        gt_dir = ROOT / "benchmarks" / "ground_truth"
        return len([p for p in gt_dir.glob("*.json") if not p.name.startswith("_")]) if gt_dir.exists() else 0
    return len(flat_final_gt_files())


def run_benchmark(backend: str, lane: str) -> Path:
    before = {p.name for p in BENCHMARK_REPORTS_DIR.iterdir()} if BENCHMARK_REPORTS_DIR.exists() else set()
    run_cmd([sys.executable, "scripts/run_benchmark.py", "--backend", backend, "--lane", lane])
    after = [p for p in BENCHMARK_REPORTS_DIR.iterdir() if p.is_dir() and p.name not in before]
    if not after:
        matching = sorted(
            BENCHMARK_REPORTS_DIR.glob(f"*_{backend}_lane{lane}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if matching:
            return matching[0]
        raise RuntimeError(f"could not find benchmark run dir for {backend} lane {lane}")
    return sorted(after, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def scorecard_row(run_dir: Path) -> dict:
    scorecard = load_json(run_dir / "scorecard.json")
    agg = scorecard["aggregate"]
    return {
        "backend": agg["backend"],
        "run_id": agg["run_id"],
        "p": agg["aggregate_precision"],
        "r": agg["aggregate_recall"],
        "f1": agg["aggregate_f1"],
        "tp": agg["total_tp"],
        "fp": agg["total_fp"],
        "fn": agg["total_fn"],
        "pdfs": agg["pdfs_processed"],
        "run_dir": run_dir,
    }


def write_lane_scorecard(lane: str, rows: list[dict], skipped: list[str]) -> Path:
    path = LATEST_DIR / f"lane_{lane.lower()}_scorecard.md"
    lines = [f"# Lane {lane} Scorecard", "", f"**Lane:** {LANE_LABELS[lane]}", ""]
    if rows:
        lines.extend([
            "| Backend | P | R | F1 | TPs | FPs | FNs | Run |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for row in rows:
            lines.append(
                f"| {row['backend']} | {row['p']:.4f} | {row['r']:.4f} | {row['f1']:.4f} | "
                f"{row['tp']} | {row['fp']} | {row['fn']} | `{row['run_id']}` |"
            )
    else:
        lines.append("No benchmark runs completed for this lane.")
    if skipped:
        lines.extend(["", "## Skipped", ""])
        for item in skipped:
            lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n")
    return path


def write_summary(selected_lanes: list[str], lane_rows: dict[str, list[dict]], lane_skips: dict[str, list[str]], regression_text: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# Detection Lab Run - {now}", ""]
    for lane in selected_lanes:
        pdf_count = expected_pdf_count(lane)
        lines.append(f"## Lane {lane} ({LANE_LABELS[lane]}) - {pdf_count} PDFs")
        lines.append("")
        rows = lane_rows.get(lane, [])
        if rows:
            lines.extend([
                "| Backend | P | R | F1 | TPs | FPs | FNs |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ])
            for row in rows:
                lines.append(
                    f"| {row['backend']} | {row['p']:.4f} | {row['r']:.4f} | {row['f1']:.4f} | "
                    f"{row['tp']} | {row['fp']} | {row['fn']} |"
                )
            lines.append("")
        else:
            if lane == "B" and flat_draft_rows():
                lines.append("WARNING: No flat-PDF ground truth available. Bootstrap drafts exist but require human review before scoring.")
                lines.append("")
                lines.append("Drafts pending review:")
                for pdf_id, count in flat_draft_rows():
                    lines.append(f"- {pdf_id} ({count} candidate fields)")
                lines.append("")
            else:
                lines.append("No benchmark results available.")
                lines.append("")
        if lane_skips.get(lane):
            lines.append("Skipped:")
            for item in lane_skips[lane]:
                lines.append(f"- {item}")
            lines.append("")
    lines.append("## Regressions vs baseline")
    lines.append("")
    lines.append(regression_text.strip() or "None.")
    lines.append("")
    (LATEST_DIR / "summary.md").write_text("\n".join(lines))


def run_regressions(lane_rows: dict[str, list[dict]]) -> str:
    a_rows = lane_rows.get("A", [])
    baseline = next((r for r in a_rows if r["backend"] == "acroform_self"), None)
    candidate = next((r for r in a_rows if r["backend"] != "acroform_self"), None)
    if not baseline or not candidate:
        text = "None."
        (LATEST_DIR / "regressions.md").write_text(text + "\n")
        return text
    code, output = run_cmd([
        sys.executable,
        "scripts/compare_to_baseline.py",
        "--baseline",
        baseline["run_id"],
        "--candidate",
        candidate["run_id"],
    ], allow_codes={0, 3})
    text = output if output.strip() else "None."
    (LATEST_DIR / "regressions.md").write_text(text)
    return "See `reports/latest/regressions.md`." if code == 3 else "None."


def dry_run(selected_lanes: list[str]) -> None:
    print("Detection lab dry run")
    print("1. Verify corpus integrity: python scripts/verify_corpus.py")
    for lane in selected_lanes:
        print(f"Lane {lane} ({LANE_LABELS[lane]}):")
        for backend in list_backends_for_lane(lane):
            if lane == "B" and not flat_final_gt_files():
                print(f"  - SKIP {backend}: no reviewed flat-PDF GT JSON files")
            else:
                print(f"  - RUN python scripts/run_benchmark.py --backend {backend} --lane {lane}")
    print("Reports: reports/latest/summary.md, lane scorecards, regressions.md")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Run all lanes")
    group.add_argument("--lane", choices=["A", "B"], help="Run one lane")
    parser.add_argument("--dry-run", action="store_true", help="Report plan only")
    parser.add_argument("--render-overlays", action="store_true", help="Render comparison overlays after benchmarks")
    args = parser.parse_args()

    selected_lanes = [args.lane] if args.lane else ["A", "B"]
    if args.dry_run:
        dry_run(selected_lanes)
        return 0

    safe_clear_latest()
    run_cmd([sys.executable, "scripts/verify_corpus.py"])

    lane_rows: dict[str, list[dict]] = {lane: [] for lane in selected_lanes}
    lane_skips: dict[str, list[str]] = {lane: [] for lane in selected_lanes}

    for lane in selected_lanes:
        for backend in list_backends_for_lane(lane):
            if lane == "B" and not flat_final_gt_files():
                message = f"{backend}: no reviewed flat-PDF GT JSON files"
                print(f"WARNING: SKIP {message}")
                lane_skips[lane].append(message)
                continue
            run_dir = run_benchmark(backend, lane)
            row = scorecard_row(run_dir)
            lane_rows[lane].append(row)

    for lane in selected_lanes:
        write_lane_scorecard(lane, lane_rows[lane], lane_skips[lane])

    regression_text = run_regressions(lane_rows)
    write_summary(selected_lanes, lane_rows, lane_skips, regression_text)

    if args.render_overlays:
        run_cmd([sys.executable, "scripts/render_detection_comparison.py"], allow_codes={0})

    print(f"Latest summary: {LATEST_DIR.relative_to(ROOT) / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
