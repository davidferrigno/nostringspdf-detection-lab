#!/usr/bin/env python3
"""Score a manual OCR/linebox candidate review file."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REVIEW_LABELS = {
    "unreviewed",
    "good",
    "bad",
    "duplicate",
    "needs_adjustment",
    "uncertain",
}
GOODISH_LABELS = {"good", "needs_adjustment"}
REVIEWED_LABELS = {"good", "bad", "duplicate", "needs_adjustment", "uncertain"}


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


def count_by(items: list[dict[str, Any]], key: str) -> Counter[str]:
    return Counter(str(item.get(key, "")) for item in items)


def nested_page_type_counts(candidates: list[dict[str, Any]]) -> dict[int, Counter[str]]:
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    for candidate in candidates:
        counts[int(candidate["page"])][candidate["type"]] += 1
    return counts


def score_review(review: dict[str, Any]) -> dict[str, Any]:
    candidates = review.get("candidate_reviews", [])
    page_reviews = review.get("page_reviews", [])
    labels = count_by(candidates, "label")
    bad_label_values = sorted(label for label in labels if label not in REVIEW_LABELS)
    reviewed = [c for c in candidates if c.get("label") in REVIEWED_LABELS]
    goodish = [c for c in reviewed if c.get("label") in GOODISH_LABELS]
    bad = [c for c in reviewed if c.get("label") == "bad"]
    duplicate = [c for c in reviewed if c.get("label") == "duplicate"]
    uncertain = [c for c in reviewed if c.get("label") == "uncertain"]
    needs_adjustment = [c for c in reviewed if c.get("label") == "needs_adjustment"]
    unreviewed = [c for c in candidates if c.get("label") == "unreviewed"]

    precision_like = None
    if reviewed:
        precision_like = len(goodish) / len(reviewed)

    pages_needing_review = sorted({int(c["page"]) for c in unreviewed})
    pages_with_missing_notes = [
        int(page["page"])
        for page in page_reviews
        if page.get("expected_missing_notes")
    ]
    bad_types = Counter(str(c.get("type", "unknown")) for c in bad)
    duplicate_types = Counter(str(c.get("type", "unknown")) for c in duplicate)

    return {
        "doc_id": review.get("doc_id"),
        "source_result_path": review.get("source_result_path"),
        "total_candidates": len(candidates),
        "reviewed_candidates": len(reviewed),
        "unreviewed_candidates": len(unreviewed),
        "label_counts": dict(sorted(labels.items())),
        "type_counts": dict(sorted(count_by(candidates, "type").items())),
        "page_counts": {
            str(page): sum(counts.values())
            for page, counts in sorted(nested_page_type_counts(candidates).items())
        },
        "page_type_counts": {
            str(page): dict(sorted(counts.items()))
            for page, counts in sorted(nested_page_type_counts(candidates).items())
        },
        "good_count": len([c for c in reviewed if c.get("label") == "good"]),
        "bad_count": len(bad),
        "duplicate_count": len(duplicate),
        "needs_adjustment_count": len(needs_adjustment),
        "uncertain_count": len(uncertain),
        "precision_like": precision_like,
        "top_false_positive_types": dict(bad_types.most_common()),
        "top_duplicate_types": dict(duplicate_types.most_common()),
        "pages_needing_review": pages_needing_review,
        "pages_with_missing_notes": pages_with_missing_notes,
        "invalid_labels": bad_label_values,
        "is_unreviewed_template": len(reviewed) == 0,
    }


def write_markdown(review: dict[str, Any], score: dict[str, Any], path: Path) -> None:
    precision_text = "n/a"
    if score["precision_like"] is not None:
        precision_text = f"{score['precision_like']:.2%}"

    lines = [
        f"# Linebox Review Score - {score['doc_id']}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Source result: `{score.get('source_result_path')}`",
        "",
        "## Summary",
        "",
        f"- Total candidates: {score['total_candidates']}",
        f"- Reviewed candidates: {score['reviewed_candidates']}",
        f"- Unreviewed candidates: {score['unreviewed_candidates']}",
        f"- Good: {score['good_count']}",
        f"- Bad: {score['bad_count']}",
        f"- Duplicate: {score['duplicate_count']}",
        f"- Needs adjustment: {score['needs_adjustment_count']}",
        f"- Uncertain: {score['uncertain_count']}",
        f"- Precision-like among reviewed: {precision_text}",
    ]
    if score["is_unreviewed_template"]:
        lines.extend([
            "",
            "**Status:** unreviewed template created. Fill `candidate_reviews[].label` before using this as a quality score.",
        ])
    if score["invalid_labels"]:
        lines.extend([
            "",
            f"**Invalid labels:** {', '.join(score['invalid_labels'])}",
        ])

    lines.extend(["", "## Labels", "", "| Label | Count |", "| --- | ---: |"])
    for label, count in sorted(score["label_counts"].items()):
        lines.append(f"| {label} | {count} |")

    lines.extend(["", "## Candidate Types", "", "| Type | Count |", "| --- | ---: |"])
    for ctype, count in sorted(score["type_counts"].items()):
        lines.append(f"| {ctype} | {count} |")

    lines.extend(["", "## Pages", "", "| Page | Candidates | By type |", "| ---: | ---: | --- |"])
    for page, count in score["page_counts"].items():
        by_type = ", ".join(f"{k}:{v}" for k, v in score["page_type_counts"][page].items())
        lines.append(f"| {page} | {count} | {by_type} |")

    lines.extend(["", "## Top False-Positive Types", ""])
    if score["top_false_positive_types"]:
        for ctype, count in score["top_false_positive_types"].items():
            lines.append(f"- {ctype}: {count}")
    else:
        lines.append("None reviewed yet.")

    lines.extend(["", "## Pages Needing Review", ""])
    if score["pages_needing_review"]:
        lines.append(", ".join(str(page) for page in score["pages_needing_review"]))
    else:
        lines.append("None.")

    missing_notes = [
        page
        for page in review.get("page_reviews", [])
        if page.get("expected_missing_notes")
    ]
    lines.extend(["", "## Missing-Field Notes", ""])
    if missing_notes:
        for page in missing_notes:
            lines.append(f"- Page {page['page']}: " + "; ".join(page["expected_missing_notes"]))
    else:
        lines.append("None recorded.")

    lines.extend([
        "",
        "## Next Heuristic Recommendations",
        "",
    ])
    if score["is_unreviewed_template"]:
        lines.extend([
            "- Review municipal pages 3-5 first.",
            "- Mark obvious text glyph fragments as `bad`.",
            "- Mark repeated boxes on the same field as `duplicate` and share a `group_id`.",
            "- Use `expected_missing_notes` for missing checkboxes, signature lines, date fields, or narrative boxes.",
        ])
    else:
        if score["top_false_positive_types"]:
            worst_type = next(iter(score["top_false_positive_types"]))
            lines.append(f"- Improve filtering for `{worst_type}` candidates first.")
        if score["duplicate_count"]:
            lines.append("- Add stronger overlap/grouping suppression for duplicate candidates.")
        if score["needs_adjustment_count"]:
            lines.append("- Use corrected bboxes to tune candidate geometry placement.")
        if score["uncertain_count"]:
            lines.append("- Resolve uncertain labels with overlay review before changing heuristics.")
        if not any([score["top_false_positive_types"], score["duplicate_count"], score["needs_adjustment_count"], score["uncertain_count"]]):
            lines.append("- No reviewed failure pattern yet.")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(score: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key in [
            "total_candidates",
            "reviewed_candidates",
            "unreviewed_candidates",
            "good_count",
            "bad_count",
            "duplicate_count",
            "needs_adjustment_count",
            "uncertain_count",
            "precision_like",
        ]:
            writer.writerow([key, score.get(key)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", required=True, help="Review JSON file")
    parser.add_argument("--out", required=True, help="Markdown score output")
    parser.add_argument("--json-out", default=None, help="Optional JSON score output")
    parser.add_argument("--csv-out", default=None, help="Optional CSV metric output")
    args = parser.parse_args()

    review_path = Path(args.review)
    if not review_path.is_absolute():
        review_path = ROOT / review_path
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    json_out = Path(args.json_out) if args.json_out else out_path.with_suffix(".json")
    if not json_out.is_absolute():
        json_out = ROOT / json_out
    csv_out = Path(args.csv_out) if args.csv_out else out_path.with_suffix(".csv")
    if not csv_out.is_absolute():
        csv_out = ROOT / csv_out

    for label, path in [("review", review_path), ("output", out_path), ("json output", json_out), ("csv output", csv_out)]:
        assert_under_root(path, label)

    review = load_json(review_path)
    score = score_review(review)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(review, score, out_path)
    json_out.write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
    write_csv(score, csv_out)

    print(f"Review scorecard: {rel(out_path)}")
    print(f"Review score JSON: {rel(json_out)}")
    print(f"Review score CSV: {rel(csv_out)}")
    print(f"Candidates: {score['total_candidates']}")
    print(f"Reviewed: {score['reviewed_candidates']}")
    print(f"Unreviewed: {score['unreviewed_candidates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
