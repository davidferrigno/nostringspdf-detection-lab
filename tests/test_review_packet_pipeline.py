from __future__ import annotations

import copy
import hashlib
import json
import socket
import sys
from pathlib import Path

import fitz
import pytest


LAB_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = LAB_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import apply_gt_review
import generate_review_packets
import review_packet_schema
from review_packet_schema import (
    PacketError,
    build_overlap_hints,
    confirmation_binding,
    confirmation_token,
    infer_gt_provenance,
    load_json,
    safe_form_id,
    sha256_file,
    validate_review,
    write_json,
)


def _write_pdf(path: Path, width: float = 240, height: float = 320) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    page.insert_text((24, 34), "Blank public synthetic form")
    page.draw_rect(fitz.Rect(24, 70, 36, 82))
    page.draw_line(fitz.Point(60, 100), fitz.Point(190, 100))
    document.save(path)
    document.close()


def _mini_repo(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "repo"
    pdf_path = root / "samples" / "flat" / "synthetic_form.pdf"
    gt_path = root / "benchmarks" / "ground_truth_flat" / "synthetic_form.draft.json"
    queue_path = root / "reports" / "gt_review_queue" / "QUEUE.md"
    manifest_path = root / "corpus" / "manifest.json"
    _write_pdf(pdf_path)
    gt = {
        "schema_version": "1.0",
        "pdf_id": "synthetic_form",
        "page_count": 1,
        "review_status": "draft",
        "needs_review": True,
        "extraction_method": "flat_pdf_bootstrap",
        "bootstrap_backend": "synthetic_bootstrap",
        "fields": [
            {
                "id": "g1",
                "page": 1,
                "type": "text",
                "bbox": [60, 84, 130, 18],
                "label": "Name",
                "group_id": None,
                "state": None,
            }
        ],
    }
    write_json(gt_path, gt)
    manifest = {
        "entries": [
            {
                "id": "synthetic_form",
                "path": "samples/flat/synthetic_form.pdf",
                "ground_truth_path": "benchmarks/ground_truth_flat/synthetic_form.draft.json",
                "privacy_status": "synthetic",
                "needs_manual_review": True,
                "known_failure": True,
            }
        ]
    }
    write_json(manifest_path, manifest)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        "# Review queue\n\n## Entry 1 - synthetic_form\n",
        encoding="utf-8",
        newline="\n",
    )
    return root, {"pdf": pdf_path, "gt": gt_path, "queue": queue_path, "manifest": manifest_path}


def _backend(_pdf_path: Path) -> list[dict]:
    return [
        {
            "id": "d1",
            "page": 1,
            "type": "text",
            "bbox": [58, 82, 66, 20],
            "label": "Name",
        },
        {
            "id": "d2",
            "page": 1,
            "type": "text",
            "bbox": [122, 82, 70, 20],
            "label": "Name continuation",
        },
    ]


def _backend_override():
    return _backend, {
        "backend_id": "synthetic_lab_backend",
        "schema_version": "1.0",
        "lanes": ["B"],
        "description": "Deterministic synthetic lab backend",
        "production_equivalent": False,
        "parity_note": "Synthetic test backend; no production parity is claimed.",
        "configuration": {"seed": 0},
    }


def _generate(root: Path, paths: dict, backend_override=None):
    return generate_review_packets.generate_packets(
        repo_root=root,
        queue_path=paths["queue"],
        manifest_path=paths["manifest"],
        out_dir=root / "reports" / "review_packets",
        reviews_dir=root / "reviews",
        backend_id="synthetic_lab_backend",
        include_ocr_demo=False,
        backend_override=backend_override or _backend_override(),
    )


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _metric_keys(value) -> set[str]:
    forbidden = {"precision", "recall", "f1", "accuracy", "aggregate_iou", "ranking"}
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                found.add(str(key).lower())
            found.update(_metric_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_metric_keys(child))
    return found


def _completed_review(root: Path) -> tuple[Path, dict]:
    review_path = root / "reviews" / "synthetic_form.review.json"
    review = load_json(review_path)
    review["reviewer"] = "Synthetic Test Reviewer"
    review["reviewed_at"] = "2026-08-10T12:00:00-04:00"
    review["fields"][0]["decision"] = "accept"
    write_json(review_path, review)
    return review_path, review


def _zero_field_repo(tmp_path: Path) -> tuple[Path, dict]:
    root, paths = _mini_repo(tmp_path)
    gt = load_json(paths["gt"])
    gt["fields"] = []
    write_json(paths["gt"], gt)
    _unused_backend, metadata = _backend_override()
    _generate(root, paths, backend_override=(lambda _pdf_path: [], metadata))
    return root, paths


def _completed_zero_field_review(
    root: Path,
    document_decision: str = "pending",
) -> tuple[Path, dict]:
    review_path = root / "reviews" / "synthetic_form.review.json"
    review = load_json(review_path)
    review["reviewer"] = "Synthetic Test Reviewer"
    review["reviewed_at"] = "2026-08-11T12:00:00-04:00"
    review["document_decision"] = document_decision
    write_json(review_path, review)
    return review_path, review


def _valid_addition() -> dict:
    return {
        "field_id": "added1",
        "page": 1,
        "type": "text",
        "geometry": [24, 120, 120, 18],
        "label": "Added field",
        "group_id": None,
        "comment": "Synthetic addition",
    }


def _multiline_addition() -> dict:
    return {
        "field_id": "summary",
        "page": 1,
        "type": "text",
        "geometry": [24, 120, 190, 160],
        "label": "Qualifications Summary",
        "group_id": None,
        "comment": "Synthetic ruled multiline addition",
    }


def _ruled_annotation(field_id: str = "text1", line_count: int = 2) -> dict:
    if line_count == 14:
        guides = [
            {"x1": 30, "y": 130 + index * 10, "x2": 205}
            for index in range(line_count)
        ]
    else:
        guides = [
            {"x1": 25, "y": 50, "x2": 195},
            {"x1": 25, "y": 80, "x2": 195},
        ]
    return {
        "kind": "ruled_multiline",
        "line_count": line_count,
        "line_guides": guides,
        "wrap": True,
        "vertical_align": "top",
        "max_words": 200,
    }


def _annotation_validation_case() -> tuple[dict, dict, dict[int, tuple[float, float]]]:
    source_gt = {
        "schema_version": "1.0",
        "fields": [
            {"id": "text1", "page": 1, "type": "text", "bbox": [20, 20, 180, 100], "label": "Summary"},
            {"id": "check1", "page": 1, "type": "checkbox", "bbox": [20, 140, 12, 12], "label": "Check"},
            {"id": "signature1", "page": 1, "type": "signature", "bbox": [20, 170, 100, 18], "label": "Signature"},
        ],
    }
    review = {
        "review_schema_version": "1.0",
        "reviewer": "Synthetic Test Reviewer",
        "reviewed_at": "2026-08-11T12:00:00-04:00",
        "document_decision": "pending",
        "fields": [
            {"field_id": field["id"], "decision": "accept"}
            for field in source_gt["fields"]
        ],
        "additions": [],
        "review_annotations": {"text1": _ruled_annotation()},
    }
    return review, source_gt, {1: (240, 320)}


def _completed_annotated_review(
    root: Path,
    line_count: int = 14,
) -> tuple[Path, dict]:
    review_path, review = _completed_review(root)
    review["additions"] = [_multiline_addition()]
    review["review_annotations"] = {
        "summary": _ruled_annotation("summary", line_count=line_count)
    }
    write_json(review_path, review)
    return review_path, review


def _populated_two_field_review(
    tmp_path: Path,
    document_decision: str,
) -> tuple[Path, dict, Path, dict]:
    root, paths = _mini_repo(tmp_path)
    gt = load_json(paths["gt"])
    gt["fields"].append(
        {
            "id": "g2",
            "page": 1,
            "type": "checkbox",
            "bbox": [24, 70, 12, 12],
            "label": "Consent",
            "group_id": None,
            "state": None,
        }
    )
    write_json(paths["gt"], gt)
    _generate(root, paths)
    review_path = root / "reviews" / "synthetic_form.review.json"
    review = load_json(review_path)
    review["reviewer"] = "Synthetic Test Reviewer"
    review["reviewed_at"] = "2026-08-11T12:00:00-04:00"
    review["document_decision"] = document_decision
    for row in review["fields"]:
        row["decision"] = "delete"
    write_json(review_path, review)
    return root, paths, review_path, review


def test_form_ids_and_provenance_are_stable():
    assert safe_form_id("synthetic_form") == "synthetic_form"
    with pytest.raises(PacketError):
        safe_form_id("Synthetic Form")
    assert infer_gt_provenance({"extraction_method": "acroform_widgets"})["kind"] == "native_widget_derived"
    assert infer_gt_provenance({"extraction_method": "flat_pdf_bootstrap"})["kind"] == "detector_bootstrapped"
    assert infer_gt_provenance({"extraction_method": "manual"})["kind"] == "manually_authored_draft"
    assert infer_gt_provenance({})["kind"] == "unknown_unreviewed"


def test_overlap_hints_preserve_many_to_many_links():
    drafts = [
        {"id": "g1", "page": 1, "type": "text", "bbox": [0, 0, 100, 20]},
        {"id": "g2", "page": 1, "type": "text", "bbox": [100, 0, 100, 20]},
    ]
    detectors = [
        {"id": "d1", "page": 1, "type": "text", "bbox": [0, 0, 50, 20]},
        {"id": "d2", "page": 1, "type": "text", "bbox": [50, 0, 50, 20]},
        {"id": "d3", "page": 1, "type": "text", "bbox": [80, 0, 40, 20]},
    ]
    hints = build_overlap_hints(drafts, detectors)
    assert hints["draft_links"]["g1"] == ["d1", "d2", "d3"]
    assert hints["detector_links"]["d3"] == ["g1", "g2"]
    assert hints["status"] == "UNSCORED_REVIEW_NAVIGATION_ONLY"


def test_packet_generation_is_complete_idempotent_and_unscored(tmp_path, monkeypatch):
    root, paths = _mini_repo(tmp_path)
    before_pdf = sha256_file(paths["pdf"])
    before_gt = sha256_file(paths["gt"])
    before_manifest = sha256_file(paths["manifest"])
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call")))
    _generate(root, paths)
    packet_root = root / "reports" / "review_packets"
    form_root = packet_root / "synthetic_form"
    expected = [
        packet_root / "index.html",
        packet_root / "packet_manifest.json",
        form_root / "form_manifest.json",
        form_root / "index.html",
        form_root / "source" / "page_001.png",
        form_root / "draft_gt" / "page_001.png",
        form_root / "detector_synthetic_lab_backend" / "page_001.png",
        form_root / "combined" / "page_001.png",
        form_root / "tables" / "draft_gt.json",
        form_root / "tables" / "detector_synthetic_lab_backend.json",
        form_root / "tables" / "detector_synthetic_lab_backend_raw.json",
        form_root / "tables" / "overlap_hints.json",
        root / "reviews" / "synthetic_form.review.json",
        root / "reviews" / "synthetic_form.review.md",
    ]
    assert all(path.is_file() for path in expected)
    manifest = load_json(form_root / "form_manifest.json")
    assert manifest["source_pdf_sha256"] == before_pdf
    assert manifest["gt_sha256"] == before_gt
    assert manifest["gt_provenance"]["kind"] == "detector_bootstrapped"
    assert manifest["backend"]["backend_id"] == "synthetic_lab_backend"
    assert manifest["backend"]["schema_version"] == "1.0"
    assert manifest["backend"]["production_equivalent"] is False
    assert manifest["packet_status"] == "UNSCORED_DRAFT_REVIEW_PACKET"
    assert not _metric_keys(manifest)
    review = load_json(root / "reviews" / "synthetic_form.review.json")
    assert {row["decision"] for row in review["fields"]} == {"pending"}
    assert review["document_decision"] == "pending"
    assert review["review_annotations"] == {}
    markdown = (root / "reviews" / "synthetic_form.review.md").read_text(encoding="utf-8")
    assert review["form_id"] in markdown
    assert review["fields"][0]["field_id"] in markdown
    assert "confirmed_zero_fields" in markdown
    assert "detector found nothing" in markdown
    assert "one logical text field" in markdown
    assert "JSON is authoritative" in markdown
    assert "UNSCORED" in (packet_root / "index.html").read_text(encoding="utf-8")
    first_hashes = _file_hashes(root)
    _generate(root, paths)
    assert _file_hashes(root) == first_hashes
    assert sha256_file(paths["pdf"]) == before_pdf
    assert sha256_file(paths["gt"]) == before_gt
    assert sha256_file(paths["manifest"]) == before_manifest


def test_untouched_legacy_review_template_upgrades_document_decision(tmp_path):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path = root / "reviews" / "synthetic_form.review.json"
    review = load_json(review_path)
    review.pop("document_decision")
    legacy_review = copy.deepcopy(review)
    write_json(review_path, review)

    _generate(root, paths)
    upgraded = load_json(review_path)
    document_decision = upgraded.pop("document_decision")

    assert document_decision == "pending"
    assert upgraded == legacy_review
    markdown = (root / "reviews" / "synthetic_form.review.md").read_text(encoding="utf-8")
    assert "confirmed_zero_fields" in markdown


def test_owner_edited_legacy_review_template_is_not_upgraded(tmp_path):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path = root / "reviews" / "synthetic_form.review.json"
    review = load_json(review_path)
    review.pop("document_decision")
    review["reviewer"] = "Owner edit must survive"
    write_json(review_path, review)

    with pytest.raises(PacketError, match="Refusing to upgrade owner-edited"):
        _generate(root, paths)
    assert load_json(review_path) == review


def test_ocr_demo_skips_without_tesseract_and_keeps_warning(tmp_path, monkeypatch):
    root, paths = _mini_repo(tmp_path)
    entry = {
        "id": "synthetic_form",
        "privacy_status": "synthetic",
        "_pdf_path": paths["pdf"],
        "_gt_path": paths["gt"],
    }
    monkeypatch.setattr(generate_review_packets.shutil, "which", lambda _name: None)
    status = generate_review_packets.generate_ocr_demo(
        root,
        [entry],
        root / "reports" / "ocr_demo",
        "test-sha",
    )
    assert status["ocr_execution"] == "skipped_missing_tesseract"
    assert (root / "reports" / "ocr_demo" / "environment_gap.md").is_file()
    assert (root / "reports" / "ocr_demo" / "synthetic_form" / "skew_3deg.png").is_file()
    assert "UNSCORED OCR DEMONSTRATION" in (root / "reports" / "ocr_demo" / "index.html").read_text(encoding="utf-8")
    assert not list((root / "reports" / "ocr_demo").rglob("tesseract_words.png"))


def test_apply_refuses_pending_blank_identity_and_bad_hashes(tmp_path):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path = root / "reviews" / "synthetic_form.review.json"
    with pytest.raises(PacketError, match="reviewer"):
        apply_gt_review.apply_review_candidate(review_path, root)
    review = load_json(review_path)
    review["reviewer"] = "Synthetic Test Reviewer"
    write_json(review_path, review)
    with pytest.raises(PacketError, match="reviewed_at"):
        apply_gt_review.apply_review_candidate(review_path, root)
    review["reviewed_at"] = "2026-08-10"
    write_json(review_path, review)
    with pytest.raises(PacketError, match="pending"):
        apply_gt_review.apply_review_candidate(review_path, root)
    review["fields"][0]["decision"] = "accept"
    review["source_gt_sha256"] = "0" * 64
    write_json(review_path, review)
    with pytest.raises(PacketError, match="source GT hash mismatch"):
        apply_gt_review.apply_review_candidate(review_path, root)
    review["source_gt_sha256"] = sha256_file(paths["gt"])
    review["source_pdf_sha256"] = "0" * 64
    write_json(review_path, review)
    with pytest.raises(PacketError, match="source PDF hash mismatch"):
        apply_gt_review.apply_review_candidate(review_path, root)


def test_untouched_zero_field_template_fails(tmp_path):
    root, _paths = _zero_field_repo(tmp_path)
    review_path = root / "reviews" / "synthetic_form.review.json"

    with pytest.raises(PacketError, match="reviewer must not be blank"):
        apply_gt_review.apply_review_candidate(review_path, root)


def test_zero_field_reviewer_and_date_requires_affirmative_document_decision(tmp_path):
    root, _paths = _zero_field_repo(tmp_path)
    review_path, _review = _completed_zero_field_review(root)

    with pytest.raises(
        PacketError,
        match="Zero-field reviews require document_decision=confirmed_zero_fields",
    ):
        apply_gt_review.apply_review_candidate(review_path, root)


def test_populated_source_all_deleted_requires_affirmative_document_decision(tmp_path):
    root, _paths, review_path, review = _populated_two_field_review(
        tmp_path,
        document_decision="pending",
    )

    assert len(review["fields"]) == 2
    assert {row["decision"] for row in review["fields"]} == {"delete"}
    assert review["additions"] == []
    with pytest.raises(
        PacketError,
        match="Zero-field reviews require document_decision=confirmed_zero_fields",
    ):
        apply_gt_review.apply_review_candidate(review_path, root)
    assert not (root / "reviews" / "output").exists()


def test_populated_source_all_deleted_with_confirmation_creates_zero_field_candidate(
    tmp_path,
):
    root, paths, review_path, review = _populated_two_field_review(
        tmp_path,
        document_decision="confirmed_zero_fields",
    )
    source_gt_before = paths["gt"].read_bytes()

    result = apply_gt_review.apply_review_candidate(review_path, root)
    candidate = load_json(result["candidate_path"])
    overlay_html = (result["overlay_dir"] / "index.html").read_text(encoding="utf-8")
    output_dir = root / "reviews" / "output"

    assert len(review["fields"]) == 2
    assert {row["decision"] for row in review["fields"]} == {"delete"}
    assert review["additions"] == []
    assert result["status"] == "human_review_candidate"
    assert candidate["fields"] == []
    assert candidate["provenance"]["document_decision"] == "confirmed_zero_fields"
    assert "ZERO FILLABLE FIELDS AFFIRMATIVELY CONFIRMED" in overlay_html
    assert "NOT YET APPROVED" in overlay_html
    assert paths["gt"].read_bytes() == source_gt_before
    assert not list(output_dir.glob("*_human_reviewed.json"))
    assert not list(output_dir.rglob("*locked*"))


def test_explicit_zero_field_decision_creates_candidate_and_affirmative_overlay(
    tmp_path,
    monkeypatch,
):
    root, _paths = _zero_field_repo(tmp_path)
    review_path, _review = _completed_zero_field_review(
        root,
        document_decision="confirmed_zero_fields",
    )
    banner_calls = []
    original_add_banner = apply_gt_review.add_banner

    def capture_banner(image, title, subtitle="", footer=""):
        banner_calls.append((title, subtitle, footer))
        return original_add_banner(image, title, subtitle, footer)

    monkeypatch.setattr(apply_gt_review, "add_banner", capture_banner)
    result = apply_gt_review.apply_review_candidate(review_path, root)
    candidate = load_json(result["candidate_path"])
    overlay_html = (result["overlay_dir"] / "index.html").read_text(encoding="utf-8")

    assert result["status"] == "human_review_candidate"
    assert candidate["fields"] == []
    assert candidate["provenance"]["document_decision"] == "confirmed_zero_fields"
    assert any(
        "ZERO FILLABLE FIELDS AFFIRMATIVELY CONFIRMED" in title
        and "NOT YET APPROVED" in footer
        for title, _subtitle, footer in banner_calls
    )
    assert "ZERO FILLABLE FIELDS AFFIRMATIVELY CONFIRMED" in overlay_html
    assert "NOT YET APPROVED" in overlay_html


def test_confirmed_zero_fields_with_addition_is_rejected(tmp_path):
    root, _paths = _zero_field_repo(tmp_path)
    review_path, review = _completed_zero_field_review(
        root,
        document_decision="confirmed_zero_fields",
    )
    review["additions"] = [_valid_addition()]
    write_json(review_path, review)

    with pytest.raises(PacketError, match="contradicts nonempty additions"):
        apply_gt_review.apply_review_candidate(review_path, root)


def test_zero_source_fields_with_addition_succeeds_without_zero_confirmation(tmp_path):
    root, _paths = _zero_field_repo(tmp_path)
    review_path, review = _completed_zero_field_review(root)
    review["additions"] = [_valid_addition()]
    write_json(review_path, review)

    result = apply_gt_review.apply_review_candidate(review_path, root)
    candidate = load_json(result["candidate_path"])
    overlay_html = (result["overlay_dir"] / "index.html").read_text(encoding="utf-8")

    assert [field["id"] for field in candidate["fields"]] == ["added1"]
    assert candidate["provenance"]["document_decision"] == "pending"
    assert "ZERO FILLABLE FIELDS AFFIRMATIVELY CONFIRMED" not in overlay_html


def test_approval_rechecks_current_zero_field_review_decision(tmp_path):
    root, _paths = _zero_field_repo(tmp_path)
    review_path, review = _completed_zero_field_review(
        root,
        document_decision="confirmed_zero_fields",
    )
    result = apply_gt_review.apply_review_candidate(review_path, root)
    review["document_decision"] = "pending"
    write_json(review_path, review)

    with pytest.raises(
        PacketError,
        match="Zero-field reviews require document_decision=confirmed_zero_fields",
    ):
        apply_gt_review.approve_candidate(
            review_path,
            result["confirmation_token"],
            True,
            root,
        )
    assert not list((root / "reviews" / "output").glob("*_human_reviewed.json"))


def test_approval_rejects_tampered_zero_field_candidate_provenance(tmp_path):
    root, paths = _zero_field_repo(tmp_path)
    review_path, _review = _completed_zero_field_review(
        root,
        document_decision="confirmed_zero_fields",
    )
    result = apply_gt_review.apply_review_candidate(review_path, root)
    candidate = load_json(result["candidate_path"])
    candidate["provenance"]["document_decision"] = "pending"
    write_json(result["candidate_path"], candidate)
    tampered_binding = confirmation_binding(
        "synthetic_form",
        sha256_file(paths["pdf"]),
        sha256_file(paths["gt"]),
        sha256_file(review_path),
        sha256_file(result["candidate_path"]),
    )

    with pytest.raises(
        PacketError,
        match="candidate provenance document_decision=confirmed_zero_fields",
    ):
        apply_gt_review.approve_candidate(
            review_path,
            confirmation_token(tampered_binding),
            True,
            root,
        )
    assert not list((root / "reviews" / "output").glob("*_human_reviewed.json"))


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda review: review["fields"][0].update({"decision": "update", "new_geometry": [220, 300, 40, 40]}), "extends beyond"),
        (lambda review: review["fields"][0].update({"decision": "update", "new_type": "unsupported"}), "must be one of"),
        (lambda review: review.update({"additions": [{"field_id": "new1", "page": 2, "type": "text", "geometry": [1, 1, 10, 10], "label": "X", "comment": "synthetic"}]}), "invalid page"),
        (lambda review: review["fields"].append(copy.deepcopy(review["fields"][0])), "Duplicate review field id"),
    ],
)
def test_apply_rejects_invalid_geometry_type_page_and_ids(tmp_path, mutator, message):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path, review = _completed_review(root)
    mutator(review)
    write_json(review_path, review)
    with pytest.raises(PacketError, match=message):
        apply_gt_review.apply_review_candidate(review_path, root)


def test_candidate_generation_is_separate_and_approval_is_gated(tmp_path):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path, _review = _completed_review(root)
    gt_hash = sha256_file(paths["gt"])
    result = apply_gt_review.apply_review_candidate(review_path, root)
    candidate = load_json(result["candidate_path"])
    assert result["status"] == "human_review_candidate"
    assert candidate["review_status"] == "human_review_candidate"
    assert candidate["needs_review"] is True
    assert (result["overlay_dir"] / "index.html").is_file()
    assert sha256_file(paths["gt"]) == gt_hash
    assert not list((root / "reviews" / "output").glob("*_human_reviewed.json"))
    with pytest.raises(PacketError, match="owner assertion"):
        apply_gt_review.approve_candidate(review_path, result["confirmation_token"], False, root)
    with pytest.raises(PacketError, match="invalid confirmation token"):
        apply_gt_review.approve_candidate(review_path, "not-the-token", True, root)
    binding = confirmation_binding("synthetic_form", "a", "b", "c", "d")
    assert confirmation_token(binding) != confirmation_token({**binding, "candidate_output_sha256": "changed"})
    with pytest.raises(PacketError, match="review output"):
        apply_gt_review.apply_review_candidate(review_path, root, output_dir=paths["gt"].parent)


def test_missing_review_annotations_is_backward_compatible(tmp_path):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path, review = _completed_review(root)
    review.pop("review_annotations", None)
    write_json(review_path, review)

    context = apply_gt_review.load_review_context(review_path, root)
    validated = validate_review(review, context["source_gt"], context["page_sizes"])
    result = apply_gt_review.apply_review_candidate(review_path, root)
    candidate = load_json(result["candidate_path"])

    assert validated["review_annotations"] == {}
    assert "review_annotations" not in candidate
    assert candidate["fields"] == validated["fields"]


def test_valid_ruled_multiline_annotation_is_normalized():
    review, source_gt, page_sizes = _annotation_validation_case()

    validated = validate_review(review, source_gt, page_sizes)

    assert validated["review_annotations"] == review["review_annotations"]

    del review["review_annotations"]["text1"]["max_words"]
    without_limit = validate_review(review, source_gt, page_sizes)
    assert "max_words" not in without_limit["review_annotations"]["text1"]


def test_annotation_on_owner_added_text_field_is_preserved_separately(tmp_path):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path, _review = _completed_annotated_review(root)

    result = apply_gt_review.apply_review_candidate(review_path, root)
    candidate = load_json(result["candidate_path"])
    summary = next(field for field in candidate["fields"] if field["id"] == "summary")

    assert len(candidate["fields"]) == 2
    assert all("review_annotations" not in field for field in candidate["fields"])
    assert candidate["review_annotations"]["summary"]["line_count"] == 14
    assert candidate["provenance"]["review_annotations"]["source"] == "owner_supplied_review_metadata"
    assert candidate["provenance"]["review_annotations"]["field_ids"] == ["summary"]


@pytest.mark.parametrize(
    "case, message",
    [
        ("top_level_array", "must be an object"),
        ("unknown_field", "unknown or deleted field"),
        ("deleted_field", "unknown or deleted field"),
        ("checkbox", "only valid for text"),
        ("signature", "only valid for text"),
        ("unknown_kind", "kind must equal ruled_multiline"),
        ("line_count_zero", "line_count must be a positive integer"),
        ("guide_count_mismatch", "line_count must equal"),
        ("unsorted", "strictly increasing"),
        ("duplicate_y", "duplicate or effectively duplicate"),
        ("outside_x1", "x1 lies outside"),
        ("outside_x2", "x2 lies outside"),
        ("outside_y", "y lies outside"),
        ("reversed", "x2 must be greater than x1"),
        ("nan", "non-finite"),
        ("infinity", "non-finite"),
        ("wrap_false", "wrap must be true"),
        ("vertical_center", "vertical_align must equal top"),
        ("max_words_zero", "max_words must be a positive integer"),
        ("unknown_annotation_key", "unknown keys"),
        ("unknown_guide_key", "guide has unknown keys"),
    ],
)
def test_invalid_review_annotations_fail_loudly(case, message):
    review, source_gt, page_sizes = _annotation_validation_case()
    annotations = review["review_annotations"]
    annotation = annotations["text1"]
    guides = annotation["line_guides"]

    if case == "top_level_array":
        review["review_annotations"] = []
    elif case == "unknown_field":
        annotations["missing"] = annotations.pop("text1")
    elif case == "deleted_field":
        review["fields"][0]["decision"] = "delete"
    elif case == "checkbox":
        annotations["check1"] = annotations.pop("text1")
    elif case == "signature":
        annotations["signature1"] = annotations.pop("text1")
    elif case == "unknown_kind":
        annotation["kind"] = "other"
    elif case == "line_count_zero":
        annotation["line_count"] = 0
    elif case == "guide_count_mismatch":
        annotation["line_count"] = 3
    elif case == "unsorted":
        annotation["line_guides"] = list(reversed(guides))
    elif case == "duplicate_y":
        guides[1]["y"] = 50.01
    elif case == "outside_x1":
        guides[0]["x1"] = 19.9
    elif case == "outside_x2":
        guides[0]["x2"] = 200.1
    elif case == "outside_y":
        guides[1]["y"] = 120.1
    elif case == "reversed":
        guides[0]["x2"] = guides[0]["x1"]
    elif case == "nan":
        guides[0]["x1"] = float("nan")
    elif case == "infinity":
        guides[0]["x2"] = float("inf")
    elif case == "wrap_false":
        annotation["wrap"] = False
    elif case == "vertical_center":
        annotation["vertical_align"] = "center"
    elif case == "max_words_zero":
        annotation["max_words"] = 0
    elif case == "unknown_annotation_key":
        annotation["extra"] = True
    elif case == "unknown_guide_key":
        guides[0]["extra"] = True
    else:
        raise AssertionError(f"Unhandled case: {case}")

    with pytest.raises(PacketError, match=message):
        validate_review(review, source_gt, page_sizes)


def test_annotation_change_updates_candidate_hash_and_invalidates_old_token(tmp_path):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path, review = _completed_annotated_review(root)
    first = apply_gt_review.apply_review_candidate(review_path, root)
    first_candidate_hash = first["candidate_sha256"]
    first_token = first["confirmation_token"]

    review["review_annotations"]["summary"]["line_guides"][0]["y"] += 1
    write_json(review_path, review)
    with pytest.raises(PacketError):
        apply_gt_review.approve_candidate(review_path, first_token, True, root)

    second = apply_gt_review.apply_review_candidate(review_path, root)
    assert second["candidate_sha256"] != first_candidate_hash
    assert second["confirmation_token"] != first_token
    assert not list((root / "reviews" / "output").glob("*_human_reviewed.json"))


def test_approval_rejects_annotation_tampering_with_recomputed_token(tmp_path):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path, _review = _completed_annotated_review(root)
    result = apply_gt_review.apply_review_candidate(review_path, root)
    candidate = load_json(result["candidate_path"])
    candidate["review_annotations"]["summary"]["max_words"] = 999
    write_json(result["candidate_path"], candidate)
    tampered_binding = confirmation_binding(
        "synthetic_form",
        sha256_file(paths["pdf"]),
        sha256_file(paths["gt"]),
        sha256_file(review_path),
        sha256_file(result["candidate_path"]),
    )

    with pytest.raises(PacketError, match="review_annotations do not match"):
        apply_gt_review.approve_candidate(
            review_path,
            confirmation_token(tampered_binding),
            True,
            root,
        )
    assert not list((root / "reviews" / "output").glob("*_human_reviewed.json"))


def test_ruled_multiline_candidate_overlay_renders_guides_and_labels(
    tmp_path,
    monkeypatch,
):
    root, paths = _mini_repo(tmp_path)
    _generate(root, paths)
    review_path, _review = _completed_annotated_review(root)
    guide_calls = []
    field_calls = []
    original_dashed_line = review_packet_schema._draw_dashed_line
    original_field_overlay = apply_gt_review.draw_field_overlay

    def capture_guide(*args, **kwargs):
        guide_calls.append((args, kwargs))
        return original_dashed_line(*args, **kwargs)

    def capture_fields(base_image, fields, *args, **kwargs):
        field_calls.extend(copy.deepcopy(fields))
        return original_field_overlay(base_image, fields, *args, **kwargs)

    monkeypatch.setattr(review_packet_schema, "_draw_dashed_line", capture_guide)
    monkeypatch.setattr(apply_gt_review, "draw_field_overlay", capture_fields)
    result = apply_gt_review.apply_review_candidate(review_path, root)
    overlay_html = (result["overlay_dir"] / "index.html").read_text(encoding="utf-8")

    assert any(field["id"] == "summary" and field["bbox"] == [24.0, 120.0, 190.0, 160.0] for field in field_calls)
    assert len(guide_calls) == 14
    assert "MULTILINE" in overlay_html
    assert "14 RULED LINES" in overlay_html
    assert "ONE LOGICAL FIELD" in overlay_html
    assert "NOT APPROVED" in overlay_html
