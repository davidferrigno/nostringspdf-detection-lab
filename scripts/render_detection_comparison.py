#!/usr/bin/env python3
"""
render_detection_comparison.py

Visual diff renderer that compares detection output against ground truth.
For each PDF page, produces a PNG showing:

  - TRUE POSITIVE (matched):       solid yellow overlay (GT + detection agree)
  - FALSE NEGATIVE (GT missed):    solid green outline (GT only)
  - FALSE POSITIVE (det wrong):    solid red outline (detection only)
  - TYPE MISMATCH (matched but type differs): yellow with orange border

Plus a header strip per page showing:
  - PDF id, page number
  - Per-page metrics: TP / FP / FN / Precision / Recall

Inputs:
  - A benchmark run directory (reports/benchmarks/<run_id>/) which contains
    per_pdf/<pdf_id>.json files with full match detail
  - Ground truth (benchmarks/ground_truth/<pdf_id>.json)
  - Source PDFs (samples/acroforms/raw/...)

Output:
  - reports/overlays/comparison/<run_id>/<pdf_id>/page_NNN.png
  - reports/overlays/comparison/<run_id>/_index.html

Guardrails:
- READ-ONLY access to PDFs, ground truth, and match details
- All writes confined to reports/overlays/comparison/
- assert_safe_output_path() refuses path traversal
- Idempotent: re-running cleans stale pages
- --dry-run mode reports without writing
- --pdf <id> mode renders a single PDF
- --run <run_id> selects which benchmark to compare (default: latest)

Usage:
    python scripts/render_detection_comparison.py                  # latest run, all PDFs
    python scripts/render_detection_comparison.py --dry-run        # report only
    python scripts/render_detection_comparison.py --pdf irs_w9     # single PDF
    python scripts/render_detection_comparison.py --run 2026-05-20_205642_acroform_self
    python scripts/render_detection_comparison.py --dpi 100
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:
    print("ERROR: pypdfium2 not installed.", file=sys.stderr)
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow not installed.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ACROFORM_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"
GROUND_TRUTH_DIR = ROOT / "benchmarks" / "ground_truth"
BENCHMARK_REPORTS_DIR = ROOT / "reports" / "benchmarks"
COMPARISON_DIR = ROOT / "reports" / "overlays" / "comparison"


def assert_safe_output_path(path: Path) -> None:
    """Guardrail: refuse to write outside reports/overlays/comparison/."""
    resolved = path.resolve()
    expected = COMPARISON_DIR.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError:
        raise RuntimeError(f"Refused to write outside {expected}: {resolved}")


# ---------------------------------------------------------------------------
# Visual style
# ---------------------------------------------------------------------------

# Status colors (RGB) + alpha
COLOR_TP_FILL        = (255, 204, 0, 90)     # yellow fill (GT + detection agree, types match)
COLOR_TP_OUTLINE     = (255, 204, 0, 230)    # yellow outline
COLOR_TP_TYPE_MISMATCH_OUTLINE = (255, 140, 0, 240)  # orange outline (geometry matches, type wrong)
COLOR_FN_OUTLINE     = (52, 199, 89, 240)    # green outline (GT missed by detection)
COLOR_FN_FILL        = (52, 199, 89, 50)     # green light fill
COLOR_FP_OUTLINE     = (255, 59, 48, 240)    # red outline (detection has no ground truth)
COLOR_FP_FILL        = (255, 59, 48, 50)     # red light fill

# Header colors
HEADER_BG     = (28, 28, 30, 230)
HEADER_TEXT   = (255, 255, 255, 255)
HEADER_SUB    = (174, 174, 178, 255)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_font(size: int = 11):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def find_latest_benchmark_run() -> Path | None:
    """Find the most recently-created benchmark run directory."""
    if not BENCHMARK_REPORTS_DIR.exists():
        return None
    runs = [p for p in BENCHMARK_REPORTS_DIR.iterdir() if p.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime)


def find_pdf_path(pdf_id: str, manifest: list) -> Path | None:
    for entry in manifest:
        if entry["id"] == pdf_id:
            return ROOT / entry["filename"]
    return None


# ---------------------------------------------------------------------------
# Match-data builder
# ---------------------------------------------------------------------------

def build_page_summary(detail: dict) -> dict:
    """
    From per_pdf/<pdf_id>.json match detail, build a per-page structure:
    {page_num: {tp: [(gt, det, type_match)], fp: [det], fn: [gt]}}
    Also accumulates per-page TP/FP/FN counts.
    """
    gt = detail.get("ground_truth", [])
    det = detail.get("detected", [])
    match = detail.get("match_detail", {})

    # We don't have ground_truth/detected arrays in the scorecard, only
    # the match indices. Re-derive these from the ground truth JSON + match.
    return match


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_page(
    pdf_doc, page_index: int, page_num: int,
    gt_for_page: list, det_for_page: list,
    tp_pairs: list, fp_indices: set, fn_indices: set,
    type_mismatches_keys: set,
    dpi: int, font_small, font_label, font_header, pdf_id: str,
    page_metrics: dict,
) -> Image.Image:
    """
    Render a single page with comparison overlays.

    tp_pairs:        list of (gt_idx_local, det_idx_local, type_match)
    fp_indices:      set of det_idx_local with no GT match
    fn_indices:      set of gt_idx_local with no det match
    type_mismatches_keys: set of (gt_idx_local, det_idx_local) for type mismatch TPs
    """
    scale = dpi / 72.0

    page = pdf_doc[page_index]
    bitmap = page.render(scale=scale)
    img = bitmap.to_pil().convert("RGBA")
    page.close()

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def bbox_to_px(bbox):
        return [
            bbox[0] * scale,
            bbox[1] * scale,
            (bbox[0] + bbox[2]) * scale,
            (bbox[1] + bbox[3]) * scale,
        ]

    # Draw FN first (GT only — beneath)
    for fn_idx in fn_indices:
        gt_field = gt_for_page[fn_idx]
        x1, y1, x2, y2 = bbox_to_px(gt_field["bbox"])
        draw.rectangle([x1, y1, x2, y2], fill=COLOR_FN_FILL, outline=COLOR_FN_OUTLINE, width=2)
        label = f"FN:{gt_field['id']}"
        draw.text((x1 + 2, y1 + 2), label, fill=(20, 90, 30, 255), font=font_small)

    # Draw FP (detection only)
    for fp_idx in fp_indices:
        det_field = det_for_page[fp_idx]
        x1, y1, x2, y2 = bbox_to_px(det_field["bbox"])
        draw.rectangle([x1, y1, x2, y2], fill=COLOR_FP_FILL, outline=COLOR_FP_OUTLINE, width=2)
        label = f"FP:{det_field.get('id','?')}"
        draw.text((x1 + 2, y1 + 2), label, fill=(140, 20, 20, 255), font=font_small)

    # Draw TP (matched) — yellow fill, outline depends on type match
    for gt_idx, det_idx, type_match in tp_pairs:
        gt_field = gt_for_page[gt_idx]
        x1, y1, x2, y2 = bbox_to_px(gt_field["bbox"])
        outline = COLOR_TP_OUTLINE if type_match else COLOR_TP_TYPE_MISMATCH_OUTLINE
        draw.rectangle([x1, y1, x2, y2], fill=COLOR_TP_FILL, outline=outline, width=2)
        if not type_match:
            label = f"TP*:{gt_field['id']}"  # asterisk = type mismatch
        else:
            label = f"TP:{gt_field['id']}"
        draw.text((x1 + 2, y1 + 2), label, fill=(120, 80, 0, 255), font=font_small)

    composed = Image.alpha_composite(img, overlay).convert("RGBA")

    # Header strip on top of page
    header_height = 56
    final = Image.new("RGBA",
                      (composed.width, composed.height + header_height),
                      (255, 255, 255, 255))
    final.paste(composed, (0, header_height), composed)

    header = Image.new("RGBA", (composed.width, header_height), HEADER_BG)
    hdraw = ImageDraw.Draw(header)
    hdraw.text((16, 8), f"{pdf_id}  ·  page {page_num}", fill=HEADER_TEXT, font=font_header)
    tp = page_metrics.get("tp", 0)
    fp = page_metrics.get("fp", 0)
    fn = page_metrics.get("fn", 0)
    tm = page_metrics.get("type_mismatches", 0)
    p = page_metrics.get("precision", 0.0)
    r = page_metrics.get("recall", 0.0)
    stat_line = f"TP {tp}  ·  FP {fp}  ·  FN {fn}  ·  type-mismatches {tm}  ·  P {p:.3f}  ·  R {r:.3f}"
    hdraw.text((16, 30), stat_line, fill=HEADER_SUB, font=font_label)

    # Legend on right side of header
    legend_x = composed.width - 360
    hdraw.rectangle([legend_x, 18, legend_x + 14, 32], fill=COLOR_TP_FILL[:3] + (255,))
    hdraw.text((legend_x + 18, 18), "TP", fill=HEADER_TEXT, font=font_small)
    hdraw.rectangle([legend_x + 50, 18, legend_x + 64, 32], fill=COLOR_FN_FILL[:3] + (255,))
    hdraw.text((legend_x + 68, 18), "FN", fill=HEADER_TEXT, font=font_small)
    hdraw.rectangle([legend_x + 100, 18, legend_x + 114, 32], fill=COLOR_FP_FILL[:3] + (255,))
    hdraw.text((legend_x + 118, 18), "FP", fill=HEADER_TEXT, font=font_small)
    hdraw.rectangle([legend_x + 150, 18, legend_x + 164, 32], fill=COLOR_TP_TYPE_MISMATCH_OUTLINE[:3] + (255,))
    hdraw.text((legend_x + 168, 18), "TP* (type mismatch)", fill=HEADER_TEXT, font=font_small)

    final.paste(header, (0, 0), header)
    return final.convert("RGB")


# ---------------------------------------------------------------------------
# Comparison data assembly
# ---------------------------------------------------------------------------

def assemble_comparison(per_pdf_detail: dict, gt: dict, backend_fn=None, source_pdf_path: Path = None) -> dict:
    """
    Resolve the per-PDF benchmark detail into the structure needed for
    rendering. We need the actual GT fields and detection fields, not just
    indices.

    Per-PDF detail JSON contains match_detail with indices into the
    original detected[] and ground_truth[] arrays. Ground truth fields
    come from the ground truth JSON. Detection fields must be regenerated
    by re-running the backend.

    Returns dict with:
        gt_fields:     list of ground truth fields
        det_fields:    list of detected fields (re-extracted)
        match_detail:  the original match detail
        ok:            bool, False if anything failed
        error:         str, only if ok=False
    """
    result = {"gt_fields": [], "det_fields": [], "match_detail": {}, "ok": False, "error": None}
    try:
        result["gt_fields"] = gt["fields"]
        result["match_detail"] = per_pdf_detail.get("match_detail", {})

        # Re-run the detection backend to get the same det_fields the
        # original benchmark produced. The per_pdf detail stores indices
        # against this list, so we MUST regenerate it deterministically.
        if backend_fn is not None and source_pdf_path is not None:
            result["det_fields"] = backend_fn(source_pdf_path)
        else:
            result["error"] = "no backend_fn provided for re-extraction"
            return result

        # Sanity: detection count must match what scorecard recorded
        recorded_det_count = per_pdf_detail.get("metrics", {}).get("detected_count")
        if recorded_det_count is not None and recorded_det_count != len(result["det_fields"]):
            result["error"] = (
                f"detected_count mismatch: re-extraction returned {len(result['det_fields'])}, "
                f"scorecard recorded {recorded_det_count}"
            )
            return result

        result["ok"] = True
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


# ---------------------------------------------------------------------------
# Backend re-extraction (acroform_self, ported from run_benchmark.py)
# ---------------------------------------------------------------------------

def backend_acroform_self(pdf_path: Path) -> list:
    """
    Same logic as run_benchmark.py's acroform_self backend.
    Re-extracts AcroForm widgets so we can recover the detection fields
    that the scorecard's indices reference.
    """
    import pikepdf
    fields = []
    field_counter = 0
    try:
        with pikepdf.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                try:
                    annots = page.get("/Annots", None)
                except Exception:
                    annots = None
                if annots is None:
                    continue
                try:
                    page_height = float(page.mediabox[3])
                except Exception:
                    continue
                seen = set()
                for annot in annots:
                    try:
                        subtype = annot.get("/Subtype", None)
                    except Exception:
                        continue
                    if subtype is None or str(subtype) != "/Widget":
                        continue
                    try:
                        key = annot.objgen
                        if key in seen:
                            continue
                        seen.add(key)
                    except Exception:
                        pass
                    try:
                        rect = annot.get("/Rect", None)
                        if rect is None:
                            continue
                        rect_vals = [float(v) for v in rect]
                    except (TypeError, ValueError, Exception):
                        continue
                    field_type = "unknown"
                    cursor = annot
                    safety = 20
                    while safety > 0 and field_type == "unknown":
                        try:
                            ft = cursor.get("/FT", None)
                        except Exception:
                            ft = None
                        if ft is not None:
                            ft_str = str(ft)
                            if ft_str == "/Tx":
                                field_type = "text"
                            elif ft_str == "/Btn":
                                try:
                                    ff = int(cursor.get("/Ff", 0))
                                except (TypeError, ValueError):
                                    ff = 0
                                if ff & 0x10000:
                                    field_type = "radio"
                                elif ff & 0x20000:
                                    field_type = "pushbutton"
                                else:
                                    field_type = "checkbox"
                            elif ft_str == "/Ch":
                                field_type = "choice"
                            elif ft_str == "/Sig":
                                field_type = "signature"
                        if field_type == "unknown":
                            try:
                                cursor = cursor.get("/Parent", None)
                            except Exception:
                                break
                            if cursor is None:
                                break
                        safety -= 1
                    if field_type == "unknown":
                        field_type = "text"
                    x_ll, y_ll, x_ur, y_ur = rect_vals
                    x = min(x_ll, x_ur)
                    width = abs(x_ur - x_ll)
                    height = abs(y_ur - y_ll)
                    y_bottom = min(y_ll, y_ur)
                    y_top = page_height - y_bottom - height
                    if width <= 0 or height <= 0:
                        continue
                    field_counter += 1
                    fields.append({
                        "id": f"d{field_counter}",
                        "page": page_idx + 1,
                        "type": field_type,
                        "bbox": [round(x, 2), round(y_top, 2), round(width, 2), round(height, 2)],
                    })
    except Exception:
        pass
    return fields


BACKEND_BY_NAME = {
    "acroform_self": backend_acroform_self,
}


# ---------------------------------------------------------------------------
# Per-PDF render
# ---------------------------------------------------------------------------

def render_comparison_for_pdf(pdf_path: Path, gt: dict, per_pdf_detail: dict,
                              backend_fn, output_dir: Path,
                              dpi: int, dry_run: bool) -> dict:
    summary = {
        "pdf_id": gt["pdf_id"],
        "pdf": gt["pdf"],
        "page_count": gt["page_count"],
        "pages_rendered": 0,
        "error": None,
    }

    assembled = assemble_comparison(per_pdf_detail, gt, backend_fn, pdf_path)
    if not assembled["ok"]:
        summary["error"] = assembled["error"]
        return summary

    gt_fields = assembled["gt_fields"]
    det_fields = assembled["det_fields"]
    match = assembled["match_detail"]

    # Build index lookups
    tp_pairs_global = match.get("tp", [])
    fp_global = set(match.get("fp", []))
    fn_global = set(match.get("fn", []))
    type_mismatch_keys = {(t["gt_idx"], t["det_idx"]) for t in match.get("type_mismatches", [])}

    # Group GT and detection by page (with local indices per page)
    gt_by_page = {}
    gt_local_index = {}  # global_idx -> (page, local_idx)
    for global_idx, f in enumerate(gt_fields):
        p = f["page"]
        local_list = gt_by_page.setdefault(p, [])
        gt_local_index[global_idx] = (p, len(local_list))
        local_list.append(f)

    det_by_page = {}
    det_local_index = {}
    for global_idx, f in enumerate(det_fields):
        p = f["page"]
        local_list = det_by_page.setdefault(p, [])
        det_local_index[global_idx] = (p, len(local_list))
        local_list.append(f)

    # Convert global TP/FP/FN to per-page local
    tp_by_page = {}
    fp_by_page = {}
    fn_by_page = {}
    type_mismatch_by_page = {}

    for tp_entry in tp_pairs_global:
        gt_global = tp_entry["gt_idx"]
        det_global = tp_entry["det_idx"]
        type_match = tp_entry["type_match"]
        p, gt_local = gt_local_index.get(gt_global, (None, None))
        _, det_local = det_local_index.get(det_global, (None, None))
        if p is None or gt_local is None or det_local is None:
            continue
        tp_by_page.setdefault(p, []).append((gt_local, det_local, type_match))
        if (gt_global, det_global) in type_mismatch_keys:
            type_mismatch_by_page.setdefault(p, set()).add((gt_local, det_local))

    for fp_global_idx in fp_global:
        p, det_local = det_local_index.get(fp_global_idx, (None, None))
        if p is None or det_local is None:
            continue
        fp_by_page.setdefault(p, set()).add(det_local)

    for fn_global_idx in fn_global:
        p, gt_local = gt_local_index.get(fn_global_idx, (None, None))
        if p is None or gt_local is None:
            continue
        fn_by_page.setdefault(p, set()).add(gt_local)

    # Per-page metrics
    def page_metrics(p):
        tp = len(tp_by_page.get(p, []))
        fp = len(fp_by_page.get(p, set()))
        fn = len(fn_by_page.get(p, set()))
        tm = len(type_mismatch_by_page.get(p, set()))
        det_count = tp + fp
        gt_count = tp + fn
        precision = tp / det_count if det_count > 0 else 0.0
        recall = tp / gt_count if gt_count > 0 else 0.0
        return {"tp": tp, "fp": fp, "fn": fn, "type_mismatches": tm,
                "precision": precision, "recall": recall}

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        for stale in output_dir.glob("page_*.png"):
            stale.unlink()

    font_small = get_font(10)
    font_label = get_font(12)
    font_header = get_font(15)

    try:
        pdf_doc = pdfium.PdfDocument(str(pdf_path))
        for page_index in range(len(pdf_doc)):
            page_num = page_index + 1
            gt_for_page = gt_by_page.get(page_num, [])
            det_for_page = det_by_page.get(page_num, [])
            tp_pairs = tp_by_page.get(page_num, [])
            fp_indices = fp_by_page.get(page_num, set())
            fn_indices = fn_by_page.get(page_num, set())
            type_keys = type_mismatch_by_page.get(page_num, set())

            metrics = page_metrics(page_num)

            if dry_run:
                summary["pages_rendered"] += 1
                continue

            img = render_page(
                pdf_doc, page_index, page_num,
                gt_for_page, det_for_page,
                tp_pairs, fp_indices, fn_indices, type_keys,
                dpi, font_small, font_label, font_header,
                gt["pdf_id"], metrics,
            )
            out_path = output_dir / f"page_{page_num:03d}.png"
            assert_safe_output_path(out_path)
            img.save(out_path, format="PNG", optimize=True)
            summary["pages_rendered"] += 1

        pdf_doc.close()
    except Exception as e:
        summary["error"] = f"{type(e).__name__}: {e}"

    if not dry_run and summary["error"] is None:
        # Per-PDF summary
        sum_path = output_dir / "summary.json"
        assert_safe_output_path(sum_path)
        sum_path.write_text(json.dumps({
            "pdf_id": gt["pdf_id"],
            "pages_rendered": summary["pages_rendered"],
            "overall_metrics": per_pdf_detail.get("metrics", {}),
            "per_page_metrics": {str(p): page_metrics(p) for p in range(1, gt["page_count"] + 1)},
        }, indent=2))

    return summary


# ---------------------------------------------------------------------------
# HTML index
# ---------------------------------------------------------------------------

def write_index_html(summaries: list, run_id: str, backend: str, dpi: int, output_root: Path) -> None:
    lines = []
    lines.append("<!DOCTYPE html>")
    lines.append("<html><head><meta charset='utf-8'>")
    lines.append(f"<title>Detection Comparison · {run_id}</title>")
    lines.append("<style>")
    lines.append("  body { font-family: -apple-system, system-ui, sans-serif; margin: 24px; color: #1c1c1e; }")
    lines.append("  h1 { font-weight: 600; margin-bottom: 8px; }")
    lines.append("  .meta { color: #6e6e73; font-size: 13px; margin-bottom: 24px; }")
    lines.append("  table { border-collapse: collapse; width: 100%; }")
    lines.append("  th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #e5e5ea; }")
    lines.append("  th { background: #f2f2f7; font-weight: 600; }")
    lines.append("  tr:hover { background: #f9f9fb; }")
    lines.append("  .legend { margin-top: 16px; padding: 12px; background: #f2f2f7; border-radius: 8px; font-size: 13px; }")
    lines.append("  .swatch { display: inline-block; width: 14px; height: 14px; border-radius: 2px; vertical-align: middle; margin-right: 4px; }")
    lines.append("  .swatch-tp { background: rgba(255, 204, 0, 0.6); border: 1px solid rgba(255, 204, 0, 1); }")
    lines.append("  .swatch-fn { background: rgba(52, 199, 89, 0.5); border: 1px solid rgba(52, 199, 89, 1); }")
    lines.append("  .swatch-fp { background: rgba(255, 59, 48, 0.5); border: 1px solid rgba(255, 59, 48, 1); }")
    lines.append("  .swatch-tm { background: rgba(255, 204, 0, 0.4); border: 2px solid rgba(255, 140, 0, 1); }")
    lines.append("  .perfect { color: #34c759; font-weight: 600; }")
    lines.append("  .bad { color: #ff3b30; font-weight: 600; }")
    lines.append("  code { background: #f2f2f7; padding: 1px 6px; border-radius: 3px; font-size: 12px; }")
    lines.append("</style></head><body>")

    lines.append(f"<h1>Detection Comparison · {run_id}</h1>")
    lines.append(f"<div class='meta'>Backend: <code>{backend}</code> · DPI: {dpi}</div>")

    lines.append("<div class='legend'>")
    lines.append("  <strong>Legend:</strong> &nbsp;")
    lines.append("  <span class='swatch swatch-tp'></span> TP (matched) &nbsp;")
    lines.append("  <span class='swatch swatch-fn'></span> FN (ground truth missed) &nbsp;")
    lines.append("  <span class='swatch swatch-fp'></span> FP (detection wrong) &nbsp;")
    lines.append("  <span class='swatch swatch-tm'></span> TP* (geometry matched, type mismatch)")
    lines.append("</div><br>")

    lines.append("<table>")
    lines.append("<tr><th>PDF ID</th><th>Pages</th><th>P</th><th>R</th><th>F1</th><th>FP</th><th>FN</th><th>First page</th></tr>")
    for s in sorted(summaries, key=lambda x: x["pdf_id"]):
        if s.get("error"):
            lines.append(
                f"<tr><td><code>{s['pdf_id']}</code></td>"
                f"<td>{s['page_count']}</td>"
                f"<td colspan='5'><span class='bad'>ERROR: {s['error']}</span></td>"
                f"<td>—</td></tr>"
            )
            continue
        metrics = s.get("overall_metrics", {})
        p = metrics.get("precision", 0)
        r = metrics.get("recall", 0)
        f1 = metrics.get("f1", 0)
        fp_count = metrics.get("fp", 0)
        fn_count = metrics.get("fn", 0)
        cls = "perfect" if (p == 1.0 and r == 1.0) else ""
        link = f"<a href='{s['pdf_id']}/page_001.png'>page_001.png</a>" if s["pages_rendered"] > 0 else "—"
        lines.append(
            f"<tr><td><code>{s['pdf_id']}</code></td>"
            f"<td>{s['page_count']}</td>"
            f"<td class='{cls}'>{p}</td>"
            f"<td class='{cls}'>{r}</td>"
            f"<td class='{cls}'>{f1}</td>"
            f"<td>{fp_count}</td>"
            f"<td>{fn_count}</td>"
            f"<td>{link}</td></tr>"
        )
    lines.append("</table></body></html>")

    index_path = output_root / "_index.html"
    assert_safe_output_path(index_path)
    index_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=None,
                        help="Benchmark run directory name (default: latest)")
    parser.add_argument("--pdf", default=None,
                        help="Render only the PDF with this pdf_id")
    parser.add_argument("--dpi", type=int, default=150,
                        help="Rendering DPI (default 150, range 72-300)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be rendered without writes")
    args = parser.parse_args()

    if not (72 <= args.dpi <= 300):
        print(f"ERROR: --dpi must be 72-300, got {args.dpi}", file=sys.stderr)
        sys.exit(1)

    if not ACROFORM_MANIFEST.exists():
        print(f"ERROR: {ACROFORM_MANIFEST} not found", file=sys.stderr)
        sys.exit(1)

    # Resolve benchmark run dir
    if args.run:
        run_dir = BENCHMARK_REPORTS_DIR / args.run
        if not run_dir.exists():
            print(f"ERROR: benchmark run '{args.run}' not found at {run_dir}", file=sys.stderr)
            sys.exit(1)
    else:
        run_dir = find_latest_benchmark_run()
        if run_dir is None:
            print(f"ERROR: no benchmark runs found in {BENCHMARK_REPORTS_DIR}", file=sys.stderr)
            print("Run scripts/run_benchmark.py first.", file=sys.stderr)
            sys.exit(1)

    scorecard_path = run_dir / "scorecard.json"
    per_pdf_dir = run_dir / "per_pdf"
    if not scorecard_path.exists() or not per_pdf_dir.exists():
        print(f"ERROR: incomplete benchmark run at {run_dir} (missing scorecard.json or per_pdf/)", file=sys.stderr)
        sys.exit(1)

    scorecard = json.loads(scorecard_path.read_text())
    backend = scorecard.get("aggregate", {}).get("backend", "unknown")
    backend_fn = BACKEND_BY_NAME.get(backend)
    if backend_fn is None:
        print(f"ERROR: unknown backend '{backend}'. Add it to BACKEND_BY_NAME.", file=sys.stderr)
        sys.exit(1)

    # Output directory
    run_id = run_dir.name
    output_root = COMPARISON_DIR / run_id

    manifest = json.loads(ACROFORM_MANIFEST.read_text())

    # Find PDFs to render
    per_pdf_files = sorted(per_pdf_dir.glob("*.json"))
    if args.pdf:
        per_pdf_files = [p for p in per_pdf_files if p.stem == args.pdf]
        if not per_pdf_files:
            print(f"ERROR: no per_pdf entry for pdf_id '{args.pdf}' in run {run_id}", file=sys.stderr)
            sys.exit(1)

    print(f"{'='*72}")
    print(f"render_detection_comparison.py")
    if args.dry_run:
        print("MODE: DRY RUN -- no files will be written")
    print(f"Benchmark run: {run_id}")
    print(f"Backend: {backend}")
    print(f"Output dir: {output_root}")
    print(f"DPI: {args.dpi}")
    print(f"PDFs to render: {len(per_pdf_files)}")
    print(f"{'='*72}")

    if not args.dry_run:
        output_root.mkdir(parents=True, exist_ok=True)

    summaries = []
    total_pages = 0
    total_errors = 0

    for pp_file in per_pdf_files:
        pdf_id = pp_file.stem
        per_pdf_detail = json.loads(pp_file.read_text())

        # Get ground truth + source PDF
        gt_path = GROUND_TRUTH_DIR / f"{pdf_id}.json"
        if not gt_path.exists():
            print(f"SKIP {pdf_id}: ground truth not found")
            summaries.append({
                "pdf_id": pdf_id, "pdf": per_pdf_detail.get("pdf", "?"),
                "page_count": 0, "pages_rendered": 0,
                "error": "ground truth not found",
                "overall_metrics": per_pdf_detail.get("metrics", {}),
            })
            total_errors += 1
            continue
        gt = json.loads(gt_path.read_text())

        pdf_path = find_pdf_path(pdf_id, manifest)
        if pdf_path is None or not pdf_path.exists():
            print(f"SKIP {pdf_id}: source PDF not found")
            summaries.append({
                "pdf_id": pdf_id, "pdf": per_pdf_detail.get("pdf", "?"),
                "page_count": gt["page_count"], "pages_rendered": 0,
                "error": "source PDF not found",
                "overall_metrics": per_pdf_detail.get("metrics", {}),
            })
            total_errors += 1
            continue

        out_dir = output_root / pdf_id
        m = per_pdf_detail.get("metrics", {})
        print(f"Comparing {pdf_id:30s} P={m.get('precision', 0):.3f} R={m.get('recall', 0):.3f} ... ",
              end="", flush=True)

        summary = render_comparison_for_pdf(
            pdf_path, gt, per_pdf_detail, backend_fn, out_dir, args.dpi, args.dry_run
        )
        summary["overall_metrics"] = m
        summaries.append(summary)

        if summary["error"]:
            print(f"ERROR: {summary['error']}")
            total_errors += 1
        else:
            print(f"OK ({summary['pages_rendered']} pages)")
            total_pages += summary["pages_rendered"]

    print(f"{'='*72}")
    print(f"PDFs processed: {len(summaries)}")
    print(f"Pages rendered: {total_pages}")
    print(f"Errors: {total_errors}")

    if not args.dry_run:
        write_index_html(summaries, run_id, backend, args.dpi, output_root)
        print(f"\nIndex: {(output_root / '_index.html').relative_to(ROOT)}")
        print(f"Output: {output_root.relative_to(ROOT)}")
    else:
        print(f"\n(dry-run: no files written)")


if __name__ == "__main__":
    main()
