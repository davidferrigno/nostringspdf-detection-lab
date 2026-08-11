#!/usr/bin/env python3
"""Generate deterministic, unscored visual review packets for LAB-PACKET-1."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True

from review_packet_schema import (
    COMBINED_BANNER,
    DETECTOR_BANNER,
    DRAFT_BANNER,
    FIELD_SCHEMA_VERSION,
    GENERATOR_VERSION,
    OCR_BANNER,
    OVERLAP_NOTICE,
    PACKET_STATUS,
    PacketError,
    add_banner,
    assert_within,
    build_overlap_hints,
    build_review_template,
    detector_table,
    draft_table,
    draw_combined_overlay,
    draw_field_overlay,
    html_page,
    html_table,
    infer_gt_provenance,
    load_json,
    normalize_bbox,
    render_pdf_pages,
    repo_relative,
    review_markdown,
    safe_form_id,
    sanitize_text,
    save_png,
    sha256_file,
    validate_field_id,
    validate_field_type,
    validate_geometry,
    validate_gt,
    write_json,
    write_text,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUEUE = ROOT / "reports" / "gt_review_queue" / "QUEUE.md"
DEFAULT_MANIFEST = ROOT / "corpus" / "manifest.json"
DEFAULT_OUT = ROOT / "reports" / "review_packets"
DEFAULT_REVIEWS = ROOT / "reviews"
DEFAULT_OCR_OUT = ROOT / "reports" / "ocr_demo"
ALLOWED_PRIVACY = {"blank", "synthetic"}
PACKET_SCHEMA_VERSION = "1.0"
RENDER_DPI = 200


def deterministic_timestamp(paths: list[Path]) -> str:
    latest = max(path.stat().st_mtime for path in paths if path.exists())
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat(timespec="seconds")


def repository_sha(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def parse_queue_ids(queue_path: Path) -> list[str]:
    text = queue_path.read_text(encoding="utf-8")
    ids = re.findall(r"^## Entry\s+\d+\s+[\u2014-]\s+([a-z0-9_]+)", text, re.MULTILINE)
    if not ids:
        ids = re.findall(r"^\|\s*\d+\s*\|\s*\*\*([a-z0-9_]+)\*\*\s*\|", text, re.MULTILINE)
    if not ids:
        raise PacketError(f"No ordered form ids found in review queue: {queue_path}")
    if len(ids) != len(set(ids)):
        raise PacketError("Review queue contains duplicate form ids")
    return [safe_form_id(value) for value in ids]


def _resolve_entry_paths(entry: dict[str, Any], repo_root: Path) -> tuple[Path, Path]:
    pdf_value = entry.get("path") or entry.get("filename")
    gt_value = entry.get("ground_truth_path")
    if not pdf_value or not gt_value:
        raise PacketError(f"Manifest entry {entry.get('id')} lacks PDF or GT path")
    pdf_path = assert_within(repo_root / pdf_value, repo_root, "source PDF")
    gt_path = assert_within(repo_root / gt_value, repo_root, "source GT")
    if not pdf_path.is_file() or not gt_path.is_file():
        raise PacketError(f"Missing PDF or GT for {entry.get('id')}")
    return pdf_path, gt_path


def load_queue_entries(
    repo_root: Path,
    queue_path: Path,
    manifest_path: Path,
) -> list[dict[str, Any]]:
    ids = parse_queue_ids(queue_path)
    manifest = load_json(manifest_path)
    entries = manifest.get("entries", [])
    by_id: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_id.setdefault(str(entry.get("id")), []).append(entry)
    selected = []
    for priority, form_id in enumerate(ids, start=1):
        matches = by_id.get(form_id, [])
        if len(matches) != 1:
            raise PacketError(f"Queue id {form_id} has {len(matches)} manifest entries")
        entry = dict(matches[0])
        privacy = sanitize_text(entry.get("privacy_status"))
        if privacy not in ALLOWED_PRIVACY:
            raise PacketError(f"Queue id {form_id} has disallowed privacy_status {privacy!r}")
        pdf_path, gt_path = _resolve_entry_paths(entry, repo_root)
        entry["_priority"] = priority
        entry["_pdf_path"] = pdf_path
        entry["_gt_path"] = gt_path
        selected.append(entry)
    return selected


def load_backend(
    repo_root: Path,
    backend_id: str,
) -> tuple[Callable[[Path], list[dict[str, Any]]], dict[str, Any]]:
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import backend_registry

    metadata = dict(backend_registry.get_backend_metadata(backend_id))
    if "B" not in metadata.get("lanes", []):
        raise PacketError(f"Backend {backend_id} is not declared for Lane B")
    fn = metadata.pop("fn")
    metadata["backend_id"] = backend_id
    metadata["production_equivalent"] = False
    metadata["parity_note"] = "Runnable lab backend; no production parity is claimed."
    metadata["configuration"] = {"deterministic_defaults": True}
    return fn, metadata


def normalize_detector_fields(
    raw_fields: Any,
    page_sizes: dict[int, tuple[float, float]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_fields, list):
        raise PacketError("Detector output must be a list")
    normalized = []
    seen: set[str] = set()
    for index, field in enumerate(raw_fields, start=1):
        if not isinstance(field, dict):
            raise PacketError(f"Detector item {index} is not an object")
        candidate_id = sanitize_text(field.get("id")) or f"candidate_{index}"
        try:
            candidate_id = validate_field_id(candidate_id, f"Detector item {index} id")
        except PacketError:
            candidate_id = f"candidate_{index}"
        if candidate_id in seen:
            candidate_id = f"candidate_{index}"
        seen.add(candidate_id)
        try:
            page = int(field.get("page"))
        except (TypeError, ValueError) as exc:
            raise PacketError(f"Detector item {candidate_id} has invalid page") from exc
        field_type = validate_field_type(field.get("type"), f"Detector item {candidate_id} type")
        bbox = validate_geometry(field.get("bbox"), page, page_sizes, f"Detector item {candidate_id} bbox")
        row = {
            "id": candidate_id,
            "candidate_id": candidate_id,
            "page": page,
            "type": field_type,
            "proposed_type": field_type,
            "label": sanitize_text(field.get("label")) or None,
            "proposed_label": sanitize_text(field.get("label")) or None,
            "bbox": bbox,
        }
        for source_key, target_key in (
            ("confidence", "raw_confidence"),
            ("_confidence", "raw_confidence"),
            ("rule", "rule"),
            ("_rule", "rule"),
            ("provenance", "candidate_provenance"),
            ("_source", "candidate_provenance"),
        ):
            if field.get(source_key) is not None and target_key not in row:
                row[target_key] = field.get(source_key)
        normalized.append(row)
    normalized.sort(key=lambda row: (row["page"], row["bbox"][1], row["bbox"][0], row["id"]))
    return normalized


def _source_image(page: dict[str, Any]):
    from PIL import ImageDraw

    image = page["image"].convert("RGB").copy()
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, image.width - 1, image.height - 1], outline=(65, 72, 82), width=3)
    return add_banner(
        image,
        "SOURCE PAGE - UNSCORED REVIEW EVIDENCE",
        f"Page {page['page']} | top-left origin | PDF points",
        f"Rendered at {page['dpi']} DPI | {page['pdf_width']} x {page['pdf_height']} points",
    )


def _review_companion(review: dict[str, Any]) -> str:
    form_id = review["form_id"]
    base = review_markdown(review)
    return base + "\n" + "\n".join([
        "## Review instructions",
        "",
        "1. Edit the JSON review file, not this generated Markdown companion.",
        "2. Resolve every pending field as accept, update, or delete.",
        "3. Add reviewer and reviewed_at in ISO-8601 format.",
        "4. Leave document_decision pending unless source inspection affirmatively confirms zero fillable fields.",
        "5. If fillable regions exist, record additions with field_id, page, type, geometry, label, and comment.",
        "6. Generate a candidate without approval:",
        "",
        f"`python scripts/apply_gt_review.py --review reviews/{form_id}.review.json`",
        "",
        "7. Inspect every page of the candidate confirmation overlay.",
        "8. Only the owner may run the separate approval command with the printed token and inspection assertion.",
        "",
    ])


def ensure_review_template(
    review_path: Path,
    markdown_path: Path,
    form_manifest: dict[str, Any],
) -> dict[str, Any]:
    if review_path.exists():
        review = load_json(review_path)
        expected = {
            "form_id": form_manifest["form_id"],
            "source_pdf_sha256": form_manifest["source_pdf_sha256"],
            "source_gt_sha256": form_manifest["gt_sha256"],
        }
        for key, value in expected.items():
            if review.get(key) != value:
                raise PacketError(f"Existing review template {review_path} is stale at {key}")
        if "document_decision" not in review:
            expected_template = build_review_template(form_manifest)
            legacy_template = dict(expected_template)
            legacy_template.pop("document_decision")
            if review != legacy_template:
                raise PacketError(
                    f"Refusing to upgrade owner-edited review template {review_path}"
                )
            output_dir = review_path.parent / "output"
            protected_outputs = [
                output_dir / f"{form_manifest['form_id']}_review_candidate.json",
                output_dir / f"{form_manifest['form_id']}_review_candidate_overlay",
                output_dir / f"{form_manifest['form_id']}_human_reviewed.json",
            ]
            if any(path.exists() for path in protected_outputs):
                raise PacketError(
                    f"Refusing to upgrade review template with candidate or approval output: {review_path}"
                )
            review = expected_template
            write_json(review_path, review)
    else:
        review = build_review_template(form_manifest)
        write_json(review_path, review)
    write_text(markdown_path, _review_companion(review))
    return review


def _form_html(
    manifest: dict[str, Any],
    review_path: Path,
    markdown_path: Path,
    repo_root: Path,
) -> str:
    provenance = manifest["gt_provenance"]["display"]
    backend_id = manifest["backend"]["backend_id"]
    page_sections = []
    for page in manifest["pages"]:
        page_sections.append(
            f"<h2>Page {page['page']}</h2><div class=\"layers\">"
            f"<figure><figcaption>Source</figcaption><img src=\"{page['source']}\" alt=\"Source page {page['page']}\"></figure>"
            f"<figure><figcaption>Draft GT</figcaption><img src=\"{page['draft_gt']}\" alt=\"Draft overlay page {page['page']}\"></figure>"
            f"<figure><figcaption>Detector candidates</figcaption><img src=\"{page['detector']}\" alt=\"Detector overlay page {page['page']}\"></figure>"
            f"<figure><figcaption>Combined navigation</figcaption><img src=\"{page['combined']}\" alt=\"Combined review view page {page['page']}\"></figure>"
            "</div>"
        )
    draft_rows = [
        [row["field_id"], row["page"], row["declared_type"], row.get("label"), row["bbox"], row["provenance"], row["current_review_status"]]
        for row in manifest["draft_gt"]["fields"]
    ]
    detector_rows = [
        [row["candidate_id"], row["page"], row["proposed_type"], row.get("proposed_label"), row["bbox"], row.get("raw_confidence"), row.get("rule") or row.get("candidate_provenance")]
        for row in manifest["detector"]["candidates"]
    ]
    overlap_rows = [
        [row.get("draft_field_id"), row.get("linked_detector_candidate_ids"), row.get("detector_candidate_id"), row.get("linked_draft_field_ids"), row["overlap_category"], row["presentation_threshold"]]
        for row in manifest["overlap_hints"]["rows"]
    ]
    body = f"""
<div class="warning">{PACKET_STATUS}. Zero packet content is authoritative ground truth. Detector output is context, not truth.</div>
<dl class="meta">
  <dt>Form ID</dt><dd><code>{manifest['form_id']}</code></dd>
  <dt>Source PDF</dt><dd><code>{manifest['source_pdf']}</code></dd>
  <dt>Source SHA-256</dt><dd><code>{manifest['source_pdf_sha256']}</code></dd>
  <dt>Draft GT</dt><dd><code>{manifest['gt_path']}</code></dd>
  <dt>GT SHA-256</dt><dd><code>{manifest['gt_sha256']}</code></dd>
  <dt>GT provenance</dt><dd>{provenance}</dd>
  <dt>GT review status</dt><dd>{manifest['gt_review_status']}</dd>
  <dt>Backend</dt><dd><code>{backend_id}</code> ({manifest['backend']['parity_note']})</dd>
  <dt>Render</dt><dd>{manifest['render_dpi']} DPI, top-left origin, points to pixels using scale {manifest['coordinate_transform']['scale_px_per_point']}</dd>
  <dt>Generation command</dt><dd><code>{manifest['generation_command']}</code></dd>
</dl>
<p><a href="../../../{repo_relative(review_path, repo_root)}">Review JSON</a> | <a href="../../../{repo_relative(markdown_path, repo_root)}">Review Markdown</a> | <a href="form_manifest.json">Form manifest</a></p>
<div class="legend"><span>Blue: draft GT</span><span>Orange: detector candidate</span><span>Teal: overlap candidate</span></div>
{''.join(page_sections)}
<h2>Draft fields</h2>{html_table(['Field','Page','Type','Label','Geometry','Provenance','Review status'], draft_rows)}
<h2>Detector candidates</h2>{html_table(['Candidate','Page','Proposed type','Proposed label','Geometry','Raw confidence','Rule/provenance'], detector_rows)}
<h2>Neutral overlap navigation</h2><p>{OVERLAP_NOTICE}</p>{html_table(['Draft','Linked candidates','Candidate','Linked drafts','Category','Threshold'], overlap_rows)}
"""
    return html_page(f"Review packet: {manifest['form_id']}", body)


def generate_form_packet(
    repo_root: Path,
    entry: dict[str, Any],
    out_dir: Path,
    reviews_dir: Path,
    backend_fn: Callable[[Path], list[dict[str, Any]]],
    backend_metadata: dict[str, Any],
    repo_sha: str,
    dpi: int,
    generation_command: str,
) -> dict[str, Any]:
    form_id = safe_form_id(str(entry["id"]))
    pdf_path: Path = entry["_pdf_path"]
    gt_path: Path = entry["_gt_path"]
    gt = load_json(gt_path)
    provenance = infer_gt_provenance(gt)
    pages = render_pdf_pages(pdf_path, dpi)
    page_sizes = {page["page"]: (page["pdf_width"], page["pdf_height"]) for page in pages}
    validate_gt(gt, page_sizes)

    raw_fields = backend_fn(pdf_path)
    detector_fields = normalize_detector_fields(raw_fields, page_sizes)
    overlap_hints = build_overlap_hints(gt["fields"], detector_fields)

    form_dir = assert_within(out_dir / form_id, out_dir, "form packet directory")
    if form_dir.exists():
        shutil.rmtree(form_dir)
    form_dir.mkdir(parents=True)
    tables_dir = form_dir / "tables"
    tables_dir.mkdir()
    backend_id = backend_metadata["backend_id"]
    draft_payload = draft_table(gt, provenance)
    detector_payload = detector_table(detector_fields, backend_id, repo_sha)
    detector_payload["candidates"] = detector_fields
    write_json(tables_dir / "draft_gt.json", draft_payload)
    write_json(tables_dir / f"detector_{backend_id}_raw.json", raw_fields)
    write_json(tables_dir / f"detector_{backend_id}.json", detector_payload)
    write_json(tables_dir / "overlap_hints.json", overlap_hints)

    page_artifacts = []
    for page in pages:
        page_number = page["page"]
        name = f"page_{page_number:03d}.png"
        page_draft = [field for field in gt["fields"] if int(field["page"]) == page_number]
        page_detector = [field for field in detector_fields if field["page"] == page_number]
        source_path = form_dir / "source" / name
        draft_path = form_dir / "draft_gt" / name
        detector_path = form_dir / f"detector_{backend_id}" / name
        combined_path = form_dir / "combined" / name
        save_png(_source_image(page), source_path)
        draft_image = draw_field_overlay(page["image"], page_draft, page["scale_px_per_point"], (0, 102, 204))
        save_png(add_banner(draft_image, DRAFT_BANNER, provenance["display"]), draft_path)
        detector_image = draw_field_overlay(page["image"], page_detector, page["scale_px_per_point"], (230, 103, 35), label_prefix="")
        save_png(add_banner(detector_image, DETECTOR_BANNER.format(backend_id=backend_id), f"Lab SHA {repo_sha[:12]} | schema {FIELD_SCHEMA_VERSION}"), detector_path)
        combined_image = draw_combined_overlay(page["image"], page_draft, page_detector, overlap_hints, page["scale_px_per_point"])
        save_png(add_banner(combined_image, COMBINED_BANNER, "Blue draft | orange detector | teal overlap candidate", OVERLAP_NOTICE), combined_path)
        page_artifacts.append({
            "page": page_number,
            "source": f"source/{name}",
            "draft_gt": f"draft_gt/{name}",
            "detector": f"detector_{backend_id}/{name}",
            "combined": f"combined/{name}",
            "pdf_size_points": [page["pdf_width"], page["pdf_height"]],
            "image_size_pixels": [page["image_width"], page["image_height"]],
        })

    source_hash = sha256_file(pdf_path)
    gt_hash = sha256_file(gt_path)
    form_manifest_path = form_dir / "form_manifest.json"
    review_path = reviews_dir / f"{form_id}.review.json"
    markdown_path = reviews_dir / f"{form_id}.review.md"
    timestamp = deterministic_timestamp([pdf_path, gt_path, Path(__file__), Path(__file__).with_name("review_packet_schema.py")])
    manifest = {
        "packet_schema_version": PACKET_SCHEMA_VERSION,
        "packet_generator_version": GENERATOR_VERSION,
        "packet_status": PACKET_STATUS,
        "form_id": form_id,
        "queue_priority": entry["_priority"],
        "lab_repository_sha": repo_sha,
        "source_pdf": repo_relative(pdf_path, repo_root),
        "source_pdf_sha256": source_hash,
        "gt_path": repo_relative(gt_path, repo_root),
        "gt_sha256": gt_hash,
        "gt_provenance": provenance,
        "gt_review_status": sanitize_text(gt.get("review_status")) or "unknown",
        "backend": backend_metadata,
        "render_dpi": dpi,
        "page_count": len(pages),
        "source_page_dimensions": [item["pdf_size_points"] for item in page_artifacts],
        "coordinate_transform": {
            "origin": "top-left",
            "input_units": "PDF points",
            "output_units": "pixels",
            "scale_px_per_point": round(dpi / 72.0, 8),
            "formula": "pixel = point * dpi / 72",
        },
        "generation_timestamp": timestamp,
        "generation_command": generation_command,
        "pages": page_artifacts,
        "draft_gt": {"fields": draft_payload["rows"]},
        "detector": {"candidates": detector_fields},
        "overlap_hints": overlap_hints,
        "artifacts": {
            "form_manifest": repo_relative(form_manifest_path, repo_root),
            "form_html": repo_relative(form_dir / "index.html", repo_root),
            "draft_table": repo_relative(tables_dir / "draft_gt.json", repo_root),
            "detector_raw": repo_relative(tables_dir / f"detector_{backend_id}_raw.json", repo_root),
            "detector_table": repo_relative(tables_dir / f"detector_{backend_id}.json", repo_root),
            "overlap_hints": repo_relative(tables_dir / "overlap_hints.json", repo_root),
            "review_json": repo_relative(review_path, repo_root),
            "review_markdown": repo_relative(markdown_path, repo_root),
        },
    }
    write_json(form_manifest_path, manifest)
    ensure_review_template(review_path, markdown_path, manifest)
    write_text(form_dir / "index.html", _form_html(manifest, review_path, markdown_path, repo_root))
    return manifest


def _ocr_variant_images(pdf_path: Path) -> dict[str, Any]:
    from PIL import Image

    page_300 = render_pdf_pages(pdf_path, 300)[0]["image"].convert("RGB")
    page_150 = render_pdf_pages(pdf_path, 150)[0]["image"].convert("RGB")
    skew = page_300.rotate(3, resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white")
    rng = random.Random(20260810)
    noise = Image.frombytes("L", page_300.size, rng.randbytes(page_300.width * page_300.height)).convert("RGB")
    mild_noise = Image.blend(page_300, noise, 0.08)
    jpeg_buffer = io.BytesIO()
    page_300.save(jpeg_buffer, format="JPEG", quality=40, optimize=False)
    jpeg_buffer.seek(0)
    jpeg_q40 = Image.open(jpeg_buffer).convert("RGB")
    return {
        "clean_300dpi": page_300,
        "clean_150dpi": page_150,
        "skew_3deg": skew,
        "mild_noise": mild_noise,
        "jpeg_q40": jpeg_q40,
    }


def _render_ocr_words(image, output_path: Path) -> dict[str, Any]:
    from PIL import ImageDraw
    import pytesseract

    data = pytesseract.image_to_data(image, config="--psm 6", output_type=pytesseract.Output.DICT)
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    words = []
    for index, text in enumerate(data.get("text", [])):
        clean = sanitize_text(text)
        if not clean:
            continue
        confidence = float(data["conf"][index])
        x, y, width, height = (int(data[key][index]) for key in ("left", "top", "width", "height"))
        shade = max(0, min(255, int(255 - max(confidence, 0) * 1.8)))
        draw.rectangle([x, y, x + width, y + height], outline=(shade, 80, 200), width=2)
        words.append({"text": clean, "confidence": confidence, "bbox_pixels": [x, y, width, height]})
    save_png(add_banner(overlay, OCR_BANNER, "Tesseract word boxes | --psm 6"), output_path)
    return {"configuration": "--psm 6", "words": words}


def generate_ocr_demo(
    repo_root: Path,
    entries: list[dict[str, Any]],
    ocr_out: Path,
    repo_sha: str,
) -> dict[str, Any]:
    ocr_out = assert_within(ocr_out, repo_root / "reports" / "ocr_demo", "OCR demo output")
    ocr_out.mkdir(parents=True, exist_ok=True)
    field_counts = []
    for entry in entries:
        gt = load_json(entry["_gt_path"])
        field_counts.append((len(gt.get("fields", [])), entry))
    simple = min(field_counts, key=lambda item: item[0])[1]
    dense = max(field_counts, key=lambda item: item[0])[1]
    selected = [("simple_sparse", simple), ("dense", dense)]
    executable = shutil.which("tesseract")
    pytesseract_available = importlib.util.find_spec("pytesseract") is not None
    ocr_available = bool(executable and pytesseract_available)
    forms = []
    image_sections = []
    for role, entry in selected:
        form_id = safe_form_id(str(entry["id"]))
        form_dir = ocr_out / form_id
        form_dir.mkdir(parents=True, exist_ok=True)
        variants = _ocr_variant_images(entry["_pdf_path"])
        paths = {}
        for variant, image in variants.items():
            path = form_dir / f"{variant}.png"
            save_png(add_banner(image, OCR_BANNER, f"{form_id} | page 1 | {variant}"), path)
            paths[variant] = repo_relative(path, repo_root)
        ocr_artifact = None
        if ocr_available:
            overlay_path = form_dir / "tesseract_words.png"
            result = _render_ocr_words(variants["clean_300dpi"], overlay_path)
            result["tesseract_version"] = str(__import__("pytesseract").get_tesseract_version())
            write_json(form_dir / "tesseract_words.json", result)
            ocr_artifact = repo_relative(overlay_path, repo_root)
        forms.append({
            "role": role,
            "form_id": form_id,
            "page": 1,
            "privacy_status": entry.get("privacy_status"),
            "selection_reason": "smallest draft field set" if role == "simple_sparse" else "largest draft field set",
            "variants": paths,
            "ocr_overlay": ocr_artifact,
        })
        figures = "".join(
            f'<figure><figcaption>{name}</figcaption><img src="{form_id}/{name}.png" alt="{form_id} {name}"></figure>'
            for name in variants
        )
        image_sections.append(f"<h2>{form_id} ({role})</h2><div class=\"layers\">{figures}</div>")
    status = {
        "status": "UNSCORED_OCR_DEMONSTRATION",
        "warning": OCR_BANNER,
        "lab_repository_sha": repo_sha,
        "pytesseract_available": pytesseract_available,
        "tesseract_executable_available": bool(executable),
        "ocr_execution": "completed" if ocr_available else "skipped_missing_tesseract",
        "forms": forms,
    }
    write_json(ocr_out / "manifest.json", status)
    if not ocr_available:
        write_text(
            ocr_out / "environment_gap.md",
            "# OCR environment gap\n\nTesseract executable is unavailable. Degraded images were generated, but no OCR overlay was fabricated.\n",
        )
    write_text(
        ocr_out / "observations.md",
        "# Unscored OCR demonstration observations\n\n"
        "- Skew appears likely to disrupt line grouping and word baselines.\n"
        "- Lower resolution merges nearby character strokes and thin rules.\n"
        "- JPEG artifacts obscure thin rules and small checkbox outlines.\n"
        "- Added noise affects small labels differently from large empty boxes.\n\n"
        "These are qualitative review notes only. No engine comparison or production recommendation is made.\n",
    )
    warning = (
        "Tesseract executed locally on approved blank fixtures."
        if ocr_available
        else "Tesseract executable is unavailable; OCR overlays were skipped honestly."
    )
    body = f'<div class="warning">{OCR_BANNER}</div><p>{warning}</p>' + "".join(image_sections)
    write_text(ocr_out / "index.html", html_page("Unscored OCR demonstration", body))
    return status


def generate_packets(
    repo_root: Path = ROOT,
    queue_path: Path | None = None,
    manifest_path: Path | None = None,
    out_dir: Path | None = None,
    reviews_dir: Path | None = None,
    backend_id: str = "heuristic_lab_v2",
    dpi: int = RENDER_DPI,
    include_ocr_demo: bool = True,
    backend_override: tuple[Callable[[Path], list[dict[str, Any]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    queue_path = (queue_path or repo_root / "reports" / "gt_review_queue" / "QUEUE.md").resolve()
    manifest_path = (manifest_path or repo_root / "corpus" / "manifest.json").resolve()
    out_dir = (out_dir or repo_root / "reports" / "review_packets").resolve()
    reviews_dir = (reviews_dir or repo_root / "reviews").resolve()
    assert_within(queue_path, repo_root, "review queue")
    assert_within(manifest_path, repo_root, "corpus manifest")
    assert_within(out_dir, repo_root / "reports" / "review_packets", "packet output")
    assert_within(reviews_dir, repo_root / "reviews", "review output")
    out_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(exist_ok=True)
    entries = load_queue_entries(repo_root, queue_path, manifest_path)
    backend_fn, backend_metadata = backend_override or load_backend(repo_root, backend_id)
    if backend_override:
        backend_metadata = dict(backend_metadata)
        backend_metadata.setdefault("backend_id", backend_id)
        backend_metadata.setdefault("schema_version", FIELD_SCHEMA_VERSION)
        backend_metadata.setdefault("lanes", ["B"])
        backend_metadata.setdefault("description", "Deterministic test backend")
        backend_metadata.setdefault("production_equivalent", False)
        backend_metadata.setdefault("parity_note", "Test-only lab backend")
        backend_metadata.setdefault("configuration", {"deterministic_defaults": True})
    sha = repository_sha(repo_root)
    command = f"python scripts/generate_review_packets.py --backend {backend_metadata['backend_id']} --dpi {dpi}"
    forms = [
        generate_form_packet(repo_root, entry, out_dir, reviews_dir, backend_fn, backend_metadata, sha, dpi, command)
        for entry in entries
    ]
    root_timestamp = deterministic_timestamp([queue_path, manifest_path, Path(__file__)])
    root_manifest = {
        "packet_schema_version": PACKET_SCHEMA_VERSION,
        "packet_generator_version": GENERATOR_VERSION,
        "packet_status": PACKET_STATUS,
        "lab_repository_sha": sha,
        "generation_timestamp": root_timestamp,
        "review_queue": repo_relative(queue_path, repo_root),
        "forms": [
            {
                "form_id": form["form_id"],
                "source_pdf": form["source_pdf"],
                "gt_path": form["gt_path"],
                "gt_provenance": form["gt_provenance"],
                "packet_status": form["packet_status"],
                "page_count": form["page_count"],
                "pages": form["pages"],
                "form_manifest": form["artifacts"]["form_manifest"],
                "form_html": form["artifacts"]["form_html"],
                "review_json": form["artifacts"]["review_json"],
                "review_markdown": form["artifacts"]["review_markdown"],
            }
            for form in forms
        ],
    }
    write_json(out_dir / "packet_manifest.json", root_manifest)
    write_json(out_dir / "assets" / "legend.json", {
        "draft_gt": "blue",
        "detector_candidate": "orange",
        "overlap_candidate": "teal",
        "notice": OVERLAP_NOTICE,
    })
    cards = []
    for form in root_manifest["forms"]:
        cards.append(
            f'<article class="form-item"><h2>{form["form_id"]}</h2>'
            f'<p>{form["gt_provenance"]["display"]}</p>'
            f'<p>{form["page_count"]} source pages</p>'
            f'<a href="{form["form_id"]}/index.html">Open review packet</a><br>'
            f'<a href="../../{form["review_json"]}">Review JSON</a> | '
            f'<a href="../../{form["review_markdown"]}">Review Markdown</a></article>'
        )
    root_body = f"""
<div class="warning">Zero packets are authoritative ground truth. Zero overlap classifications are accuracy measurements. Detector output is context, not truth. Owner review is required before any promotion.</div>
<p>Queue: <code>{root_manifest['review_queue']}</code> | Lab SHA: <code>{sha}</code></p>
<div class="forms">{''.join(cards)}</div>
"""
    write_text(out_dir / "index.html", html_page("Detection lab review packets", root_body))
    ocr_status = None
    if include_ocr_demo:
        ocr_status = generate_ocr_demo(repo_root, entries, repo_root / "reports" / "ocr_demo", sha)
    return {"packet_manifest": root_manifest, "ocr_demo": ocr_status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--reviews", default=str(DEFAULT_REVIEWS))
    parser.add_argument("--backend", default="heuristic_lab_v2")
    parser.add_argument("--dpi", type=int, default=RENDER_DPI)
    parser.add_argument("--skip-ocr-demo", action="store_true")
    args = parser.parse_args()
    result = generate_packets(
        repo_root=ROOT,
        queue_path=Path(args.queue),
        manifest_path=Path(args.manifest),
        out_dir=Path(args.out),
        reviews_dir=Path(args.reviews),
        backend_id=args.backend,
        dpi=args.dpi,
        include_ocr_demo=not args.skip_ocr_demo,
    )
    forms = result["packet_manifest"]["forms"]
    print(f"Generated {len(forms)} unscored review packets.")
    print(f"Index: {repo_relative(DEFAULT_OUT / 'index.html')}")
    if result["ocr_demo"]:
        print(f"OCR demo: {result['ocr_demo']['ocr_execution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
