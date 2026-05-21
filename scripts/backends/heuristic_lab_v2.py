#!/usr/bin/env python3
"""
heuristic_lab_v2.py

Adds char-box detection (Category 2 from failure_analysis_v1.md).

Char-boxes are rows of small adjacent squares for per-character input:
SSN (___-__-____), EIN, phone numbers, etc. The boxes ARE visible in
the content stream but v1 deliberately skipped them via
looks_like_char_box_row() inside detect_checkboxes.

v2 changes:
  1. Detect char-box rows EXPLICITLY via detect_char_boxes()
  2. Emit each row as a SINGLE text field spanning the row
  3. Pass char_box_fields to detect_checkboxes() so checkbox detection
     no longer skips them (it just doesn't re-emit them as checkboxes)
  4. Filter text underlines that overlap char-box rows

Algorithm for detect_char_boxes():
  - Find all rects + curves with width 6-30pt and height 6-30pt
    (wider than checkboxes; many segmented fields use ~15-20pt squares)
  - Group by row (y-bin of ~5pt)
  - For each row: require >=4 boxes with consistent width and close gaps
    (gap ≤ median_width * 1.5)
  - Emit as single text field spanning row x0 to row x1

Output schema unchanged from v1.
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
# Text helpers (unchanged from v1)
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
# Line classification (unchanged from v1)
# ---------------------------------------------------------------------------

def classify_lines(edges: list, tol: float = 2.0) -> tuple[list, list]:
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
# Selection box helpers (unchanged from v1)
# ---------------------------------------------------------------------------

def dedupe_selection_boxes(boxes: list) -> list:
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
# NEW in v2: Char-box row detection
# ---------------------------------------------------------------------------

def detect_char_boxes(rects: list, curves: list, chars: list) -> list:
    """
    Detect rows of small adjacent squares (segmented input fields like
    SSN, EIN, phone, account number). Emit each row as a single text field
    spanning the entire row.

    Width range: 6-30pt per box (wider than checkboxes alone — segmented
    fields often use ~12-20pt squares).
    Height range: 8-30pt per box.

    A row qualifies as char-box if:
      - >= 4 boxes
      - Consistent box width (within reasonable variance)
      - Small gaps between boxes (gap <= median_width * 1.5)

    Returns list of Field dicts (type="text") representing whole rows.
    """
    fields = []

    # Gather candidate boxes (broader range than checkbox-only)
    candidates = []
    for rect in rects:
        box = rect_to_box(rect)
        # Char-box squares are typically 8-25pt wide; allow up to 30 for taller forms
        if 6 <= box["width"] <= 30 and 8 <= box["height"] <= 30:
            # Reject boxes that are extremely wide-vs-tall or vice versa
            if box["width"] > 0 and box["height"] > 0:
                aspect = box["width"] / box["height"]
                if 0.5 <= aspect <= 2.5:  # roughly squarish
                    candidates.append(box)
    for curve in curves or []:
        box = rect_to_box(curve)
        if 6 <= box["width"] <= 30 and 8 <= box["height"] <= 30:
            if box["width"] > 0 and box["height"] > 0:
                aspect = box["width"] / box["height"]
                if 0.5 <= aspect <= 2.5:
                    candidates.append(box)

    candidates = dedupe_selection_boxes(candidates)

    # Group by row (5pt bins)
    rows = {}
    for box in candidates:
        rows.setdefault(round(box["y"] / 5) * 5, []).append(box)

    for row_y, row_boxes in rows.items():
        # Sort by x
        row_boxes = sorted(row_boxes, key=lambda b: b["x"])

        # Minimum 4 boxes (production uses 5; we lower to 4 to catch shorter
        # segmented fields like 4-digit account suffixes)
        if len(row_boxes) < 4:
            continue

        widths = [b["width"] for b in row_boxes]
        heights = [b["height"] for b in row_boxes]
        median_width = sorted(widths)[len(widths) // 2]
        median_height = sorted(heights)[len(heights) // 2]

        # Require width variance to be small (boxes are uniform)
        width_variance = max(widths) - min(widths)
        if width_variance > median_width * 0.6:
            continue

        # Compute gaps between consecutive boxes
        gaps = [
            row_boxes[i + 1]["x"] - (row_boxes[i]["x"] + row_boxes[i]["width"])
            for i in range(len(row_boxes) - 1)
        ]
        # Most gaps should be small (within median_width * 1.5)
        # Allow some large gaps for dash separators in SSN
        close_gaps = [g for g in gaps if 0 <= g <= median_width * 2.0]
        if len(close_gaps) < max(3, len(gaps) - 2):
            continue

        # Find a label to the left of the row, same baseline
        row_x0 = row_boxes[0]["x"]
        row_x1 = row_boxes[-1]["x"] + row_boxes[-1]["width"]
        row_top = min(b["y"] for b in row_boxes)
        row_bottom = max(b["y"] + b["height"] for b in row_boxes)
        row_center_y = (row_top + row_bottom) / 2

        nearby = [
            char for char in chars
            if char.get("text", "").strip()
            and char.get("x1", 0) < row_x0 + 5
            and char.get("x0", 0) > row_x0 - 240
            and char.get("top", 0) > row_top - 8
            and char.get("bottom", char.get("top", 0) + char.get("size", 10)) < row_bottom + 8
        ]
        label = normalize_text("".join(
            char.get("text", "") for char in sorted(nearby, key=lambda c: c.get("x0", 0))
        ))[-40:]

        fields.append({
            "x": round(row_x0, 1),
            "y": round(row_top, 1),
            "width": round(row_x1 - row_x0, 1),
            "height": round(median_height, 1),
            "label": label or None,
            "type": "text",
            "_char_box_row": True,  # marker for downstream filtering
        })

    return fields


# ---------------------------------------------------------------------------
# Token extraction (unchanged from v1)
# ---------------------------------------------------------------------------

def extract_line_tokens(chars: list) -> list:
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
# Underline detection (unchanged from v1)
# ---------------------------------------------------------------------------

def detect_underlines(raw_h_lines: list, all_verticals: list, chars: list, page_height: float) -> list:
    fields = []
    grouped_h = group_horizontal_segments(raw_h_lines) if raw_h_lines else []

    def is_box_edge(line):
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
        nearby = [
            char for char in chars
            if abs(char.get("bottom", char.get("top", 0) + char.get("size", 10)) - line_y) < 8
            and char.get("x1", 0) < line["x0"] + 10
        ]
        label = normalize_text("".join(char.get("text", "") for char in nearby))[-30:]

        if not label:
            above = [
                char for char in chars
                if char.get("top", 0) > line_y - 16
                and char.get("bottom", 0) < line_y
                and char.get("x0", 0) >= line["x0"] - 5
                and char.get("x1", 0) <= line["x1"] + 5
            ]
            label = normalize_text("".join(char.get("text", "") for char in above))[:30]

        if re.fullmatch(r"[-\s]+", label or ""):
            continue

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
# Checkbox detection (unchanged from v1 except: skips boxes inside char_box rows)
# ---------------------------------------------------------------------------

CHECKBOX_GLYPHS = {
    "\u2610",
    "\u25FB",
    "\u25A1",
    "\uF06F", "\uF070", "\uF071", "\uF0A8", "\uF0FE",
}


def detect_checkboxes(rects: list, curves: list, chars: list, char_box_fields: list = None) -> list:
    """
    Detect checkbox fields. If char_box_fields is provided, skip any
    rect that falls within a known char-box row (those are text fields,
    not checkboxes).
    """
    char_box_fields = char_box_fields or []
    fields = []

    # Pre-compute char-box row bounding boxes for fast overlap check
    cb_boxes = []
    for cbf in char_box_fields:
        cb_boxes.append({
            "x0": cbf["x"],
            "x1": cbf["x"] + cbf["width"],
            "y0": cbf["y"] - 3,
            "y1": cbf["y"] + cbf["height"] + 3,
        })

    def is_inside_char_box_row(box):
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        for cb in cb_boxes:
            if cb["x0"] <= cx <= cb["x1"] and cb["y0"] <= cy <= cb["y1"]:
                return True
        return False

    # Strategy 1: Small rectangles and curves
    selection_boxes = []
    for rect in rects:
        box = rect_to_box(rect)
        if 6 <= box["width"] <= 24 and 6 <= box["height"] <= 24:
            if not is_inside_char_box_row(box):
                selection_boxes.append(box)
    for curve in curves or []:
        box = rect_to_box(curve)
        if 6 <= box["width"] <= 24 and 6 <= box["height"] <= 24:
            if not is_inside_char_box_row(box):
                selection_boxes.append(box)

    rows = {}
    for box in dedupe_selection_boxes(selection_boxes):
        rows.setdefault(round(box["y"] / 6) * 6, []).append(box)

    for row_boxes in rows.values():
        if looks_like_char_box_row(row_boxes):
            continue
        for box in row_boxes:
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

    # Strategy 2: Checkbox glyph characters (skip if in char-box row)
    for char in chars:
        if char.get("text", "") not in CHECKBOX_GLYPHS:
            continue
        size = char.get("size", 10)
        box = {
            "x": round(char.get("x0", 0), 1),
            "y": round(char.get("top", char.get("y0", 0)), 1),
            "width": round(size * 1.2, 1),
            "height": round(size * 1.2, 1),
        }
        if is_inside_char_box_row(box):
            continue
        fields.append({
            "x": box["x"],
            "y": box["y"],
            "width": box["width"],
            "height": box["height"],
            "label": None,
            "type": "checkbox",
        })

    # Strategy 3: Colon-pattern
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
            box = {
                "x": round(token["x0"] - size, 1),
                "y": round(token["top"], 1),
                "width": round(size, 1),
                "height": round(size, 1),
            }
            if is_inside_char_box_row(box):
                continue
            fields.append({
                "x": box["x"],
                "y": box["y"],
                "width": box["width"],
                "height": box["height"],
                "label": word,
                "type": "checkbox",
            })

    return fields


# ---------------------------------------------------------------------------
# Deduplication + char-box-aware underline filter
# ---------------------------------------------------------------------------

def filter_underlines_in_char_box_rows(underline_fields: list, char_box_fields: list) -> list:
    """
    Remove underline-derived text fields that fall inside a char-box row.
    The char-box row supersedes them.
    """
    if not char_box_fields:
        return underline_fields

    cb_boxes = []
    for cbf in char_box_fields:
        cb_boxes.append({
            "x0": cbf["x"] - 2,
            "x1": cbf["x"] + cbf["width"] + 2,
            "y0": cbf["y"] - 4,
            "y1": cbf["y"] + cbf["height"] + 8,  # generous below; underlines often sit below
        })

    result = []
    for f in underline_fields:
        fx_center = f["x"] + f["width"] / 2
        fy_center = f["y"] + f["height"] / 2
        inside = False
        for cb in cb_boxes:
            if cb["x0"] <= fx_center <= cb["x1"] and cb["y0"] <= fy_center <= cb["y1"]:
                inside = True
                break
        if not inside:
            result.append(f)
    return result


def deduplicate(fields: list, threshold: float = 6.0) -> list:
    result = []
    for field in fields:
        duplicate = False
        for existing in list(result):
            if existing.get("page") != field.get("page"):
                continue
            if abs(existing["x"] - field["x"]) < threshold and abs(existing["y"] - field["y"]) < threshold:
                # Prefer char-box rows over other text fields
                keep_new = (
                    field.get("_char_box_row")
                    or field.get("type") == "checkbox"
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
    """v2 pipeline: char-box detection added; checkbox detection respects char-box rows."""
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

                # 3. NEW IN V2: Detect char-box rows FIRST
                char_box_fields = detect_char_boxes(rects, curves, chars)

                # 4. Detect underlines, then filter ones inside char-box rows
                underline_fields = detect_underlines(h_lines_raw, v_lines, chars, page_height)
                underline_fields = filter_underlines_in_char_box_rows(underline_fields, char_box_fields)

                # 5. Detect checkboxes (skips those in char-box rows)
                checkbox_fields = detect_checkboxes(rects, curves, chars, char_box_fields)

                # 6. Combine all and tag page
                page_fields = char_box_fields + underline_fields + checkbox_fields
                for f in page_fields:
                    f["page"] = page_idx + 1
                all_fields.extend(page_fields)

    except Exception as e:
        sys.stderr.write(f"[heuristic_lab_v2] {pdf_path.name}: {type(e).__name__}: {e}\n")
        return []

    # 7. Deduplicate
    all_fields = deduplicate(all_fields)

    # 8. Output schema
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
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    if len(sys.argv) < 2:
        print("Usage: python heuristic_lab_v2.py <pdf_path>", file=sys.stderr)
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
