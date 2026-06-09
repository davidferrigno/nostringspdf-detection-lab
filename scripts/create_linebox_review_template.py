#!/usr/bin/env python3
"""Create a manual review template for OCR/linebox candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REVIEWER = "manual_review"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def assert_under_root(path: Path, label: str) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        raise RuntimeError(f"{label} must be inside {ROOT}: {resolved}")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_hash(candidate: dict[str, Any]) -> str:
    payload = {
        "page": candidate.get("page"),
        "type": candidate.get("type"),
        "bbox": candidate.get("bbox"),
        "source": candidate.get("source"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:8]


def candidate_id(doc_id: str, candidate: dict[str, Any], index: int) -> str:
    page = candidate.get("page", "x")
    ctype = str(candidate.get("type", "unknown")).replace(" ", "_")
    return f"{doc_id}_p{page}_{ctype}_{index:04d}_{candidate_hash(candidate)}"


def build_review(result: dict[str, Any], result_path: Path, reviewer: str) -> dict[str, Any]:
    doc_id = result["id"]
    page_reviews = []
    candidate_reviews = []
    index = 0

    for page in result.get("pages", []):
        page_num = page["page"]
        page_reviews.append({
            "page": page_num,
            "overlay": page.get("overlay"),
            "candidate_count": page.get("candidate_count", 0),
            "candidate_counts_by_type": page.get("candidate_counts_by_type", {}),
            "expected_missing_notes": [],
            "reviewer_notes": "",
        })
        for candidate in page.get("candidates", []):
            index += 1
            candidate_reviews.append({
                "candidate_id": candidate_id(doc_id, candidate, index),
                "page": candidate.get("page", page_num),
                "type": candidate.get("type", "unknown"),
                "bbox": candidate.get("bbox"),
                "image_bbox": candidate.get("image_bbox"),
                "confidence": candidate.get("confidence"),
                "source": candidate.get("source"),
                "source_notes": candidate.get("notes", ""),
                "label": "unreviewed",
                "expected_type": "",
                "corrected_bbox": None,
                "notes": "",
                "group_id": "",
                "matched_ground_truth_id": "",
            })

    return {
        "schema_version": "linebox_review_v1",
        "doc_id": doc_id,
        "source_result_path": rel(result_path),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reviewed_at": None,
        "reviewer": reviewer,
        "review_guidance": {
            "labels": [
                "unreviewed",
                "good",
                "bad",
                "duplicate",
                "needs_adjustment",
                "uncertain",
            ],
            "page_missing_notes": "Use page_reviews[].expected_missing_notes for missing fields when no full ground truth exists.",
        },
        "page_reviews": page_reviews,
        "candidate_reviews": candidate_reviews,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, help="OCR/linebox result JSON")
    parser.add_argument("--out", required=True, help="Review template output JSON")
    parser.add_argument("--reviewer", default=DEFAULT_REVIEWER, help="Reviewer name")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing review file")
    args = parser.parse_args()

    result_path = Path(args.result)
    if not result_path.is_absolute():
        result_path = ROOT / result_path
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    assert_under_root(result_path, "result")
    assert_under_root(out_path, "output")

    if not result_path.exists():
        raise FileNotFoundError(result_path)
    if out_path.exists() and not args.overwrite:
        raise FileExistsError(f"{out_path} exists; pass --overwrite to replace it")

    result = load_json(result_path)
    review = build_review(result, result_path, args.reviewer)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")

    print(f"Review template: {rel(out_path)}")
    print(f"Document: {review['doc_id']}")
    print(f"Pages: {len(review['page_reviews'])}")
    print(f"Candidates: {len(review['candidate_reviews'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
