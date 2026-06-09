#!/usr/bin/env python3
"""Placeholder for the future OCR plus line/box detection experiment."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    print("OCR line/box experiment scaffold")
    print("No OCR pipeline is implemented in this slice.")
    print("Plan: docs/ocr_linebox_plan.md")
    print("Input lane: scanned_image entries in corpus/manifest.json")
    print(f"Experiment directory: {ROOT / 'experiments' / 'ocr_linebox'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
