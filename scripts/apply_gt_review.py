#!/usr/bin/env python3
"""Apply an owner-completed review JSON without overwriting source ground truth."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from review_packet_schema import (
    GENERATOR_VERSION,
    PacketError,
    add_banner,
    assert_within,
    confirmation_binding,
    confirmation_token,
    draw_field_overlay,
    html_page,
    infer_gt_provenance,
    load_json,
    render_pdf_pages,
    repo_relative,
    safe_form_id,
    sanitize_text,
    save_png,
    sha256_file,
    validate_review,
    write_json,
    write_text,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "reviews" / "output"
CANDIDATE_STATUS = "human_review_candidate"
APPROVED_STATUS = "human_reviewed"
TOOL_VERSION = "lab-packet-apply-1.0"


def _resolve_repo_path(repo_root: Path, value: str | Path, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return assert_within(path, repo_root, label)


def load_review_context(review_path: Path, repo_root: Path = ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    review_path = _resolve_repo_path(repo_root, review_path, "review JSON")
    assert_within(review_path, repo_root / "reviews", "review JSON")
    if not review_path.is_file():
        raise PacketError(f"Review JSON not found: {review_path}")
    review = load_json(review_path)
    form_id = safe_form_id(str(review.get("form_id", "")))
    manifest_value = review.get("packet_manifest")
    if not manifest_value:
        raise PacketError("Review JSON has no packet_manifest")
    manifest_path = _resolve_repo_path(repo_root, manifest_value, "packet manifest")
    assert_within(manifest_path, repo_root / "reports" / "review_packets", "packet manifest")
    manifest = load_json(manifest_path)
    if manifest.get("form_id") != form_id:
        raise PacketError("Review and packet manifest form ids differ")
    pdf_path = _resolve_repo_path(repo_root, manifest.get("source_pdf", ""), "source PDF")
    gt_path = _resolve_repo_path(repo_root, manifest.get("gt_path", ""), "source GT")
    if not pdf_path.is_file() or not gt_path.is_file():
        raise PacketError("Source PDF or source GT is missing")
    pdf_hash = sha256_file(pdf_path)
    gt_hash = sha256_file(gt_path)
    expected_hashes = {
        "source PDF": (manifest.get("source_pdf_sha256"), review.get("source_pdf_sha256"), pdf_hash),
        "source GT": (manifest.get("gt_sha256"), review.get("source_gt_sha256"), gt_hash),
    }
    for label, values in expected_hashes.items():
        if len(set(values)) != 1:
            raise PacketError(f"{label} hash mismatch")
    source_gt = load_json(gt_path)
    rendered = render_pdf_pages(pdf_path, 200)
    page_sizes = {
        page["page"]: (page["pdf_width"], page["pdf_height"])
        for page in rendered
    }
    return {
        "repo_root": repo_root,
        "review_path": review_path,
        "review": review,
        "form_id": form_id,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "pdf_path": pdf_path,
        "pdf_hash": pdf_hash,
        "gt_path": gt_path,
        "gt_hash": gt_hash,
        "source_gt": source_gt,
        "rendered": rendered,
        "page_sizes": page_sizes,
    }


def _candidate_payload(context: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    source_gt = context["source_gt"]
    original_provenance = infer_gt_provenance(source_gt)
    review_hash = sha256_file(context["review_path"])
    manifest_hash = sha256_file(context["manifest_path"])
    candidate = dict(source_gt)
    candidate.update({
        "schema_version": source_gt.get("schema_version", "1.0"),
        "pdf_id": source_gt.get("pdf_id") or context["form_id"],
        "review_status": CANDIDATE_STATUS,
        "needs_review": True,
        "extraction_method": CANDIDATE_STATUS,
        "fields": validated["fields"],
        "provenance": {
            "kind": CANDIDATE_STATUS,
            "source_pdf": repo_relative(context["pdf_path"], context["repo_root"]),
            "source_pdf_sha256": context["pdf_hash"],
            "original_gt": repo_relative(context["gt_path"], context["repo_root"]),
            "original_gt_sha256": context["gt_hash"],
            "original_gt_provenance": original_provenance,
            "reviewer": validated["reviewer"],
            "reviewed_at": validated["reviewed_at"],
            "packet_manifest": repo_relative(context["manifest_path"], context["repo_root"]),
            "packet_manifest_sha256": manifest_hash,
            "review_json": repo_relative(context["review_path"], context["repo_root"]),
            "review_json_sha256": review_hash,
            "document_decision": validated["document_decision"],
            "applied_decisions": validated["decision_log"],
            "tool_version": TOOL_VERSION,
            "packet_generator_version": GENERATOR_VERSION,
        },
    })
    return candidate


def _candidate_overlay(
    context: dict[str, Any],
    candidate: dict[str, Any],
    overlay_dir: Path,
) -> None:
    if overlay_dir.exists():
        shutil.rmtree(overlay_dir)
    overlay_dir.mkdir(parents=True)
    zero_fields_confirmed = (
        not candidate.get("fields")
        and candidate.get("provenance", {}).get("document_decision")
        == "confirmed_zero_fields"
    )
    if zero_fields_confirmed:
        banner = (
            "OWNER REVIEW CANDIDATE - ZERO FILLABLE FIELDS "
            "AFFIRMATIVELY CONFIRMED"
        )
        footer = "NOT YET APPROVED - OWNER INSPECTION REQUIRED"
    else:
        banner = "HUMAN REVIEW CANDIDATE - NOT APPROVED"
        footer = "This overlay confirms a candidate only. It is not locked ground truth."
    figures = []
    for page in context["rendered"]:
        page_number = page["page"]
        fields = [field for field in candidate["fields"] if int(field["page"]) == page_number]
        image = draw_field_overlay(
            page["image"],
            fields,
            page["scale_px_per_point"],
            (30, 135, 75),
        )
        image = add_banner(
            image,
            banner,
            f"{context['form_id']} | page {page_number} | owner inspection required",
            footer,
        )
        name = f"page_{page_number:03d}.png"
        save_png(image, overlay_dir / name)
        figures.append(
            f'<figure><figcaption>Page {page_number}</figcaption><img src="{name}" alt="Candidate overlay page {page_number}"></figure>'
        )
    if zero_fields_confirmed:
        warning = (
            "OWNER REVIEW CANDIDATE - ZERO FILLABLE FIELDS AFFIRMATIVELY "
            "CONFIRMED. NOT YET APPROVED. Inspect every page before using "
            "the separate owner approval command."
        )
    else:
        warning = (
            "HUMAN REVIEW CANDIDATE - NOT APPROVED. Inspect every page before "
            "using the separate owner approval command."
        )
    body = f'<div class="warning">{warning}</div><div class="layers">{"".join(figures)}</div>'
    write_text(overlay_dir / "index.html", html_page(f"Candidate overlay: {context['form_id']}", body))


def apply_review_candidate(
    review_path: Path,
    repo_root: Path = ROOT,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    context = load_review_context(review_path, repo_root)
    validated = validate_review(
        context["review"],
        context["source_gt"],
        context["page_sizes"],
        require_complete=True,
    )
    output_dir = (output_dir or context["repo_root"] / "reviews" / "output").resolve()
    assert_within(output_dir, context["repo_root"] / "reviews" / "output", "review output")
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / f"{context['form_id']}_review_candidate.json"
    if candidate_path.resolve() == context["gt_path"].resolve():
        raise PacketError("Refusing to overwrite source ground truth")
    candidate = _candidate_payload(context, validated)
    write_json(candidate_path, candidate)
    candidate_hash = sha256_file(candidate_path)
    overlay_dir = output_dir / f"{context['form_id']}_review_candidate_overlay"
    _candidate_overlay(context, candidate, overlay_dir)
    binding = confirmation_binding(
        context["form_id"],
        context["pdf_hash"],
        context["gt_hash"],
        sha256_file(context["review_path"]),
        candidate_hash,
    )
    return {
        "status": CANDIDATE_STATUS,
        "candidate_path": candidate_path,
        "candidate_sha256": candidate_hash,
        "overlay_dir": overlay_dir,
        "confirmation_binding": binding,
        "confirmation_token": confirmation_token(binding),
    }


def approve_candidate(
    review_path: Path,
    supplied_token: str,
    owner_inspected_overlay: bool,
    repo_root: Path = ROOT,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if not owner_inspected_overlay:
        raise PacketError("Approval requires an explicit owner assertion that the overlay was inspected")
    context = load_review_context(review_path, repo_root)
    validated = validate_review(
        context["review"],
        context["source_gt"],
        context["page_sizes"],
        require_complete=True,
    )
    output_dir = (output_dir or context["repo_root"] / "reviews" / "output").resolve()
    assert_within(output_dir, context["repo_root"] / "reviews" / "output", "review output")
    candidate_path = output_dir / f"{context['form_id']}_review_candidate.json"
    overlay_dir = output_dir / f"{context['form_id']}_review_candidate_overlay"
    if not candidate_path.is_file() or not (overlay_dir / "index.html").is_file():
        raise PacketError("Approval requires an existing candidate and confirmation overlay")
    candidate = load_json(candidate_path)
    if candidate.get("review_status") != CANDIDATE_STATUS:
        raise PacketError("Candidate has an invalid review_status")
    candidate_fields = candidate.get("fields")
    if not isinstance(candidate_fields, list):
        raise PacketError("Candidate fields must be a list")
    candidate_provenance = candidate.get("provenance")
    if not isinstance(candidate_provenance, dict):
        raise PacketError("Candidate provenance must be an object")
    additions_applied = any(
        isinstance(item, dict) and item.get("decision") == "add"
        for item in candidate_provenance.get("applied_decisions", [])
    )
    if not candidate_fields and not additions_applied:
        if validated["document_decision"] != "confirmed_zero_fields":
            raise PacketError(
                "Zero-field approval requires the current review to affirm "
                "document_decision=confirmed_zero_fields"
            )
        if candidate_provenance.get("document_decision") != "confirmed_zero_fields":
            raise PacketError(
                "Zero-field approval requires candidate provenance "
                "document_decision=confirmed_zero_fields"
            )
    binding = confirmation_binding(
        context["form_id"],
        context["pdf_hash"],
        context["gt_hash"],
        sha256_file(context["review_path"]),
        sha256_file(candidate_path),
    )
    expected_token = confirmation_token(binding)
    if not supplied_token or supplied_token != expected_token:
        raise PacketError("Missing or invalid confirmation token")
    approved = dict(candidate)
    approved["review_status"] = APPROVED_STATUS
    approved["needs_review"] = False
    approved["extraction_method"] = APPROVED_STATUS
    approved["provenance"] = dict(candidate.get("provenance", {}))
    approved["provenance"]["approval"] = {
        "status": APPROVED_STATUS,
        "confirmation_binding": binding,
        "owner_inspected_overlay": True,
        "confirmation_token_sha256": confirmation_token({"token": expected_token}),
    }
    approved_path = output_dir / f"{context['form_id']}_human_reviewed.json"
    if approved_path.resolve() == context["gt_path"].resolve():
        raise PacketError("Refusing to overwrite source ground truth")
    write_json(approved_path, approved)
    return {"status": APPROVED_STATUS, "approved_path": approved_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, help="Structured review JSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--confirmation-token")
    parser.add_argument("--owner-inspected-overlay", action="store_true")
    args = parser.parse_args()
    try:
        if args.approve:
            result = approve_candidate(
                Path(args.review),
                supplied_token=args.confirmation_token or "",
                owner_inspected_overlay=args.owner_inspected_overlay,
                output_dir=Path(args.output_dir),
            )
            print(f"Approved output: {repo_relative(result['approved_path'])}")
            return 0
        result = apply_review_candidate(Path(args.review), output_dir=Path(args.output_dir))
        print(f"Status: {result['status']}")
        print(f"Candidate: {repo_relative(result['candidate_path'])}")
        print(f"Confirmation overlay: {repo_relative(result['overlay_dir'] / 'index.html')}")
        print(f"Confirmation token: {result['confirmation_token']}")
        print("No ground truth was promoted. Owner approval remains a separate command.")
        return 0
    except PacketError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
