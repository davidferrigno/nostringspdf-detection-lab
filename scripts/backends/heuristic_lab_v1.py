#!/usr/bin/env python3
"""
heuristic_lab_v1.py

Detection Lab heuristic backend v1.

Generic content-stream-based field detection. Reads a PDF via pdfplumber,
extracts horizontal/vertical edges, detects underlines (with box-edge
rejection and label-based noise filtering), detects checkboxes (rect-based,
glyph-based, and colon-pattern-based), deduplicates, and returns a flat
list of Field dicts matching the ground truth schema.

ARCHITECTURE
============

Pipeline (single file, no hidden state):

    1. extract_page_data(page)
         → chars, rects, curves, edges, page dimensions

    2. classify_lines(edges)
         → horizontal lines, vertical lines (with tolerance)

    3. group_lines(lines, key)
         → merge nearby segments (h: extend x-span; v: keep distinct spans)

    4. group_horizontal_segments(lines)
         → bridge small gaps between collinear h-segments

    5. detect_underlines(h_lines, v_lines, chars, page_height)
         → underline-based text fields with prose-rejection filters

    6. detect_checkboxes(rects, curves, chars)
         → checkbox/radio detection from rectangles, glyphs, colon patterns

    7. deduplicate(fields)
         → keep larger / prefer checkbox in overlap zone

    8. detect(pdf_path)
         → public entry point. Returns flat Field list across all pages.

WHAT THIS DELIBERATELY DOES NOT DO (vs. production):

    - No grid cell classification
    - No char-box (segmented input) detection
    - No labeled-pair detection (Date/Place synthesis)
    - No text-pattern underlines (____ or ....)
    - No noise filtering by form context
    - No form-specific cleanup (Marriage, Eden, Field Trip)
    - No OCR raster fallback
    - No Azure backend
    - No radio grouping (all selection marks classified as checkbox)
    - No rendering hints (fieldStyle, fontSize, guideOffset)

These are deliberate omissions. The point of v1 is to measure the simplest
viable generic algorithm honestly, then add stages by measurement-driven
priority.

OUTPUT SCHEMA (matches ground truth):

    {
        "id": "d{N}",          # auto-numbered globally
        "page": int,           # 1-indexed
        "type": str,           # "text" | "checkbox"
        "bbox": [x, y, w, h],  # top-left origin, PDF points
        "label": str | None,
    }

Coordinate convention: pdfplumber returns y with top-left origin. Ground
truth uses top-left origin. No flip needed.

USAGE (from run_benchmark.py):

    from scripts.backends.heuristic_lab_v1 import detect
    fields = detect(Path("samples/acroforms/raw/irs/irs_w9.pdf"))
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Text helpers (ported from production)
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def rect_to_box(rect: dict) -> dict:
    x0 = rect.get("x0", 0)
    x1 = rect.get("x1", 0)
    y0 = rect.get("top", rect.get("y0", 0))
    y1 = rect.get("bottom", rect.get("y1", 0))
    return {
        "x": round(x0, 1),
        "y": round(y0, 1),
        "width": round(x1 - x0, 1),
        "height": round(y1 - y0, 1),
    }


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------

def classify_lines(edges: list, tol: float = 2.0) -> tuple[list, list]:
    """
    Split edges into horizontal and vertical lines.

    Horizontal: dy ≤ tol and dx > 15
    Vertical:   dx ≤ tol and dy > 8
    """
    h, v = [], []
    for e in edges:
        x0, x1 = e.get("x0", 0), e.get("x1", 0)
        y0 = e.get("top", e.get("y0", 0))
        y1 = e.get("bottom", e.get("y1", 0))
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        if dy <= tol and dx > 15:
            h.append({
                "y": round((y0 + y1) / 2, 1),
                "x0": round(min(x0, x1), 1),
                "x1": round(max(x0, x1), 1),
                "width": round(dx, 1),
            })
        elif dx <= tol and dy > 8:
            v.append({
                "x": round((x0 + x1) / 2, 1),
                "y0": round(min(y0, y1), 1),
                "y1": round(max(y0, y1), 1),
                "height": round(dy, 1),
            })
    return h, v


def group_lines(lines: list, key: str, threshold: float = 3.0) -> list:
    """
    Group nearby lines by `key` ('y' for horizontal, 'x' for vertical).

    Horizontal: merge same-y lines, extend x-span.
    Vertical:   group by x, but keep separate segments that don't overlap.
                Only merge overlapping or adjacent spans (5pt gap).
    """
    if not lines:
        return []
    s = sorted(lines, key=lambda l: l[key])
    groups = [[s[0]]]
    for line in s[1:]:
        if line[key] - groups[-1][-1][key] <= threshold:
            groups[-1].append(line)
        else:
            groups.append([line])

    result = []
    for g in groups:
        if key == "y":
            m = {"y": round(sum(l["y"] for l in g) / len(g), 1)}
            m["x0"] = round(min(l["x0"] for l in g), 1)
            m["x1"] = round(max(l["x1"] for l in g), 1)
            m["width"] = round(m["x1"] - m["x0"], 1)
            result.append(m)
        else:
            avg_x = round(sum(l["x"] for l in g) / len(g), 1)
            segs = sorted(g, key=lambda l: l["y0"])
            merged_segs = [{"y0": segs[0]["y0"], "y1": segs[0]["y1"]}]
            for seg in segs[1:]:
                last = merged_segs[-1]
                if seg["y0"] <= last["y1"] + 5:
                    last["y1"] = max(last["y1"], seg["y1"])
                else:
                    merged_segs.append({"y0": seg["y0"], "y1": seg["y1"]})
            for ms in merged_segs:
                result.append({
                    "x": avg_x,
                    "y0": round(ms["y0"], 1),
                    "y1": round(ms["y1"], 1),
                    "height": round(ms["y1"] - ms["y0"], 1),
                })
    return result


def group_horizontal_segments(lines: list, y_threshold: float = 1.5, gap_threshold: float = 12.0) -> list:
    """
    Bridge small gaps between collinear horizontal segments.

    Used to merge fragmented underlines into single field zones.
    """
    if not lines:
        return []
    ordered = sorted(lines, key=lambda line: (line["y"], line["x0"]))
    rows = []
    for line in ordered:
        if not rows or abs(rows[-1][0]["y"] - line["y"]) > y_threshold:
            rows.append([line])
        else:
            rows[-1].append(line)

    segments = []
    for row in rows:
        merged = []
        for line in sorted(row, key=lambda item: item["x0"]):
            if not merged:
                merged.append(dict(line))
                continue
            prev = merged[-1]
            if line["x0"] <= prev["x1"] + gap_threshold:
                prev["x1"] = max(prev["x1"], line["x1"])
                prev["width"] = round(prev["x1"] - prev["x0"], 1)
            else:
                merged.append(dict(line))
        segments.extend(merged)
    return segments


# ---------------------------------------------------------------------------
# Selection box helpers
# ---------------------------------------------------------------------------

def dedupe_selection_boxes(boxes: list) -> list:
    """Remove near-identical selection marks (within 2.5pt center-to-center)."""
    deduped = []
    for box in sorted(boxes, key=lambda item: item["width"] * item["height"], reverse=True):
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        if any(
            abs(cx - (existing["x"] + existing["width"] / 2)) <= 2.5
            and abs(cy - (existing["y"] + existing["height"] / 2)) <= 2.5
            for existing in deduped
        ):
            continue
        deduped.append(box)
    return deduped


def looks_like_char_box_row(boxes: list) -> bool:
    """
    Detect rows of small adjacent squares (segmented input like SSN/EIN boxes).
    These should NOT be classified as checkboxes.
    """
    if len(boxes) < 5:
        return False
    ordered = sorted(boxes, key=lambda box: box["x"])
    widths = [box["width"] for box in ordered]
    median_width = sorted(widths)[len(widths) // 2]
    gaps = [
        ordered[i + 1]["x"] - (ordered[i]["x"] + ordered[i]["width"])
        for i in range(len(ordered) - 1)
    ]
    close_gaps = [gap for gap in gaps if 0 <= gap <= median_width * 1.5]
    return len(close_gaps) >= max(3, len(gaps) - 1)


# ---------------------------------------------------------------------------
# Token extraction (for colon-pattern checkbox detection)
# ---------------------------------------------------------------------------

def extract_line_tokens(chars: list) -> list:
    """Group chars on the same line into word tokens."""
    tokens = []
    current = []
    prev_x1 = None
    for char in sorted(chars, key=lambda item: item.get("x0", 0)):
        text = char.get("text", "")
        if not text.strip():
            if current:
                token_text = normalize_text("".join(item.get("text", "") for item in current))
                if token_text:
                    tokens.append({
                        "text": token_text,
                        "x0": current[0].get("x0", 0),
                        "x1": current[-1].get("x1", 0),
                        "top": min(item.get("top", 0) for item in current),
                        "bottom": max(item.get("bottom", item.get("top", 0) + item.get("size", 10))
                                      for item in current),
                    })
                current = []
                prev_x1 = None
            continue
        gap = (char.get("x0", 0) - prev_x1) if prev_x1 is not None else 0
        if current and gap > max(4, char.get("size", 10) * 0.35):
            token_text = normalize_text("".join(item.get("text", "") for item in current))
            if token_text:
                tokens.append({
                    "text": token_text,
                    "x0": current[0].get("x0", 0),
                    "x1": current[-1].get("x1", 0),
                    "top": min(item.get("top", 0) for item in current),
                    "bottom": max(item.get("bottom", item.get("top", 0) + item.get("size", 10))
                                  for item in current),
                })
            current = []
        current.append(char)
        prev_x1 = char.get("x1", 0)
    if current:
        token_text = normalize_text("".join(item.get("text", "") for item in current))
        if token_text:
            tokens.append({
                "text": token_text,
                "x0": current[0].get("x0", 0),
                "x1": current[-1].get("x1", 0),
                "top": min(item.get("top", 0) for item in current),
                "bottom": max(item.get("bottom", item.get("top", 0) + item.get("size", 10))
                              for item in current),
            })
    return tokens


# ---------------------------------------------------------------------------
# Underline detection
# ---------------------------------------------------------------------------

def detect_underlines(raw_h_lines: list, all_verticals: list, chars: list, page_height: float) -> list:
    """
    Detect underline-based text fields from horizontal segments.

    Rejects:
      - Lines that pair with parallel siblings + connecting verticals (box edges)
      - Lines whose extracted label looks like prose (4+ words, mostly connectors)
      - Lines at extreme top (banner noise) or extreme bottom (footer noise)
      - Generic wide lines with no label (paragraph artifacts)
      - Narrow lines with verbose labels
    """
    fields = []
    grouped_h = group_horizontal_segments(raw_h_lines) if raw_h_lines else []

    def is_box_edge(line):
        """Check if `line` is the top/bottom of a closed rectangle."""
        for other in grouped_h:
            if other is line:
                continue
            dy = abs(other["y"] - line["y"])
            if dy < 0.5 or dy > 300:
                continue
            if not (abs(other["x0"] - line["x0"]) <= 3 and abs(other["x1"] - line["x1"]) <= 3):
                continue
            y_top = min(line["y"], other["y"])
            y_bot = max(line["y"], other["y"])
            has_left = False
            has_right = False
            for v in all_verticals or []:
                v_x = v.get("x", 0)
                v_y0 = v.get("y0", 0)
                v_y1 = v.get("y1", 0)
                v_top, v_bot = min(v_y0, v_y1), max(v_y0, v_y1)
                if v_bot < y_top - 2 or v_top > y_bot + 2:
                    continue
                if abs(v_x - line["x0"]) <= 3:
                    has_left = True
                if abs(v_x - line["x1"]) <= 3:
                    has_right = True
                if has_left and has_right:
                    return True
        return False

    # Pre-compute siblings on same row for each line
    siblings_on_row = {}
    for i, line_i in enumerate(grouped_h):
        count = sum(
            1 for j, line_j in enumerate(grouped_h)
            if i != j and abs(line_j["y"] - line_i["y"]) < 1.5
        )
        siblings_on_row[id(line_i)] = count

    for line in grouped_h:
        if line["width"] < 30:
            continue
        if is_box_edge(line):
            continue

        line_y = line["y"]

        # Extract label: characters to the left of and on the same baseline
        nearby = [
            char for char in chars
            if abs(char.get("bottom", char.get("top", 0) + char.get("size", 10)) - line_y) < 8
            and char.get("x1", 0) < line["x0"] + 10
        ]
        label = normalize_text("".join(char.get("text", "") for char in nearby))[-30:]

        if not label:
            # Try characters directly above
            above = [
                char for char in chars
                if char.get("top", 0) > line_y - 16
                and char.get("bottom", 0) < line_y
                and char.get("x0", 0) >= line["x0"] - 5
                and char.get("x1", 0) <= line["x1"] + 5
            ]
            label = normalize_text("".join(char.get("text", "") for char in above))[:30]

        # Reject label that's just hyphens/whitespace
        if re.fullmatch(r"[-\s]+", label or ""):
            continue

        # Prose rejection: 4+ words, dominant connectors, mostly lowercase
        prose_label = label or ""
        if not prose_label.rstrip().endswith(":"):
            label_word_list = re.findall(r"\b[a-zA-Z']+\b", prose_label)
            if len(label_word_list) >= 4:
                connectors = {
                    "and", "of", "the", "with", "before", "after",
                    "me", "my", "at", "on", "in", "by", "for",
                    "this", "that", "these", "those", "is", "are",
                    "was", "were", "to", "from",
                }
                connector_count = sum(1 for w in label_word_list if w.lower() in connectors)
                uppercase_count = sum(1 for w in label_word_list if w[0].isupper())
                if connector_count >= 2 and uppercase_count < len(label_word_list) / 2:
                    # Narrow underline in multi-segment row: drop label, keep field
                    if siblings_on_row.get(id(line), 0) >= 1 and line["width"] < 200:
                        label = ""
                    else:
                        continue

        label_words = len(re.findall(r"[A-Za-z0-9']+", label))
        label_looks_field_like = label.endswith(":") or bool(
            re.search(
                r"\b(name|address|city|state|zip|date|signature|license|"
                r"ceremony|day|applicant|witness)\b",
                label, re.I,
            )
        )
        top_noise = (line_y < 70 and not label_looks_field_like
                     and (not label or label == "Field" or label_words >= 4))
        banner_noise = (line_y < page_height * 0.2 and line["width"] > 300
                        and label_words >= 4 and not label_looks_field_like)
        generic_noise = (not label or label == "Field") and line["width"] > 250
        narrow_verbose = line["width"] < 250 and label_words >= 5 and not label_looks_field_like
        bottom_verbose = (line_y > page_height * 0.75 and label_words >= 4
                          and not label_looks_field_like)
        if top_noise or banner_noise or generic_noise or "@" in label or bottom_verbose or narrow_verbose:
            continue

        fields.append({
            "x": round(line["x0"], 1),
            "y": round(line_y - 12, 1),
            "width": round(line["width"], 1),
            "height": 12.0,
            "label": label or None,
            "type": "text",
        })
    return fields


# ---------------------------------------------------------------------------
# Checkbox detection
# ---------------------------------------------------------------------------

CHECKBOX_GLYPHS = {
    "\u2610",  # ballot box
    "\u25FB",  # white medium square
    "\u25A1",  # white square
    "\uF06F", "\uF070", "\uF071", "\uF0A8", "\uF0FE",  # wingdings
}


def detect_checkboxes(rects: list, curves: list, chars: list) -> list:
    """
    Detect checkbox fields via three strategies:

      1. Small square rectangles (6-24pt) — most common in vector PDFs
      2. Checkbox glyph characters (Unicode + Wingdings)
      3. Colon-pattern: "Label: Option1 Option2 Option3" implies checkboxes
         to the left of each option word

    Filters out char_box rows (segmented input like SSN/EIN).
    All selection marks classified as "checkbox" in this v1 (radio
    classification is left for v2).
    """
    fields = []

    # Strategy 1: Small rectangles and curves
    selection_boxes = []
    for rect in rects:
        box = rect_to_box(rect)
        if 6 <= box["width"] <= 24 and 6 <= box["height"] <= 24:
            selection_boxes.append(box)
    for curve in curves or []:
        box = rect_to_box(curve)
        if 6 <= box["width"] <= 24 and 6 <= box["height"] <= 24:
            selection_boxes.append(box)

    # Group by row and filter char-box rows
    rows = {}
    for box in dedupe_selection_boxes(selection_boxes):
        rows.setdefault(round(box["y"] / 6) * 6, []).append(box)

    for row_boxes in rows.values():
        if looks_like_char_box_row(row_boxes):
            continue
        for box in row_boxes:
            # Find label: characters to the right of the box, same row
            nearby = [
                char for char in chars
                if char.get("text", "").strip()
                and char.get("x0", 0) >= box["x"] + box["width"] + 2
                and char.get("x0", 0) <= box["x"] + 140
                and char.get("top", 0) <= box["y"] + box["height"] + 4
                and char.get("bottom", char.get("top", 0) + char.get("size", 10)) >= box["y"] - 4
            ]
            label = normalize_text("".join(
                char.get("text", "")
                for char in sorted(nearby, key=lambda item: item.get("x0", 0))
            ))
            fields.append({
                "x": box["x"],
                "y": box["y"],
                "width": box["width"],
                "height": box["height"],
                "label": label or None,
                "type": "checkbox",
            })

    # Strategy 2: Checkbox glyph characters
    for char in chars:
        if char.get("text", "") not in CHECKBOX_GLYPHS:
            continue
        size = char.get("size", 10)
        fields.append({
            "x": round(char.get("x0", 0), 1),
            "y": round(char.get("top", char.get("y0", 0)), 1),
            "width": round(size * 1.2, 1),
            "height": round(size * 1.2, 1),
            "label": None,
            "type": "checkbox",
        })

    # Strategy 3: Colon-pattern "Label: Option Option Option"
    line_groups = {}
    for char in chars:
        if char.get("text", "").strip():
            line_groups.setdefault(round(char.get("top", 0) / 4) * 4, []).append(char)

    for line_chars in line_groups.values():
        tokens = extract_line_tokens(line_chars)
        if len(tokens) < 4:
            continue
        colon_idx = next(
            (idx for idx, token in enumerate(tokens)
             if token["text"].endswith(":") or token["text"] == ":"),
            -1,
        )
        if colon_idx < 0:
            continue
        candidates = []
        for idx in range(colon_idx + 1, len(tokens)):
            previous = tokens[idx - 1]
            token = tokens[idx]
            gap = token["x0"] - previous["x1"]
            word = token["text"].strip(".,;:()")
            if 10 <= gap <= 40 and re.fullmatch(r"[A-Za-z][A-Za-z/&-]{1,14}", word):
                candidates.append((token, word, gap))
        if len(candidates) < 2:
            continue
        for token, word, gap in candidates:
            height = token["bottom"] - token["top"]
            size = min(12.0, max(8.0, height))
            fields.append({
                "x": round(token["x0"] - size, 1),
                "y": round(token["top"], 1),
                "width": round(size, 1),
                "height": round(size, 1),
                "label": word,
                "type": "checkbox",
            })

    return fields


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def deduplicate(fields: list, threshold: float = 6.0) -> list:
    """
    Remove duplicate fields (same page, within `threshold` pt of each other).
    Prefer checkboxes over text. Otherwise keep the larger field.
    """
    result = []
    for field in fields:
        duplicate = False
        for existing in list(result):
            if existing.get("page") != field.get("page"):
                continue
            if abs(existing["x"] - field["x"]) < threshold and abs(existing["y"] - field["y"]) < threshold:
                keep_new = (
                    field.get("type") == "checkbox"
                    or (field["width"] * field["height"] > existing["width"] * existing["height"])
                )
                if keep_new:
                    result.remove(existing)
                    result.append(field)
                duplicate = True
                break
        if not duplicate:
            result.append(field)
    return result


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def detect(pdf_path: Path) -> list[dict]:
    """
    Run the heuristic detection pipeline on `pdf_path`.

    Returns a flat list of Field dicts (one per detected field across all
    pages), matching the ground truth schema:

        {"id": "d{N}", "page": int, "type": str, "bbox": [x, y, w, h], "label": str|None}

    Coordinate convention: top-left origin, PDF points.
    """
    all_fields = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                try:
                    chars = page.chars or []
                    rects = page.rects or []
                    curves = page.curves or []
                    edges = page.edges or []
                    page_height = float(page.height or 0)
                except Exception:
                    continue

                # 1. Line classification
                h_lines_raw, v_lines_raw = classify_lines(edges)

                # 2. Group lines
                h_lines = group_lines(list(h_lines_raw), "y") if h_lines_raw else []
                v_lines = group_lines(list(v_lines_raw), "x") if v_lines_raw else []

                # 3. Detect underlines
                underline_fields = detect_underlines(h_lines_raw, v_lines, chars, page_height)

                # 4. Detect checkboxes
                checkbox_fields = detect_checkboxes(rects, curves, chars)

                # 5. Tag with page number and accumulate
                page_fields = underline_fields + checkbox_fields
                for f in page_fields:
                    f["page"] = page_idx + 1
                all_fields.extend(page_fields)

    except Exception as e:
        # Silent failure produces empty list; benchmark will record this as P=0/R=0
        sys.stderr.write(f"[heuristic_lab_v1] {pdf_path.name}: {type(e).__name__}: {e}\n")
        return []

    # 6. Deduplicate across all pages
    all_fields = deduplicate(all_fields)

    # 7. Convert to ground-truth schema with bbox list and globally-numbered IDs
    output = []
    for idx, f in enumerate(all_fields, start=1):
        if f.get("width", 0) <= 0 or f.get("height", 0) <= 0:
            continue
        output.append({
            "id": f"d{idx}",
            "page": f["page"],
            "type": f["type"],
            "bbox": [
                round(f["x"], 2),
                round(f["y"], 2),
                round(f["width"], 2),
                round(f["height"], 2),
            ],
            "label": f.get("label"),
        })

    return output


# ---------------------------------------------------------------------------
# Standalone CLI for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    if len(sys.argv) < 2:
        print("Usage: python heuristic_lab_v1.py <pdf_path>", file=sys.stderr)
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"ERROR: {pdf_path} does not exist", file=sys.stderr)
        sys.exit(1)

    fields = detect(pdf_path)
    print(f"Detected {len(fields)} fields in {pdf_path.name}")
    type_counts = {}
    for f in fields:
        type_counts[f["type"]] = type_counts.get(f["type"], 0) + 1
    for t, n in sorted(type_counts.items()):
        print(f"  {t}: {n}")
    if "--json" in sys.argv:
        print(json.dumps(fields, indent=2))
