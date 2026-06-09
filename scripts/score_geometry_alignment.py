#!/usr/bin/env python3
"""Standalone geometry/alignment scorer for flat-PDF lab cases.

This experiment is intentionally outside the production detector and the main
benchmark scorer. It measures whether detected boxes visually land on the form
geometry they are supposed to target.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fitz
except ImportError:
    print("ERROR: PyMuPDF/fitz is required for rendering and geometry scoring.", file=sys.stderr)
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow is required for geometry overlays.", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "corpus" / "manifest.json"
DEFAULT_OUT = ROOT / "experiments" / "geometry_alignment" / "runs" / "latest"
DEFAULT_BACKEND = "heuristic_lab_v2"

IOU_ALIGNED = 0.60
IOU_MATCH = 0.10
CENTER_MATCH_MAX = 50.0
Y_SHIFT_WARN = 8.0
X_SHIFT_WARN = 15.0
WRONG_SIZE_RATIO = 0.50
LABEL_OVERLAP_WARN = 0.10

STATUS_COLORS = {
    "aligned": (52, 199, 89),
    "y_shifted": (255, 149, 0),
    "x_shifted": (255, 149, 0),
    "wrong_size": (255, 149, 0),
    "overlaps_label": (175, 82, 222),
    "false_positive": (255, 59, 48),
    "missed_gt": (255, 59, 48),
    "needs_review": (142, 142, 147),
}
GT_COLOR = (52, 199, 89)
DET_COLOR = (0, 122, 255)


@dataclass
class RenderedPage:
    page_num: int
    image: Image.Image
    pdf_width: float
    pdf_height: float
    scale: float


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


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_font(size: int = 14) -> ImageFont.ImageFont:
    for path in [
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def resolve_pdf_path(entry: dict[str, Any]) -> Path:
    value = entry.get("path") or entry.get("filename") or entry.get("source_path")
    if not value:
        raise ValueError("manifest entry has no path, filename, or source_path")
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def load_manifest_entry(manifest_path: Path, doc_id: str) -> dict[str, Any]:
    data = load_json(manifest_path)
    entries = data.get("entries", data if isinstance(data, list) else [])
    for entry in entries:
        if entry.get("id") == doc_id:
            return entry
    raise KeyError(f"document not found in manifest: {doc_id}")


def load_ground_truth(entry: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    path_value = entry.get("ground_truth_path")
    if not path_value:
        return None, None
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return path, None
    return path, load_json(path)


def run_backend(pdf_path: Path, backend_name: str) -> tuple[list[dict[str, Any]], float]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from backend_registry import get_backend

    started = time.perf_counter()
    fields = get_backend(backend_name)(pdf_path)
    return fields, time.perf_counter() - started


def iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    inter = (right - left) * (bottom - top)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def center_distance(a: list[float], b: list[float]) -> float:
    ax, ay = center(a)
    bx, by = center(b)
    return math.hypot(ax - bx, ay - by)


def area(box: list[float]) -> float:
    return max(0.0, box[2]) * max(0.0, box[3])


def overlap_area(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def match_fields(
    detections: list[dict[str, Any]],
    ground_truth: list[dict[str, Any]],
) -> tuple[list[tuple[int, int, float, float]], list[int], list[int]]:
    candidates: list[tuple[float, float, int, int]] = []
    for gt_idx, gt in enumerate(ground_truth):
        for det_idx, det in enumerate(detections):
            if gt.get("page") != det.get("page"):
                continue
            score = iou(gt["bbox"], det["bbox"])
            distance = center_distance(gt["bbox"], det["bbox"])
            if score >= IOU_MATCH or distance <= CENTER_MATCH_MAX:
                candidates.append((score, -distance, gt_idx, det_idx))

    candidates.sort(reverse=True)
    claimed_gt: set[int] = set()
    claimed_det: set[int] = set()
    matches: list[tuple[int, int, float, float]] = []
    for score, neg_distance, gt_idx, det_idx in candidates:
        if gt_idx in claimed_gt or det_idx in claimed_det:
            continue
        claimed_gt.add(gt_idx)
        claimed_det.add(det_idx)
        matches.append((gt_idx, det_idx, score, -neg_distance))

    missed_gt = [idx for idx in range(len(ground_truth)) if idx not in claimed_gt]
    false_positive = [idx for idx in range(len(detections)) if idx not in claimed_det]
    return matches, missed_gt, false_positive


def render_pdf(pdf_path: Path, dpi: int) -> tuple[list[RenderedPage], fitz.Document]:
    doc = fitz.open(pdf_path)
    scale = dpi / 72.0
    pages: list[RenderedPage] = []
    for index, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        mode = "RGB" if pix.n < 4 else "RGBA"
        image = Image.frombytes(mode, [pix.width, pix.height], pix.samples).convert("RGB")
        pages.append(RenderedPage(
            page_num=index,
            image=image,
            pdf_width=float(page.rect.width),
            pdf_height=float(page.rect.height),
            scale=scale,
        ))
    return pages, doc


def dark_pixel_mask(image: Image.Image, threshold: int = 105) -> Image.Image:
    gray = image.convert("L")
    return gray.point(lambda value: 255 if value < threshold else 0, mode="1")


def merge_runs(runs: list[tuple[int, int, int]], y_tolerance: int = 3, gap_tolerance: int = 10) -> list[tuple[int, int, int]]:
    if not runs:
        return []
    rows: list[list[tuple[int, int, int]]] = []
    for run in sorted(runs, key=lambda item: (item[0], item[1])):
        if not rows or abs(rows[-1][0][0] - run[0]) > y_tolerance:
            rows.append([run])
        else:
            rows[-1].append(run)

    merged: list[tuple[int, int, int]] = []
    for row in rows:
        row_y = round(sum(item[0] for item in row) / len(row))
        segments = sorted((x0, x1) for _, x0, x1 in row)
        cur_x0, cur_x1 = segments[0]
        for x0, x1 in segments[1:]:
            if x0 <= cur_x1 + gap_tolerance:
                cur_x1 = max(cur_x1, x1)
            else:
                merged.append((row_y, cur_x0, cur_x1))
                cur_x0, cur_x1 = x0, x1
        merged.append((row_y, cur_x0, cur_x1))
    return merged


def horizontal_line_segments(page: RenderedPage) -> list[dict[str, float]]:
    mask = dark_pixel_mask(page.image)
    width, height = mask.size
    px = mask.load()
    runs: list[tuple[int, int, int]] = []
    for y in range(height):
        x = 0
        while x < width:
            while x < width and px[x, y] == 0:
                x += 1
            start = x
            while x < width and px[x, y] != 0:
                x += 1
            if x - start >= 35:
                runs.append((y, start, x - 1))
    return [
        {"y": round(y / page.scale, 2), "x0": round(x0 / page.scale, 2), "x1": round(x1 / page.scale, 2)}
        for y, x0, x1 in merge_runs(runs)
    ]


def component_boxes(mask: Image.Image, max_components: int = 3000) -> list[tuple[int, int, int, int, int]]:
    width, height = mask.size
    px = mask.load()
    visited: set[tuple[int, int]] = set()
    boxes: list[tuple[int, int, int, int, int]] = []
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if px[x, y] == 0 or (x, y) in visited:
                continue
            stack = [(x, y)]
            visited.add((x, y))
            min_x = max_x = x
            min_y = max_y = y
            pixels = 0
            while stack:
                cx, cy = stack.pop()
                pixels += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    if (nx, ny) in visited or px[nx, ny] == 0:
                        continue
                    visited.add((nx, ny))
                    stack.append((nx, ny))
            boxes.append((min_x, min_y, max_x, max_y, pixels))
            if len(boxes) >= max_components:
                return boxes
    return boxes


def looks_like_checkbox_outline(gray: Image.Image, x0: int, y0: int, x1: int, y1: int) -> bool:
    width = x1 - x0 + 1
    height = y1 - y0 + 1
    if width < 9 or height < 9:
        return False
    px = gray.load()
    border_dark = 0
    border_total = 0
    for x in range(x0, x1 + 1):
        for y in (y0, y1):
            border_total += 1
            border_dark += int(px[x, y] < 150)
    for y in range(y0, y1 + 1):
        for x in (x0, x1):
            border_total += 1
            border_dark += int(px[x, y] < 150)

    inset_x = max(2, width // 4)
    inset_y = max(2, height // 4)
    cx0, cy0 = x0 + inset_x, y0 + inset_y
    cx1, cy1 = x1 - inset_x, y1 - inset_y
    center_dark = 0
    center_total = 0
    if cx1 > cx0 and cy1 > cy0:
        for y in range(cy0, cy1 + 1):
            for x in range(cx0, cx1 + 1):
                center_total += 1
                center_dark += int(px[x, y] < 150)
    border_ratio = border_dark / max(1, border_total)
    center_ratio = center_dark / max(1, center_total)
    return border_ratio >= 0.26 and center_ratio <= 0.22


def checkbox_boxes(page: RenderedPage) -> list[list[float]]:
    gray = page.image.convert("L")
    mask = dark_pixel_mask(page.image)
    boxes: list[list[float]] = []
    for x0, y0, x1, y1, pixels in component_boxes(mask):
        width = x1 - x0 + 1
        height = y1 - y0 + 1
        if width < 9 or height < 9 or width > 50 or height > 50:
            continue
        aspect = width / height
        density = pixels / max(1, width * height)
        if not (0.72 <= aspect <= 1.28 and 0.08 <= density <= 0.55):
            continue
        if not looks_like_checkbox_outline(gray, x0, y0, x1, y1):
            continue
        boxes.append([
            round(x0 / page.scale, 2),
            round(y0 / page.scale, 2),
            round(width / page.scale, 2),
            round(height / page.scale, 2),
        ])
    return boxes


def page_words(doc: fitz.Document) -> dict[int, list[dict[str, Any]]]:
    words_by_page: dict[int, list[dict[str, Any]]] = {}
    for page_index, page in enumerate(doc, start=1):
        words = []
        for item in page.get_text("words"):
            x0, y0, x1, y1, text, *_ = item
            words.append({
                "text": text,
                "bbox": [float(x0), float(y0), float(x1 - x0), float(y1 - y0)],
            })
        words_by_page[page_index] = words
    return words_by_page


def label_overlap_risk(box: list[float], words: list[dict[str, Any]]) -> tuple[float, list[str]]:
    box_area = max(1.0, area(box))
    overlaps: list[tuple[float, str]] = []
    total = 0.0
    for word in words:
        hit = overlap_area(box, word["bbox"])
        if hit <= 0:
            continue
        total += hit
        overlaps.append((hit, word["text"]))
    overlaps.sort(reverse=True)
    return round(min(1.0, total / box_area), 4), [text for _, text in overlaps[:5]]


def checkbox_label_anchor_distance(box: list[float], label: str | None, words: list[dict[str, Any]]) -> float | None:
    if not label:
        return None
    label_lower = label.lower()
    best_box = None
    for word in words:
        text = str(word.get("text", "")).lower()
        if label_lower in text:
            best_box = word["bbox"]
            break
    if best_box is None:
        return None

    # Some PDFs encode the visual checkbox as a font glyph prefixed to the
    # label word. The first 12pt of that word bbox is the visible square target.
    anchor_box = [best_box[0], best_box[1] + 5.0, 12.0, 12.0]
    return round(center_distance(box, anchor_box), 2)


def nearest_baseline(box: list[float], lines: list[dict[str, float]]) -> tuple[float | None, float | None]:
    if not lines:
        return None, None
    x0, y0, w, h = box
    x1 = x0 + w
    bottom = y0 + h
    best: tuple[float, float] | None = None
    for line in lines:
        overlap = max(0.0, min(x1, line["x1"]) - max(x0, line["x0"]))
        if overlap <= 0 and (line["x1"] < x0 - 8 or line["x0"] > x1 + 8):
            continue
        distance = abs(bottom - line["y"])
        overlap_ratio = overlap / max(1.0, w)
        if best is None or distance < best[0]:
            best = (distance, overlap_ratio)
    if best is None:
        return None, None
    return round(best[0], 2), round(best[1], 4)


def nearest_checkbox_distance(box: list[float], candidates: list[list[float]]) -> float | None:
    if not candidates:
        return None
    return round(min(center_distance(box, cand) for cand in candidates), 2)


def classify_status(
    *,
    match_iou: float,
    x_offset: float,
    y_offset: float,
    gt_box: list[float],
    det_box: list[float],
    baseline_distance: float | None,
    label_risk: float,
) -> str:
    if label_risk >= LABEL_OVERLAP_WARN:
        return "overlaps_label"
    if abs(y_offset) > Y_SHIFT_WARN:
        return "y_shifted"
    if baseline_distance is not None and baseline_distance > Y_SHIFT_WARN:
        return "y_shifted"
    if abs(x_offset) > X_SHIFT_WARN:
        return "x_shifted"
    area_ratio = abs(area(det_box) - area(gt_box)) / max(1.0, area(gt_box))
    if match_iou < IOU_ALIGNED or area_ratio > WRONG_SIZE_RATIO:
        return "wrong_size"
    return "aligned"


def score_fields(
    *,
    detections: list[dict[str, Any]],
    ground_truth: list[dict[str, Any]],
    pages: list[RenderedPage],
    doc: fitz.Document,
    draft_gt: bool,
) -> list[dict[str, Any]]:
    lines_by_page = {page.page_num: horizontal_line_segments(page) for page in pages}
    checkbox_by_page = {page.page_num: checkbox_boxes(page) for page in pages}
    words_by_page = page_words(doc)
    matches, missed_gt, false_positive = match_fields(detections, ground_truth)
    rows: list[dict[str, Any]] = []

    for gt_idx, det_idx, match_iou, distance in matches:
        gt = ground_truth[gt_idx]
        det = detections[det_idx]
        gt_cx, gt_cy = center(gt["bbox"])
        det_cx, det_cy = center(det["bbox"])
        baseline_distance, printed_line_overlap = nearest_baseline(
            det["bbox"], lines_by_page.get(det.get("page"), [])
        )
        label_risk, label_words = label_overlap_risk(det["bbox"], words_by_page.get(det.get("page"), []))
        visible_checkbox_distance = None
        label_anchor_distance = None
        if det.get("type") == "checkbox":
            visible_checkbox_distance = nearest_checkbox_distance(
                det["bbox"], checkbox_by_page.get(det.get("page"), [])
            )
            label_anchor_distance = checkbox_label_anchor_distance(
                det["bbox"],
                gt.get("label") or det.get("label"),
                words_by_page.get(det.get("page"), []),
            )
        status = classify_status(
            match_iou=match_iou,
            x_offset=det_cx - gt_cx,
            y_offset=det_cy - gt_cy,
            gt_box=gt["bbox"],
            det_box=det["bbox"],
            baseline_distance=baseline_distance if det.get("type") != "checkbox" else None,
            label_risk=label_risk,
        )
        rows.append({
            "doc_id": None,
            "page": det.get("page"),
            "field_id": gt.get("id"),
            "detection_id": det.get("id"),
            "field_type": det.get("type"),
            "ground_truth_type": gt.get("type"),
            "detected_bbox": det.get("bbox"),
            "ground_truth_bbox": gt.get("bbox"),
            "iou": round(match_iou, 4),
            "center_distance": round(distance, 2),
            "x_offset": round(det_cx - gt_cx, 2),
            "y_offset": round(det_cy - gt_cy, 2),
            "baseline_distance": baseline_distance if det.get("type") != "checkbox" else None,
            "printed_line_overlap": printed_line_overlap if det.get("type") != "checkbox" else None,
            "visible_checkbox_center_distance": visible_checkbox_distance,
            "checkbox_label_anchor_distance": label_anchor_distance,
            "label_overlap_risk": label_risk,
            "label_overlap_words": label_words,
            "status": status,
            "gt_needs_review": draft_gt,
        })

    for gt_idx in missed_gt:
        gt = ground_truth[gt_idx]
        rows.append({
            "doc_id": None,
            "page": gt.get("page"),
            "field_id": gt.get("id"),
            "detection_id": None,
            "field_type": gt.get("type"),
            "ground_truth_type": gt.get("type"),
            "detected_bbox": None,
            "ground_truth_bbox": gt.get("bbox"),
            "iou": 0.0,
            "center_distance": None,
            "x_offset": None,
            "y_offset": None,
            "baseline_distance": None,
            "printed_line_overlap": None,
            "visible_checkbox_center_distance": None,
            "checkbox_label_anchor_distance": None,
            "label_overlap_risk": None,
            "label_overlap_words": [],
            "status": "missed_gt",
            "gt_needs_review": draft_gt,
        })

    for det_idx in false_positive:
        det = detections[det_idx]
        baseline_distance, printed_line_overlap = nearest_baseline(
            det["bbox"], lines_by_page.get(det.get("page"), [])
        )
        label_risk, label_words = label_overlap_risk(det["bbox"], words_by_page.get(det.get("page"), []))
        label_anchor_distance = None
        if det.get("type") == "checkbox":
            label_anchor_distance = checkbox_label_anchor_distance(
                det["bbox"],
                det.get("label"),
                words_by_page.get(det.get("page"), []),
            )
        rows.append({
            "doc_id": None,
            "page": det.get("page"),
            "field_id": None,
            "detection_id": det.get("id"),
            "field_type": det.get("type"),
            "ground_truth_type": None,
            "detected_bbox": det.get("bbox"),
            "ground_truth_bbox": None,
            "iou": 0.0,
            "center_distance": None,
            "x_offset": None,
            "y_offset": None,
            "baseline_distance": baseline_distance,
            "printed_line_overlap": printed_line_overlap,
            "visible_checkbox_center_distance": nearest_checkbox_distance(
                det["bbox"], checkbox_by_page.get(det.get("page"), [])
            ) if det.get("type") == "checkbox" else None,
            "checkbox_label_anchor_distance": label_anchor_distance,
            "label_overlap_risk": label_risk,
            "label_overlap_words": label_words,
            "status": "false_positive",
            "gt_needs_review": draft_gt,
        })
    rows.sort(key=lambda row: (row["page"] or 0, row["ground_truth_bbox"] or row["detected_bbox"] or [0, 0, 0, 0]))
    return rows


def aggregate(rows: list[dict[str, Any]], detections: list[dict[str, Any]], gt: dict[str, Any] | None) -> dict[str, Any]:
    counts = Counter(row["status"] for row in rows)
    matched = [row for row in rows if row["detected_bbox"] and row["ground_truth_bbox"]]
    aligned = counts.get("aligned", 0)
    scored = len(matched)
    return {
        "ground_truth_field_count": len(gt.get("fields", [])) if gt else 0,
        "detected_count": len(detections),
        "matched_count": scored,
        "aligned_count": aligned,
        "missed_gt": counts.get("missed_gt", 0),
        "false_positive": counts.get("false_positive", 0),
        "status_counts": dict(sorted(counts.items())),
        "mean_iou": round(sum(row["iou"] for row in matched) / scored, 4) if scored else 0.0,
        "mean_center_distance": round(sum(row["center_distance"] for row in matched) / scored, 2) if scored else None,
        "max_abs_y_offset": round(max(abs(row["y_offset"]) for row in matched), 2) if matched else None,
        "max_label_overlap_risk": round(max(row["label_overlap_risk"] or 0 for row in rows), 4) if rows else 0.0,
        "max_checkbox_label_anchor_distance": round(max(row["checkbox_label_anchor_distance"] or 0 for row in rows), 2) if rows else 0.0,
        "alignment_rate": round(aligned / scored, 4) if scored else 0.0,
    }


def draw_box(draw: ImageDraw.ImageDraw, page: RenderedPage, bbox: list[float], color: tuple[int, int, int], width: int, label: str | None = None) -> None:
    x, y, w, h = bbox
    rect = [x * page.scale, y * page.scale, (x + w) * page.scale, (y + h) * page.scale]
    draw.rectangle(rect, outline=(*color, 240), width=width)
    if label:
        font = get_font(13)
        tx, ty = rect[0] + 3, max(0, rect[1] - 17)
        draw.rectangle([tx - 2, ty - 1, tx + len(label) * 7 + 5, ty + 15], fill=(*color, 220))
        draw.text((tx, ty), label, fill=(255, 255, 255, 255), font=font)


def render_overlays(
    pages: list[RenderedPage],
    rows: list[dict[str, Any]],
    output_dir: Path,
    doc_id: str,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    font = get_font(15)
    paths: list[str] = []
    rows_by_page: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("page"):
            rows_by_page.setdefault(int(row["page"]), []).append(row)

    for page in pages:
        image = page.image.convert("RGBA")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for row in rows_by_page.get(page.page_num, []):
            gt_box = row.get("ground_truth_bbox")
            det_box = row.get("detected_bbox")
            if gt_box:
                draw_box(draw, page, gt_box, GT_COLOR, 2, f"GT {row.get('field_id')}")
            if det_box:
                color = STATUS_COLORS.get(row["status"], DET_COLOR)
                draw_box(draw, page, det_box, color, 3, f"{row.get('detection_id') or 'det'} {row['status']}")

        draw.rectangle([0, 0, image.width, 42], fill=(20, 20, 22, 230))
        draw.text(
            (10, 10),
            f"{doc_id} page {page.page_num} - geometry alignment",
            fill=(255, 255, 255, 255),
            font=font,
        )
        output = Image.alpha_composite(image, overlay).convert("RGB")
        path = output_dir / f"{doc_id}_p{page.page_num}.png"
        output.save(path)
        paths.append(rel(path))
    return paths


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "doc_id",
        "page",
        "field_id",
        "detection_id",
        "field_type",
        "ground_truth_type",
        "iou",
        "center_distance",
        "x_offset",
        "y_offset",
        "baseline_distance",
        "printed_line_overlap",
        "visible_checkbox_center_distance",
        "checkbox_label_anchor_distance",
        "label_overlap_risk",
        "status",
        "gt_needs_review",
        "detected_bbox",
        "ground_truth_bbox",
        "label_overlap_words",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            csv_row = row.copy()
            csv_row["detected_bbox"] = json.dumps(csv_row["detected_bbox"])
            csv_row["ground_truth_bbox"] = json.dumps(csv_row["ground_truth_bbox"])
            csv_row["label_overlap_words"] = " ".join(csv_row["label_overlap_words"])
            writer.writerow({column: csv_row.get(column) for column in columns})


def write_markdown(path: Path, result: dict[str, Any]) -> None:
    agg = result["aggregate"]
    gt_status = result["ground_truth"]["review_status"]
    lines = [
        f"# Geometry Alignment Score - {result['doc_id']}",
        "",
        "## Summary",
        "",
        f"- Created: {result['created_at']}",
        f"- Backend: `{result['backend']}`",
        f"- Source PDF: `{result['pdf']}`",
        f"- Ground truth: `{result['ground_truth']['path'] or 'none'}` ({gt_status})",
        f"- Draft warning: {result['ground_truth']['needs_review']}",
        f"- Fields: GT {agg['ground_truth_field_count']}, detected {agg['detected_count']}, matched {agg['matched_count']}",
        f"- Alignment rate: {agg['alignment_rate']:.4f}",
        f"- Mean IoU: {agg['mean_iou']:.4f}",
        f"- Mean center distance: {agg['mean_center_distance']}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in agg["status_counts"].items():
        lines.append(f"- {status}: {count}")
    lines.extend([
        "",
        "## Per Field",
        "",
        "| Field | Detection | Type | IoU | Center Dist | X Off | Y Off | Label Risk | Checkbox Dist | Status |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for row in result["fields"]:
        lines.append(
            f"| `{row.get('field_id') or '-'}` | `{row.get('detection_id') or '-'}` | "
            f"{row.get('field_type') or '-'} | {row.get('iou')} | {row.get('center_distance')} | "
            f"{row.get('x_offset')} | {row.get('y_offset')} | {row.get('label_overlap_risk')} | "
            f"{row.get('checkbox_label_anchor_distance') or row.get('visible_checkbox_center_distance')} | {row.get('status')} |"
        )
    lines.extend([
        "",
        "## Notes",
        "",
        "- This is diagnostic experiment output; draft ground truth is not promoted by this script.",
        "- Baseline-distance and printed-line overlap are populated for line-like targets when measurable.",
        "- Checkbox distance uses label-anchored square glyphs when available, with image components as a fallback signal.",
        "",
    ])
    if result["overlays"]:
        lines.extend(["## Overlays", ""])
        lines.extend(f"- `{overlay}`" for overlay in result["overlays"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True, help="Corpus manifest document id")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Corpus manifest path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Experiment output directory")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help="Backend to score")
    parser.add_argument("--dpi", type=int, default=150, help="Overlay render DPI")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear output directory first")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    assert_under_root(manifest_path, "manifest")
    assert_under_root(out_dir, "output directory")

    entry = load_manifest_entry(manifest_path, args.doc)
    pdf_path = resolve_pdf_path(entry)
    assert_under_root(pdf_path, "PDF")
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    gt_path, gt = load_ground_truth(entry)
    if gt is None:
        print(f"ERROR: ground truth not found: {gt_path or '(missing path)'}", file=sys.stderr)
        return 1

    if out_dir.exists() and not args.no_clear:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    detections, detect_seconds = run_backend(pdf_path, args.backend)
    pages, doc = render_pdf(pdf_path, args.dpi)
    try:
        draft_gt = bool(gt.get("needs_review") or gt.get("review_status") == "draft" or str(gt_path).endswith(".draft.json"))
        rows = score_fields(
            detections=detections,
            ground_truth=gt.get("fields", []),
            pages=pages,
            doc=doc,
            draft_gt=draft_gt,
        )
    finally:
        doc.close()

    for row in rows:
        row["doc_id"] = args.doc

    overlays = render_overlays(pages, rows, out_dir / "overlays", args.doc)
    result = {
        "experiment": "geometry_alignment_1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "doc_id": args.doc,
        "manifest": rel(manifest_path),
        "pdf": rel(pdf_path),
        "backend": args.backend,
        "detect_seconds": round(detect_seconds, 3),
        "ground_truth": {
            "path": rel(gt_path) if gt_path else None,
            "pdf_id": gt.get("pdf_id"),
            "review_status": gt.get("review_status", "reviewed"),
            "needs_review": bool(gt.get("needs_review")),
            "field_count": len(gt.get("fields", [])),
        },
        "aggregate": aggregate(rows, detections, gt),
        "fields": rows,
        "overlays": overlays,
    }

    write_json(out_dir / "score.json", result)
    write_csv(out_dir / "score.csv", rows)
    write_markdown(out_dir / "score.md", result)

    print("Geometry alignment score")
    print(f"  Document: {args.doc}")
    print(f"  Backend: {args.backend}")
    print(f"  Ground truth: {rel(gt_path) if gt_path else '(none)'} needs_review={result['ground_truth']['needs_review']}")
    print(f"  Output: {rel(out_dir)}")
    print(f"  Fields: GT={result['aggregate']['ground_truth_field_count']} detected={result['aggregate']['detected_count']} matched={result['aggregate']['matched_count']}")
    print(f"  Alignment rate: {result['aggregate']['alignment_rate']:.4f}")
    print(f"  Status counts: {result['aggregate']['status_counts']}")
    print(f"  Markdown: {rel(out_dir / 'score.md')}")
    print(f"  Overlay count: {len(overlays)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
