#!/usr/bin/env python3
"""OCR/line-box experiment for scanned/image-only lab documents.

This is standalone experiment code. It does not modify production detectors or
lab benchmark scoring.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fitz
except ImportError:
    print("ERROR: PyMuPDF/fitz is required for rendering.", file=sys.stderr)
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow is required for geometry analysis and overlays.", file=sys.stderr)
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "corpus" / "manifest.json"
DEFAULT_OUT = ROOT / "experiments" / "ocr_linebox" / "runs" / "latest"
ALLOWED_PRIVACY = {"blank", "synthetic", "sensitive_do_not_store"}
TYPE_COLORS = {
    "text_line": (0, 122, 255),
    "text_box": (88, 86, 214),
    "checkbox": (52, 199, 89),
    "signature_line": (255, 59, 48),
    "date_field": (255, 149, 0),
    "narrative_box": (175, 82, 222),
    "unknown": (142, 142, 147),
}


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


def get_font(size: int = 15) -> ImageFont.ImageFont:
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


def is_scanned_entry(entry: dict[str, Any]) -> bool:
    return "scanned_image" in entry.get("lanes", [])


def has_image_only_signal(entry: dict[str, Any]) -> bool:
    """Infer scanned/image-only status from a manifest PDF without OCR."""
    if entry.get("privacy_status") == "sensitive_do_not_store":
        return False
    try:
        pdf_path = resolve_pdf_path(entry)
        if not pdf_path.exists():
            return False
        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            doc.close()
            return False
        text_chars = 0
        image_count = 0
        for page in doc:
            text_chars += len((page.get_text("text") or "").strip())
            image_count += len(page.get_images(full=True))
        page_count = doc.page_count
        doc.close()
        return text_chars == 0 and image_count >= page_count
    except Exception:
        return False


def ocr_status() -> dict[str, Any]:
    status = {
        "pytesseract_available": False,
        "tesseract_available": False,
        "error": None,
    }
    try:
        import pytesseract  # noqa: F401

        status["pytesseract_available"] = True
    except Exception as exc:
        status["error"] = f"pytesseract import failed: {type(exc).__name__}: {exc}"
        return status

    try:
        import pytesseract

        version = pytesseract.get_tesseract_version()
        status["tesseract_available"] = True
        status["tesseract_version"] = str(version)
    except Exception as exc:
        status["error"] = f"tesseract unavailable: {type(exc).__name__}: {exc}"
    return status


def render_pdf(pdf_path: Path, dpi: int) -> list[RenderedPage]:
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
    doc.close()
    return pages


def dark_pixel_mask(image: Image.Image, threshold: int = 105) -> Image.Image:
    gray = image.convert("L")
    return gray.point(lambda value: 255 if value < threshold else 0, mode="1")


def looks_like_checkbox_outline(gray: Image.Image, x0: int, y0: int, x1: int, y1: int) -> bool:
    """Prefer hollow square outlines over text glyph fragments."""
    width = x1 - x0 + 1
    height = y1 - y0 + 1
    if width < 11 or height < 11:
        return False
    px = gray.load()
    border_dark = 0
    border_total = 0
    for x in range(x0, x1 + 1):
        for y in (y0, y1):
            border_total += 1
            if px[x, y] < 150:
                border_dark += 1
    for y in range(y0, y1 + 1):
        for x in (x0, x1):
            border_total += 1
            if px[x, y] < 150:
                border_dark += 1

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
                if px[x, y] < 150:
                    center_dark += 1

    border_ratio = border_dark / max(1, border_total)
    center_ratio = center_dark / max(1, center_total)
    return border_ratio >= 0.28 and center_ratio <= 0.18


def merge_runs(runs: list[tuple[int, int, int]], y_tolerance: int = 3, gap_tolerance: int = 10) -> list[tuple[int, int, int]]:
    if not runs:
        return []
    ordered = sorted(runs, key=lambda item: (item[0], item[1]))
    rows: list[list[tuple[int, int, int]]] = []
    for run in ordered:
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


def horizontal_line_segments(mask: Image.Image) -> list[tuple[int, int, int]]:
    width, height = mask.size
    px = mask.load()
    runs: list[tuple[int, int, int]] = []
    for y in range(0, height):
        x = 0
        while x < width:
            while x < width and px[x, y] == 0:
                x += 1
            start = x
            while x < width and px[x, y] != 0:
                x += 1
            if x - start >= 35:
                runs.append((y, start, x - 1))
    return merge_runs(runs)


def vertical_line_segments(mask: Image.Image) -> list[tuple[int, int, int]]:
    width, height = mask.size
    px = mask.load()
    runs: list[tuple[int, int, int]] = []
    for x in range(0, width):
        y = 0
        while y < height:
            while y < height and px[x, y] == 0:
                y += 1
            start = y
            while y < height and px[x, y] != 0:
                y += 1
            if y - start >= 35:
                runs.append((x, start, y - 1))

    if not runs:
        return []
    ordered = sorted(runs, key=lambda item: (item[0], item[1]))
    cols: list[list[tuple[int, int, int]]] = []
    for run in ordered:
        if not cols or abs(cols[-1][0][0] - run[0]) > 3:
            cols.append([run])
        else:
            cols[-1].append(run)

    merged: list[tuple[int, int, int]] = []
    for col in cols:
        col_x = round(sum(item[0] for item in col) / len(col))
        segments = sorted((y0, y1) for _, y0, y1 in col)
        cur_y0, cur_y1 = segments[0]
        for y0, y1 in segments[1:]:
            if y0 <= cur_y1 + 10:
                cur_y1 = max(cur_y1, y1)
            else:
                merged.append((col_x, cur_y0, cur_y1))
                cur_y0, cur_y1 = y0, y1
        merged.append((col_x, cur_y0, cur_y1))
    return merged


def component_boxes(mask: Image.Image, max_components: int = 2000) -> list[tuple[int, int, int, int, int]]:
    width, height = mask.size
    px = mask.load()
    visited: set[tuple[int, int]] = set()
    boxes: list[tuple[int, int, int, int, int]] = []

    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if px[x, y] == 0 or (x, y) in visited:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited.add((x, y))
            min_x = max_x = x
            min_y = max_y = y
            area = 0
            while queue:
                cx, cy = queue.popleft()
                area += 1
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
                    queue.append((nx, ny))
            boxes.append((min_x, min_y, max_x, max_y, area))
            if len(boxes) >= max_components:
                return boxes
    return boxes


def px_to_pdf_bbox(bbox: list[float], page: RenderedPage) -> list[float]:
    x, y, w, h = bbox
    return [round(x / page.scale, 2), round(y / page.scale, 2), round(w / page.scale, 2), round(h / page.scale, 2)]


def make_candidate(
    page: RenderedPage,
    candidate_type: str,
    image_bbox: list[float],
    confidence: float,
    source: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "page": page.page_num,
        "type": candidate_type,
        "bbox": px_to_pdf_bbox(image_bbox, page),
        "image_bbox": [round(v, 1) for v in image_bbox],
        "confidence": round(confidence, 3),
        "source": source,
        "notes": notes,
    }


def detect_candidates(page: RenderedPage) -> list[dict[str, Any]]:
    gray = page.image.convert("L")
    mask = dark_pixel_mask(page.image)
    image_width, image_height = page.image.size
    h_lines = horizontal_line_segments(mask)
    v_lines = vertical_line_segments(mask)
    candidates: list[dict[str, Any]] = []

    for y, x0, x1 in h_lines:
        line_width = x1 - x0 + 1
        if line_width < 50:
            continue
        # Ignore page borders and dense text baselines near the top.
        if y < image_height * 0.06 or y > image_height * 0.96:
            continue
        if line_width > image_width * 0.94:
            continue

        candidate_type = "text_line"
        confidence = 0.58
        notes = "horizontal rule/underline candidate"
        if line_width > image_width * 0.55 and image_height * 0.32 < y < image_height * 0.82:
            candidate_type = "narrative_box"
            confidence = 0.52
            notes = "wide horizontal rule inside narrative region"
        if y > image_height * 0.78 and image_width * 0.18 < line_width < image_width * 0.62:
            candidate_type = "signature_line"
            confidence = 0.64
            notes = "lower-page horizontal rule, possible signature line"
        if y > image_height * 0.55 and image_width * 0.06 < line_width < image_width * 0.25:
            candidate_type = "date_field"
            confidence = 0.55
            notes = "short lower-page horizontal rule, possible date field"

        box_height = 18 if candidate_type != "narrative_box" else 24
        image_bbox = [x0, max(0, y - box_height + 2), line_width, box_height]
        candidates.append(make_candidate(page, candidate_type, image_bbox, confidence, "linebox_v1", notes))

    # Rectangle/text-box candidates from nearby horizontal and vertical rules.
    for top_y, top_x0, top_x1 in h_lines:
        for bot_y, bot_x0, bot_x1 in h_lines:
            if bot_y <= top_y:
                continue
            height = bot_y - top_y
            if height < 35 or height > image_height * 0.42:
                continue
            x0 = max(top_x0, bot_x0)
            x1 = min(top_x1, bot_x1)
            width = x1 - x0
            if width < image_width * 0.22:
                continue
            left_ok = any(abs(vx - x0) < 18 and vy0 <= top_y + 12 and vy1 >= bot_y - 12 for vx, vy0, vy1 in v_lines)
            right_ok = any(abs(vx - x1) < 18 and vy0 <= top_y + 12 and vy1 >= bot_y - 12 for vx, vy0, vy1 in v_lines)
            if not (left_ok or right_ok):
                continue
            ctype = "narrative_box" if height > image_height * 0.16 else "text_box"
            candidates.append(make_candidate(
                page,
                ctype,
                [x0, top_y, width, height],
                0.54,
                "geometry_v1",
                "rectangle-like region from horizontal/vertical rules",
            ))

    # Checkbox candidates from square-ish connected components.
    for x0, y0, x1, y1, area in component_boxes(mask):
        width = x1 - x0 + 1
        height = y1 - y0 + 1
        if width < 9 or height < 9 or width > 46 or height > 46:
            continue
        aspect = width / height
        if not (0.72 <= aspect <= 1.28):
            continue
        density = area / max(1, width * height)
        if not (0.08 <= density <= 0.52):
            continue
        if y0 < image_height * 0.05:
            continue
        if not looks_like_checkbox_outline(gray, x0, y0, x1, y1):
            continue
        candidates.append(make_candidate(
            page,
            "checkbox",
            [x0, y0, width, height],
            0.48,
            "geometry_v1",
            "square-ish dark component candidate",
        ))

    return dedupe_candidates(candidates)


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
    return inter / max(1.0, aw * ah + bw * bh - inter)


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    type_priority = {
        "checkbox": 6,
        "signature_line": 5,
        "date_field": 4,
        "narrative_box": 3,
        "text_box": 2,
        "text_line": 1,
        "unknown": 0,
    }
    ordered = sorted(
        candidates,
        key=lambda c: (type_priority.get(c["type"], 0), c["confidence"], c["bbox"][2] * c["bbox"][3]),
        reverse=True,
    )
    kept: list[dict[str, Any]] = []
    for cand in ordered:
        if any(cand["page"] == prev["page"] and iou(cand["bbox"], prev["bbox"]) > 0.72 for prev in kept):
            continue
        kept.append(cand)
    kept.sort(key=lambda c: (c["page"], c["bbox"][1], c["bbox"][0], c["type"]))
    return kept


def render_overlay(page: RenderedPage, candidates: list[dict[str, Any]], output_path: Path) -> None:
    image = page.image.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = get_font(15)
    for index, cand in enumerate(candidates, start=1):
        x, y, w, h = cand["image_bbox"]
        color = TYPE_COLORS.get(cand["type"], TYPE_COLORS["unknown"])
        fill = (*color, 42)
        outline = (*color, 230)
        draw.rectangle([x, y, x + w, y + h], outline=outline, fill=fill, width=3)
        draw.text((x + 3, max(0, y - 18)), f"{index}:{cand['type']}", fill=outline, font=font)

    header_h = 34
    draw.rectangle([0, 0, image.width, header_h], fill=(20, 20, 22, 220))
    draw.text((10, 8), f"Page {page.page_num} - {len(candidates)} candidates", fill=(255, 255, 255, 255), font=font)
    output = Image.alpha_composite(image, overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.save(output_path)


def process_entry(entry: dict[str, Any], out_dir: Path, dpi: int, ocr_info: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": entry.get("id"),
        "path": entry.get("path") or entry.get("source_path"),
        "lanes": entry.get("lanes", []),
        "privacy_status": entry.get("privacy_status"),
        "status": "pending",
        "warnings": [],
        "ocr": ocr_info,
        "pages": [],
        "candidate_counts_by_type": {},
        "total_candidates": 0,
    }

    if result["privacy_status"] not in ALLOWED_PRIVACY:
        result["status"] = "privacy_error"
        result["warnings"].append(f"invalid privacy_status: {result['privacy_status']!r}")
        return result
    if result["privacy_status"] == "sensitive_do_not_store":
        result["status"] = "skipped_sensitive_local_only"
        result["warnings"].append("sensitive/local-only entries are skipped by this experiment")
        return result

    try:
        pdf_path = resolve_pdf_path(entry)
        assert_under_root(pdf_path, f"entry {entry.get('id')} path")
    except Exception as exc:
        result["status"] = "path_error"
        result["warnings"].append(str(exc))
        return result

    if not pdf_path.exists():
        result["status"] = "missing"
        result["warnings"].append(f"PDF not found: {pdf_path}")
        return result

    result["path"] = rel(pdf_path)
    rendered_pages = render_pdf(pdf_path, dpi=dpi)
    all_counts: Counter[str] = Counter()
    overlays_dir = out_dir / "overlays"

    for page in rendered_pages:
        candidates = detect_candidates(page)
        counts = Counter(c["type"] for c in candidates)
        all_counts.update(counts)
        overlay_path = overlays_dir / f"{entry['id']}_p{page.page_num}.png"
        render_overlay(page, candidates, overlay_path)
        result["pages"].append({
            "page": page.page_num,
            "pdf_size": [round(page.pdf_width, 2), round(page.pdf_height, 2)],
            "image_size": list(page.image.size),
            "candidate_count": len(candidates),
            "candidate_counts_by_type": dict(sorted(counts.items())),
            "overlay": rel(overlay_path),
            "candidates": candidates,
        })

    result["candidate_counts_by_type"] = dict(sorted(all_counts.items()))
    result["total_candidates"] = sum(all_counts.values())
    result["status"] = "ok"
    return result


def write_summary(results: list[dict[str, Any]], out_dir: Path, ocr_info: dict[str, Any]) -> None:
    total_pages = sum(len(r.get("pages", [])) for r in results)
    type_counts: Counter[str] = Counter()
    for result in results:
        type_counts.update(result.get("candidate_counts_by_type", {}))

    md_lines = [
        f"# OCR Line/Box Experiment - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        "",
        f"- Documents processed: {sum(1 for r in results if r['status'] == 'ok')}",
        f"- Documents skipped/missing/error: {sum(1 for r in results if r['status'] != 'ok')}",
        f"- Pages processed: {total_pages}",
        f"- Total candidates: {sum(type_counts.values())}",
        f"- OCR available: {ocr_info.get('tesseract_available', False)}",
    ]
    if ocr_info.get("error"):
        md_lines.append(f"- OCR note: {ocr_info['error']}")
    md_lines.extend(["", "## Candidate Counts By Type", ""])
    if type_counts:
        for ctype, count in sorted(type_counts.items()):
            md_lines.append(f"- {ctype}: {count}")
    else:
        md_lines.append("No candidates generated.")

    md_lines.extend([
        "",
        "## Per Document",
        "",
        "| Document | Status | Pages | Candidates | By type |",
        "| --- | --- | ---: | ---: | --- |",
    ])
    for result in results:
        by_type = ", ".join(f"{k}:{v}" for k, v in result.get("candidate_counts_by_type", {}).items()) or "-"
        md_lines.append(
            f"| `{result['id']}` | {result['status']} | {len(result.get('pages', []))} | "
            f"{result.get('total_candidates', 0)} | {by_type} |"
        )

    md_lines.extend([
        "",
        "## Top Failures / Limitations",
        "",
        "- OCR text blocks are omitted when the local Tesseract executable is unavailable.",
        "- Geometry candidates are first-pass review aids, not reviewed ground truth.",
        "- Checkbox detection uses square-ish dark components and may include small icons or text fragments.",
        "- Narrative region detection is based on wide horizontal rules and rectangle-like regions.",
        "",
        "## Recommended Next Step",
        "",
        "Review overlays for municipal pages 3-5, tune checkbox filtering, then add manually reviewed scanned-image ground truth.",
        "",
    ])
    (out_dir / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "status", "pages", "total_candidates", "candidate_counts_by_type", "warnings"])
        for result in results:
            writer.writerow([
                result["id"],
                result["status"],
                len(result.get("pages", [])),
                result.get("total_candidates", 0),
                json.dumps(result.get("candidate_counts_by_type", {}), sort_keys=True),
                "; ".join(result.get("warnings", [])),
            ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Queue manifest path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Experiment output directory")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI for image analysis")
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

    manifest = load_json(manifest_path)
    entries = [
        entry
        for entry in manifest.get("entries", [])
        if is_scanned_entry(entry) or has_image_only_signal(entry)
    ]
    if out_dir.exists() and not args.no_clear:
        shutil.rmtree(out_dir)
    (out_dir / "results").mkdir(parents=True, exist_ok=True)

    info = ocr_status()
    print("OCR/linebox experiment")
    print(f"Manifest: {rel(manifest_path)}")
    print(f"Output: {rel(out_dir)}")
    print(f"Scanned entries: {len(entries)}")
    print(f"OCR available: {info.get('tesseract_available', False)}")
    if info.get("error"):
        print(f"OCR note: {info['error']}")

    results = []
    for entry in entries:
        print(f"Processing {entry.get('id')} ... ", end="", flush=True)
        result = process_entry(entry, out_dir, args.dpi, info)
        results.append(result)
        (out_dir / "results" / f"{result['id']}.json").write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{result['status']} candidates={result.get('total_candidates', 0)}")

    write_summary(results, out_dir, info)
    print(f"Summary: {rel(out_dir / 'summary.md')}")
    print(f"CSV: {rel(out_dir / 'summary.csv')}")
    print(f"Results: {rel(out_dir / 'results')}")
    print(f"Overlays: {rel(out_dir / 'overlays')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
