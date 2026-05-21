#!/usr/bin/env python3
"""Smoke tests for the detection lab automation runner."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def result(name: str, ok: bool, detail: str = "") -> bool:
    if ok:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}: {detail}")
    return ok


def test_import_backends() -> bool:
    try:
        import backend_registry as br
        for name in br.list_backends():
            fn = br.get_backend(name)
            if not callable(fn):
                return result("imports", False, f"backend {name} is not callable")
        return result("imports", True)
    except Exception as exc:
        return result("imports", False, f"{type(exc).__name__}: {exc}")


def test_backend_metadata() -> bool:
    try:
        import backend_registry as br
        required = {"fn", "lanes", "description", "schema_version"}
        for name, metadata in br.BACKEND_METADATA.items():
            missing = required - set(metadata)
            if missing:
                return result("backend_metadata", False, f"{name} missing {sorted(missing)}")
            if not callable(metadata["fn"]):
                return result("backend_metadata", False, f"{name} fn is not callable")
            if not isinstance(metadata["lanes"], list) or not metadata["lanes"]:
                return result("backend_metadata", False, f"{name} lanes must be a non-empty list")
            if not metadata["description"]:
                return result("backend_metadata", False, f"{name} description is empty")
        return result("backend_metadata", True)
    except Exception as exc:
        return result("backend_metadata", False, f"{type(exc).__name__}: {exc}")


def test_schema_versions() -> bool:
    try:
        import backend_registry as br
        bad = [name for name, metadata in br.BACKEND_METADATA.items() if metadata.get("schema_version") != "1.0"]
        if bad:
            return result("schema_versions", False, f"non-1.0 backends: {bad}")
        return result("schema_versions", True)
    except Exception as exc:
        return result("schema_versions", False, f"{type(exc).__name__}: {exc}")


def newest_matching(pattern: str, before: set[str]) -> Path | None:
    reports_dir = ROOT / "reports" / "benchmarks"
    if not reports_dir.exists():
        return None
    candidates = [p for p in reports_dir.glob(pattern) if p.is_dir() and p.name not in before]
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    candidates = list(reports_dir.glob(pattern))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def test_acroform_self_w9() -> bool:
    reports_dir = ROOT / "reports" / "benchmarks"
    before = {p.name for p in reports_dir.iterdir()} if reports_dir.exists() else set()
    proc = subprocess.run(
        [sys.executable, "scripts/run_benchmark.py", "--backend", "acroform_self", "--lane", "A", "--pdf", "irs_w9"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        return result("acroform_self_w9", False, f"exit {proc.returncode}\n{proc.stdout}")
    run_dir = newest_matching("*_acroform_self_laneA", before)
    if run_dir is None:
        return result("acroform_self_w9", False, "scorecard run directory not found")
    scorecard = json.loads((run_dir / "scorecard.json").read_text())
    agg = scorecard["aggregate"]
    if agg.get("aggregate_precision") != 1.0 or agg.get("aggregate_recall") != 1.0:
        return result("acroform_self_w9", False, f"P={agg.get('aggregate_precision')} R={agg.get('aggregate_recall')}")
    return result("acroform_self_w9", True)


def test_lane_mismatch_exit() -> bool:
    proc = subprocess.run(
        [sys.executable, "scripts/run_benchmark.py", "--backend", "heuristic_lab_v2", "--lane", "A"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 2:
        return result("lane_mismatch_exit", False, f"expected 2 got {proc.returncode}\n{proc.stdout}")
    return result("lane_mismatch_exit", True)


def main() -> int:
    tests = [
        test_import_backends,
        test_backend_metadata,
        test_schema_versions,
        test_acroform_self_w9,
        test_lane_mismatch_exit,
    ]
    ok = True
    for test in tests:
        ok = test() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
