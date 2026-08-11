#!/usr/bin/env python3
"""Shared schema, rendering, and validation helpers for LAB-PACKET-1."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
GENERATOR_VERSION = "lab-packet-1.0"
PACKET_STATUS = "UNSCORED_DRAFT_REVIEW_PACKET"
REVIEW_TEMPLATE_VERSION = "1.0"
FIELD_SCHEMA_VERSION = "1.0"
ALLOWED_FIELD_TYPES = {"text", "checkbox", "radio", "choice", "signature"}
ALLOWED_DECISIONS = {"accept", "update", "delete", "pending"}
ALLOWED_DOCUMENT_DECISIONS = {"pending", "confirmed_zero_fields"}
ALLOWED_PROVENANCE = {
    "native_widget_derived",
    "detector_bootstrapped",
    "manually_authored_draft",
    "unknown_unreviewed",
}
FIELD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

DRAFT_BANNER = "DRAFT GROUND TRUTH - UNSCORED - NOT HUMAN REVIEWED"
DETECTOR_BANNER = "DETECTOR CANDIDATES - UNSCORED - BACKEND {backend_id}"
COMBINED_BANNER = "COMBINED REVIEW VIEW - UNSCORED - DRAFT CONTEXT"
OVERLAP_NOTICE = "OVERLAP HINTS ARE FOR REVIEW NAVIGATION ONLY - NOT A SCORE"
OCR_BANNER = "UNSCORED OCR DEMONSTRATION - NOT AN ACCURACY EVALUATION"

DRAFT_COLOR = (0, 102, 204)
DETECTOR_COLOR = (230, 103, 35)
LINK_COLOR = (0, 128, 112)
PAGE_BORDER_COLOR = (65, 72, 82)


class PacketError(RuntimeError):
    """Raised when packet inputs or review data violate the contract."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"Cannot read JSON {path}: {exc}") from exc


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def assert_within(path: Path, expected_root: Path, label: str = "path") -> Path:
    resolved = path.resolve()
    expected = expected_root.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError as exc:
        raise PacketError(f"{label} must be inside {expected}: {resolved}") from exc
    return resolved


def resolve_repo_path(value: str | Path, repo_root: Path = ROOT) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return assert_within(path, repo_root, "repository path")


def repo_relative(path: Path, repo_root: Path = ROOT) -> str:
    resolved = assert_within(path, repo_root, "repository path")
    return resolved.relative_to(repo_root.resolve()).as_posix()


def sanitize_text(value: Any, maximum: int = 256) -> str:
    if value is None:
        return ""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:maximum]


def safe_form_id(value: str) -> str:
    candidate = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    if not candidate or candidate != value:
        raise PacketError(f"Unsafe or unstable form id: {value!r}")
    return candidate


def validate_field_id(value: Any, label: str = "field id") -> str:
    field_id = sanitize_text(value, maximum=128)
    if not FIELD_ID_PATTERN.fullmatch(field_id):
        raise PacketError(
            f"{label} must be 1-128 characters using letters, digits, _, ., :, or -"
        )
    return field_id


def infer_gt_provenance(gt: dict[str, Any]) -> dict[str, Any]:
    declared = gt.get("provenance")
    if isinstance(declared, dict):
        declared_kind = sanitize_text(declared.get("kind"))
    else:
        declared_kind = sanitize_text(declared)
    if declared_kind in ALLOWED_PROVENANCE:
        return {
            "kind": declared_kind,
            "method": sanitize_text(gt.get("extraction_method")) or None,
            "backend": sanitize_text(gt.get("bootstrap_backend")) or None,
            "display": declared_kind.replace("_", " "),
        }

    method = sanitize_text(gt.get("extraction_method"))
    if method == "flat_pdf_bootstrap":
        backend = sanitize_text(gt.get("bootstrap_backend")) or "unknown"
        return {
            "kind": "detector_bootstrapped",
            "method": method,
            "backend": backend,
            "display": f"detector-bootstrapped draft via {backend}",
        }
    if method == "acroform_widgets":
        return {
            "kind": "native_widget_derived",
            "method": method,
            "backend": None,
            "display": "native-widget-derived draft",
        }
    if method in {"manual", "manually_authored", "human_draft"}:
        return {
            "kind": "manually_authored_draft",
            "method": method,
            "backend": None,
            "display": "manually authored draft",
        }
    return {
        "kind": "unknown_unreviewed",
        "method": None,
        "backend": None,
        "display": "unknown_unreviewed",
    }


def provenance_value(provenance: dict[str, Any]) -> str:
    return sanitize_text(provenance.get("display")) or "unknown_unreviewed"


def normalize_bbox(value: Any, label: str = "bbox") -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise PacketError(f"{label} must be [x, y, width, height]")
    try:
        box = [round(float(part), 2) for part in value]
    except (TypeError, ValueError) as exc:
        raise PacketError(f"{label} contains a non-numeric value") from exc
    if not all(math.isfinite(part) for part in box):
        raise PacketError(f"{label} contains a non-finite value")
    if box[0] < 0 or box[1] < 0 or box[2] <= 0 or box[3] <= 0:
        raise PacketError(f"{label} must have non-negative origin and positive size")
    return box


def validate_geometry(
    value: Any,
    page: int,
    page_sizes: dict[int, tuple[float, float]],
    label: str,
) -> list[float]:
    if page not in page_sizes:
        raise PacketError(f"{label} references invalid page {page}")
    box = normalize_bbox(value, label)
    page_width, page_height = page_sizes[page]
    epsilon = 0.02
    if box[0] + box[2] > page_width + epsilon:
        raise PacketError(f"{label} extends beyond page {page} width")
    if box[1] + box[3] > page_height + epsilon:
        raise PacketError(f"{label} extends beyond page {page} height")
    return box


def validate_field_type(value: Any, label: str) -> str:
    field_type = sanitize_text(value)
    if field_type not in ALLOWED_FIELD_TYPES:
        allowed = ", ".join(sorted(ALLOWED_FIELD_TYPES))
        raise PacketError(f"{label} must be one of: {allowed}")
    return field_type


def validate_gt(gt: dict[str, Any], page_sizes: dict[int, tuple[float, float]]) -> None:
    if gt.get("schema_version") != FIELD_SCHEMA_VERSION:
        raise PacketError("Ground truth schema_version must equal 1.0")
    if not isinstance(gt.get("fields"), list):
        raise PacketError("Ground truth fields must be a list")
    seen: set[str] = set()
    for index, field in enumerate(gt["fields"]):
        field_id = validate_field_id(field.get("id"), f"Ground truth field {index} id")
        if field_id in seen:
            raise PacketError(f"Duplicate ground truth field id: {field_id}")
        seen.add(field_id)
        try:
            page = int(field.get("page"))
        except (TypeError, ValueError) as exc:
            raise PacketError(f"Ground truth field {field_id} has invalid page") from exc
        validate_field_type(field.get("type"), f"Ground truth field {field_id} type")
        validate_geometry(field.get("bbox"), page, page_sizes, f"Ground truth field {field_id} bbox")


def bbox_intersection_fraction(a: list[float], b: list[float]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0.0, min(ay2, by2) - max(ay1, by1))
    smaller = min(aw * ah, bw * bh)
    return (width * height / smaller) if smaller > 0 else 0.0


def build_overlap_hints(
    draft_fields: list[dict[str, Any]],
    detector_fields: list[dict[str, Any]],
    link_threshold: float = 0.10,
    substantial_threshold: float = 0.50,
) -> dict[str, Any]:
    draft_links: dict[str, list[tuple[str, str]]] = {
        sanitize_text(field.get("id")): [] for field in draft_fields
    }
    detector_links: dict[str, list[tuple[str, str]]] = {
        sanitize_text(field.get("id")): [] for field in detector_fields
    }

    for draft in draft_fields:
        draft_id = sanitize_text(draft.get("id"))
        draft_box = normalize_bbox(draft.get("bbox"), f"draft {draft_id} bbox")
        for detector in detector_fields:
            if int(draft.get("page", 0)) != int(detector.get("page", -1)):
                continue
            detector_id = sanitize_text(detector.get("id"))
            detector_box = normalize_bbox(detector.get("bbox"), f"detector {detector_id} bbox")
            overlap = bbox_intersection_fraction(draft_box, detector_box)
            if overlap < link_threshold:
                continue
            category = "substantial" if overlap >= substantial_threshold else "partial"
            draft_links[draft_id].append((detector_id, category))
            detector_links[detector_id].append((draft_id, category))

    rows: list[dict[str, Any]] = []
    linked_pairs: set[tuple[str, str]] = set()
    for draft_id in sorted(draft_links):
        links = sorted(draft_links[draft_id])
        all_detector_ids = [item[0] for item in links]
        if not links:
            rows.append({
                "draft_field_id": draft_id,
                "linked_detector_candidate_ids": [],
                "detector_candidate_id": None,
                "linked_draft_field_ids": [],
                "overlap_category": "none",
                "presentation_threshold": link_threshold,
            })
            continue
        for detector_id, category in links:
            linked_pairs.add((draft_id, detector_id))
            rows.append({
                "draft_field_id": draft_id,
                "linked_detector_candidate_ids": all_detector_ids,
                "detector_candidate_id": detector_id,
                "linked_draft_field_ids": [
                    item[0] for item in sorted(detector_links[detector_id])
                ],
                "overlap_category": category,
                "presentation_threshold": link_threshold,
            })

    for detector_id in sorted(detector_links):
        if detector_links[detector_id]:
            continue
        rows.append({
            "draft_field_id": None,
            "linked_detector_candidate_ids": [],
            "detector_candidate_id": detector_id,
            "linked_draft_field_ids": [],
            "overlap_category": "none",
            "presentation_threshold": link_threshold,
        })

    return {
        "status": "UNSCORED_REVIEW_NAVIGATION_ONLY",
        "notice": OVERLAP_NOTICE,
        "link_measure": "intersection_over_smaller_box_area",
        "presentation_threshold": link_threshold,
        "substantial_threshold": substantial_threshold,
        "rows": rows,
        "draft_links": {
            key: [item[0] for item in sorted(value)]
            for key, value in sorted(draft_links.items())
        },
        "detector_links": {
            key: [item[0] for item in sorted(value)]
            for key, value in sorted(detector_links.items())
        },
    }


def get_font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = []
    if bold:
        candidates.extend([
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ])
    candidates.extend([
        "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ])
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_pdf_pages(pdf_path: Path, dpi: int) -> list[dict[str, Any]]:
    import fitz
    from PIL import Image

    if dpi < 36 or dpi > 600:
        raise PacketError("Render DPI must be between 36 and 600")
    scale = dpi / 72.0
    pages: list[dict[str, Any]] = []
    document = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            pages.append({
                "page": page_index + 1,
                "image": image,
                "pdf_width": round(float(page.rect.width), 2),
                "pdf_height": round(float(page.rect.height), 2),
                "image_width": image.width,
                "image_height": image.height,
                "scale_px_per_point": scale,
                "dpi": dpi,
            })
    finally:
        document.close()
    return pages


def add_banner(image, title: str, subtitle: str = "", footer: str = ""):
    from PIL import Image, ImageDraw

    title_font = get_font(20, bold=True)
    body_font = get_font(14)
    top_height = 58 if subtitle else 38
    bottom_height = 34 if footer else 0
    output = Image.new(
        "RGB",
        (image.width, image.height + top_height + bottom_height),
        (255, 255, 255),
    )
    output.paste(image.convert("RGB"), (0, top_height))
    draw = ImageDraw.Draw(output)
    draw.rectangle([0, 0, output.width, top_height], fill=(31, 34, 39))
    draw.text((14, 8), title, fill=(255, 255, 255), font=title_font)
    if subtitle:
        draw.text((14, 34), subtitle, fill=(213, 219, 226), font=body_font)
    if footer:
        y = top_height + image.height
        draw.rectangle([0, y, output.width, output.height], fill=(241, 244, 247))
        draw.text((14, y + 8), footer, fill=(35, 42, 49), font=body_font)
    return output


def _bbox_to_pixels(bbox: Iterable[float], scale: float) -> list[float]:
    x, y, width, height = bbox
    return [x * scale, y * scale, (x + width) * scale, (y + height) * scale]


def draw_field_overlay(
    base_image,
    fields: list[dict[str, Any]],
    scale: float,
    color: tuple[int, int, int],
    id_key: str = "id",
    label_prefix: str = "",
):
    from PIL import ImageDraw

    image = base_image.convert("RGB").copy()
    draw = ImageDraw.Draw(image)
    label_font = get_font(13, bold=True)
    secondary_font = get_font(11)
    draw.rectangle([0, 0, image.width - 1, image.height - 1], outline=PAGE_BORDER_COLOR, width=3)
    draw.line([0, 0, min(55, image.width), 0], fill=(190, 35, 45), width=5)
    draw.line([0, 0, 0, min(55, image.height)], fill=(190, 35, 45), width=5)
    draw.text((7, 7), "origin (0,0), top-left", fill=(150, 25, 35), font=secondary_font)
    for field in fields:
        box = normalize_bbox(field.get("bbox"), "overlay bbox")
        pixel_box = _bbox_to_pixels(box, scale)
        draw.rectangle(pixel_box, outline=color, width=3)
        field_id = sanitize_text(field.get(id_key)) or "?"
        field_type = sanitize_text(field.get("type")) or "unknown"
        primary = f"{label_prefix}{field_id}:{field_type}"
        x, y = int(pixel_box[0]), int(pixel_box[1])
        text_y = max(20, y - 18)
        text_box = draw.textbbox((x, text_y), primary, font=label_font)
        draw.rectangle(text_box, fill=(255, 255, 255))
        draw.text((x, text_y), primary, fill=color, font=label_font)
        secondary = sanitize_text(field.get("label"), maximum=80)
        if secondary:
            second_y = min(image.height - 14, int(pixel_box[3]) + 2)
            second_box = draw.textbbox((x, second_y), secondary, font=secondary_font)
            draw.rectangle(second_box, fill=(255, 255, 255))
            draw.text((x, second_y), secondary, fill=color, font=secondary_font)
    return image


def draw_combined_overlay(
    base_image,
    draft_fields: list[dict[str, Any]],
    detector_fields: list[dict[str, Any]],
    overlap_hints: dict[str, Any],
    scale: float,
):
    from PIL import ImageDraw

    image = base_image.convert("RGB").copy()
    draw = ImageDraw.Draw(image)
    font = get_font(10, bold=True)

    def draw_tag(x: int, y: int, text: str, color: tuple[int, int, int]) -> None:
        padding_x = 3
        padding_y = 2
        text_box = draw.textbbox((0, 0), text, font=font)
        width = text_box[2] - text_box[0] + padding_x * 2
        height = text_box[3] - text_box[1] + padding_y * 2
        x = max(0, min(x, image.width - width))
        y = max(0, min(y, image.height - height))
        draw.rectangle(
            (x, y, x + width, y + height),
            fill=(255, 255, 255),
            outline=color,
            width=1,
        )
        draw.text(
            (x + padding_x, y + padding_y),
            text,
            fill=color,
            font=font,
        )

    draw.rectangle([0, 0, image.width - 1, image.height - 1], outline=PAGE_BORDER_COLOR, width=3)
    draft_links = overlap_hints.get("draft_links", {})
    detector_links = overlap_hints.get("detector_links", {})
    for field in draft_fields:
        field_id = sanitize_text(field.get("id"))
        linked = bool(draft_links.get(field_id))
        color = LINK_COLOR if linked else DRAFT_COLOR
        box = _bbox_to_pixels(normalize_bbox(field.get("bbox")), scale)
        draw.rectangle(box, outline=color, width=3)
        term = "overlap candidate" if linked else "draft-GT-only"
        draw_tag(box[0] + 2, box[1] + 2, f"G:{field_id} {term}", color)
    for field in detector_fields:
        field_id = sanitize_text(field.get("id"))
        linked = bool(detector_links.get(field_id))
        color = LINK_COLOR if linked else DETECTOR_COLOR
        box = _bbox_to_pixels(normalize_bbox(field.get("bbox")), scale)
        draw.rectangle(box, outline=color, width=2)
        term = "overlap candidate" if linked else "detector-only"
        draw_tag(box[0] + 2, box[3] - 14, f"D:{field_id} {term}", color)
    return image


def save_png(image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, format="PNG", optimize=False, compress_level=9)


def draft_table(gt: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for field in gt.get("fields", []):
        rows.append({
            "field_id": sanitize_text(field.get("id")),
            "page": int(field.get("page")),
            "declared_type": sanitize_text(field.get("type")),
            "label": field.get("label"),
            "bbox": normalize_bbox(field.get("bbox")),
            "provenance": provenance_value(provenance),
            "current_review_status": sanitize_text(gt.get("review_status")) or "unknown",
            "group_id": field.get("group_id"),
            "state": field.get("state"),
            "comb": field.get("comb"),
        })
    return {
        "status": PACKET_STATUS,
        "schema_version": gt.get("schema_version"),
        "gt_provenance": provenance,
        "rows": rows,
    }


def detector_table(
    fields: list[dict[str, Any]],
    backend_id: str,
    backend_version: str,
) -> dict[str, Any]:
    return {
        "status": PACKET_STATUS,
        "backend_id": backend_id,
        "backend_version": backend_version,
        "candidates": fields,
    }


def build_review_template(form_manifest: dict[str, Any]) -> dict[str, Any]:
    draft_rows = form_manifest["draft_gt"]["fields"]
    return {
        "review_schema_version": REVIEW_TEMPLATE_VERSION,
        "form_id": form_manifest["form_id"],
        "source_pdf_sha256": form_manifest["source_pdf_sha256"],
        "source_gt_sha256": form_manifest["gt_sha256"],
        "source_gt_provenance": form_manifest["gt_provenance"]["display"],
        "packet_manifest": form_manifest["artifacts"]["form_manifest"],
        "reviewer": "",
        "reviewed_at": "",
        "review_status": "review_template",
        "document_decision": "pending",
        "fields": [
            {
                "field_id": row["field_id"],
                "decision": "pending",
                "new_type": None,
                "new_geometry": None,
                "new_label": None,
                "group_id": None,
                "comment": "",
            }
            for row in draft_rows
        ],
        "additions": [],
        "page_notes": [],
        "document_notes": "",
    }


def review_markdown(review: dict[str, Any]) -> str:
    lines = [
        f"# Review: {review['form_id']}",
        "",
        "This Markdown is generated from the JSON review file. Edit the JSON only.",
        "",
        f"- Packet manifest: `{review['packet_manifest']}`",
        f"- Source PDF SHA-256: `{review['source_pdf_sha256']}`",
        f"- Source GT SHA-256: `{review['source_gt_sha256']}`",
        f"- Source GT provenance: `{review['source_gt_provenance']}`",
        f"- Reviewer: `{sanitize_text(review.get('reviewer'))}`",
        f"- Reviewed at: `{sanitize_text(review.get('reviewed_at'))}`",
        f"- Document decision: `{sanitize_text(review.get('document_decision')) or 'pending'}`",
        "",
        "| Done | Field | Decision | New type | New geometry | Comment |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in review.get("fields", []):
        decision = sanitize_text(row.get("decision")) or "pending"
        checked = "x" if decision != "pending" else " "
        geometry = json.dumps(row.get("new_geometry"), ensure_ascii=False)
        comment = sanitize_text(row.get("comment")).replace("|", "\\|")
        lines.append(
            f"| [{checked}] | `{row.get('field_id')}` | `{decision}` | "
            f"`{row.get('new_type')}` | `{geometry}` | {comment} |"
        )
    lines.extend([
        "",
        f"Additions recorded in JSON: {len(review.get('additions', []))}",
        "",
        "## Document-level zero-field decision",
        "",
        "`document_decision` normally remains `pending`.",
        "",
        "Set `document_decision` to `confirmed_zero_fields` only after inspecting "
        "the source form and affirmatively deciding that it genuinely contains zero fillable fields.",
        "",
        "Do not use `confirmed_zero_fields` merely because the detector found nothing, "
        "the draft contains nothing, fields were difficult to identify, or the form is confusing.",
        "",
        "If fillable regions exist, record them in the structured `additions` array instead.",
        "",
    ])
    return "\n".join(lines)


def validate_iso_date(value: Any) -> str:
    text = sanitize_text(value)
    if not text:
        raise PacketError("reviewed_at must not be blank")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PacketError("reviewed_at must be a valid ISO-8601 date or timestamp") from exc
    return text


def validate_review(
    review: dict[str, Any],
    source_gt: dict[str, Any],
    page_sizes: dict[int, tuple[float, float]],
    require_complete: bool = True,
) -> dict[str, Any]:
    if review.get("review_schema_version") != REVIEW_TEMPLATE_VERSION:
        raise PacketError("Unsupported review_schema_version")
    reviewer = sanitize_text(review.get("reviewer"))
    if not reviewer:
        raise PacketError("reviewer must not be blank")
    reviewed_at = validate_iso_date(review.get("reviewed_at"))
    if not isinstance(review.get("fields"), list):
        raise PacketError("review fields must be a list")
    document_decision = sanitize_text(review.get("document_decision"))
    if document_decision not in ALLOWED_DOCUMENT_DECISIONS:
        allowed = ", ".join(sorted(ALLOWED_DOCUMENT_DECISIONS))
        raise PacketError(f"document_decision must be one of: {allowed}")
    additions = review.get("additions", [])
    if not isinstance(additions, list):
        raise PacketError("additions must be a list")
    if document_decision == "confirmed_zero_fields" and additions:
        raise PacketError(
            "document_decision=confirmed_zero_fields contradicts nonempty additions"
        )

    source_by_id = {
        validate_field_id(field.get("id"), "Source field id"): field
        for field in source_gt.get("fields", [])
    }
    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in review["fields"]:
        field_id = validate_field_id(row.get("field_id"), "Review field id")
        if not field_id or field_id not in source_by_id:
            raise PacketError(f"Review references unknown field id: {field_id!r}")
        if field_id in rows_by_id:
            raise PacketError(f"Duplicate review field id: {field_id}")
        decision = sanitize_text(row.get("decision"))
        if decision not in ALLOWED_DECISIONS:
            raise PacketError(f"Invalid decision for {field_id}: {decision!r}")
        if require_complete and decision == "pending":
            raise PacketError(f"Review field {field_id} is still pending")
        rows_by_id[field_id] = row

    missing = sorted(set(source_by_id) - set(rows_by_id))
    if missing:
        raise PacketError(f"Review is missing source fields: {', '.join(missing)}")

    output_ids: set[str] = set()
    normalized_fields: list[dict[str, Any]] = []
    decision_log: list[dict[str, Any]] = []
    for source_id, source in source_by_id.items():
        row = rows_by_id[source_id]
        decision = sanitize_text(row.get("decision"))
        decision_log.append({"field_id": source_id, "decision": decision})
        if decision == "delete":
            continue
        result = dict(source)
        result["id"] = source_id
        if decision == "update":
            changed = False
            if row.get("new_type") is not None:
                result["type"] = validate_field_type(row.get("new_type"), f"Field {source_id} new_type")
                changed = True
            if row.get("new_geometry") is not None:
                page = int(result.get("page"))
                result["bbox"] = validate_geometry(
                    row.get("new_geometry"), page, page_sizes, f"Field {source_id} new_geometry"
                )
                changed = True
            if row.get("new_label") is not None:
                result["label"] = sanitize_text(row.get("new_label")) or None
                changed = True
            if row.get("group_id") is not None:
                result["group_id"] = sanitize_text(row.get("group_id")) or None
                changed = True
            if not changed:
                raise PacketError(f"Field {source_id} is update but has no changed value")
        page = int(result.get("page"))
        result["type"] = validate_field_type(result.get("type"), f"Field {source_id} type")
        result["bbox"] = validate_geometry(result.get("bbox"), page, page_sizes, f"Field {source_id} bbox")
        if source_id in output_ids:
            raise PacketError(f"Duplicate output field id: {source_id}")
        output_ids.add(source_id)
        normalized_fields.append(result)

    for index, addition in enumerate(additions, start=1):
        if not isinstance(addition, dict):
            raise PacketError(f"Addition {index} must be an object")
        field_id = validate_field_id(addition.get("field_id"), f"Addition {index} field_id")
        if field_id in source_by_id or field_id in output_ids:
            raise PacketError(f"Duplicate addition field id: {field_id}")
        try:
            page = int(addition.get("page"))
        except (TypeError, ValueError) as exc:
            raise PacketError(f"Addition {field_id} has invalid page") from exc
        field_type = validate_field_type(addition.get("type"), f"Addition {field_id} type")
        geometry = validate_geometry(
            addition.get("geometry"), page, page_sizes, f"Addition {field_id} geometry"
        )
        result = {
            "id": field_id,
            "page": page,
            "type": field_type,
            "bbox": geometry,
            "label": sanitize_text(addition.get("label")) or None,
        }
        group_id = sanitize_text(addition.get("group_id"))
        if group_id:
            result["group_id"] = group_id
        comment = sanitize_text(addition.get("comment"))
        if not comment:
            raise PacketError(f"Addition {field_id} requires a comment")
        output_ids.add(field_id)
        normalized_fields.append(result)
        decision_log.append({"field_id": field_id, "decision": "add"})

    normalized_fields.sort(key=lambda field: (int(field["page"]), field["bbox"][1], field["bbox"][0], field["id"]))
    if require_complete and not normalized_fields and document_decision != "confirmed_zero_fields":
        raise PacketError(
            "Zero-field reviews require document_decision=confirmed_zero_fields "
            "after the source form has been inspected."
        )
    if document_decision == "confirmed_zero_fields" and normalized_fields:
        raise PacketError(
            "document_decision=confirmed_zero_fields requires a zero-field review result"
        )
    return {
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "document_decision": document_decision,
        "fields": normalized_fields,
        "decision_log": decision_log,
    }


def confirmation_binding(
    form_id: str,
    source_pdf_sha256: str,
    source_gt_sha256: str,
    review_json_sha256: str,
    candidate_output_sha256: str,
) -> dict[str, str]:
    return {
        "form_id": form_id,
        "source_pdf_sha256": source_pdf_sha256,
        "source_gt_sha256": source_gt_sha256,
        "review_json_sha256": review_json_sha256,
        "candidate_output_sha256": candidate_output_sha256,
    }


def confirmation_token(binding: dict[str, str]) -> str:
    return sha256_bytes(canonical_json_bytes(binding))


def html_page(title: str, body: str, root_prefix: str = "") -> str:
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{ color-scheme: light; --ink:#1f252b; --muted:#66717c; --line:#cbd2d9; --blue:#0066cc; --orange:#c95418; --teal:#007f70; --warn:#fff3cd; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:#f7f8fa; font:15px/1.45 Arial,sans-serif; letter-spacing:0; }}
    header {{ background:#20252b; color:white; padding:18px clamp(14px,4vw,48px); }} h1,h2,h3 {{ margin:0 0 10px; letter-spacing:0; }} h1 {{ font-size:clamp(24px,4vw,38px); }} h2 {{ font-size:21px; margin-top:24px; }}
    main {{ max-width:1500px; margin:auto; padding:20px clamp(12px,3vw,40px) 50px; }} a {{ color:#005cb8; }} .warning {{ background:var(--warn); border:1px solid #d8b651; padding:12px; margin:14px 0; font-weight:700; }}
    .meta {{ display:grid; grid-template-columns:minmax(150px,240px) minmax(0,1fr); gap:6px 14px; margin:14px 0; }} .meta dt {{ font-weight:700; }} .meta dd {{ margin:0; overflow-wrap:anywhere; }}
    .forms {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }} .form-item {{ border:1px solid var(--line); background:white; padding:14px; border-radius:6px; }}
    .layers {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr)); gap:14px; align-items:start; }} figure {{ margin:0; min-width:0; }} figure img {{ display:block; width:100%; height:auto; border:1px solid var(--line); background:white; }} figcaption {{ font-weight:700; padding:6px 0; }}
    .table-wrap {{ overflow:auto; border:1px solid var(--line); background:white; }} table {{ width:100%; border-collapse:collapse; min-width:720px; }} th,td {{ padding:7px 9px; border-bottom:1px solid #e2e6ea; text-align:left; vertical-align:top; }} th {{ background:#edf1f4; position:sticky; top:0; }} code {{ overflow-wrap:anywhere; }} .legend {{ display:flex; flex-wrap:wrap; gap:6px 14px; }} .legend span {{ white-space:normal; }}
    @media (max-width:600px) {{ .meta {{ grid-template-columns:1fr; }} .meta dt {{ margin-top:8px; }} h1 {{ font-size:26px; }} }}
  </style>
</head>
<body>
<header><h1>{escaped_title}</h1><div>UNSCORED DRAFT REVIEW EVIDENCE</div></header>
<main>{body}</main>
</body>
</html>
"""


def html_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'
