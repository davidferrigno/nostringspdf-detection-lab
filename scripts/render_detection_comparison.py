#!/usr/bin/env python3
"""
render_detection_comparison.py v1.1

Visual diff renderer. Compares detection output against ground truth and
produces per-page PNG overlays showing TP/FN/FP/type-mismatch regions.

Backends imported from scripts/backend_registry.py.

For each PDF page:
  - TRUE POSITIVE (matched):       yellow fill + yellow outline
  - TYPE MISMATCH (geometry only): yellow + orange outline
  - FALSE NEGATIVE (GT missed):    light green outline
  - FALSE POSITIVE (det wrong):    light red outline

Plus a header strip per page showing TP/FP/FN counts and P/R metrics.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend_registry import get_backend


ROOT = Path(__file__).resolve().parent.parent
ACROFORM_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"
GROUND_TRUTH_DIR = ROOT / "benchmarks" / "ground_truth"
BENCHMARK_REPORTS_DIR = ROOT / "reports" / "benchmarks"
COMPARISON_DIR = ROOT / "reports" / "overlays" / "comparison"


def assert_safe_output_path(path: Path) -> None:
    resolved = path.resolve()
    expected = COMPARISON_DIR.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError:
        raise RuntimeError(f"Refused to write outside {expected}: {resolved}")


COLOR_TP_FILL = (255, 204, 0, 90)
COLOR_TP_OUTLINE = (255, 204, 0, 230)
COLOR_TP_TYPE_MISMATCH_OUTLINE = (255, 140, 0, 240)
COLOR_FN_OUTLINE = (52, 199, 89, 240)
COLOR_FN_FILL = (52, 199, 89, 50)
COLOR_FP_OUTLINE = (255, 59, 48, 240)
COLOR_FP_FILL = (255, 59, 48, 50)
HEADER_BG = (28, 28, 30, 230)
HEADER_TEXT = (255, 255, 255, 255)
HEADER_SUB = (174, 174, 178, 255)


def get_font(size: int = 11):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def find_latest_benchmark_run() -> Path | None:
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


def assemble_comparison(per_pdf_detail, gt, backend_fn, source_pdf_path):
    result = {"gt_fields": [], "det_fields": [], "match_detail": {}, "ok": False, "error": None}
    try:
        result["gt_fields"] = gt["fields"]
        result["match_detail"] = per_pdf_detail.get("match_detail", {})
        if backend_fn is None or source_pdf_path is None:
            result["error"] = "no backend_fn provided"
            return result
        result["det_fields"] = backend_fn(source_pdf_path)
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


def render_page(pdf_doc, page_index, page_num, gt_for_page, det_for_page,
                tp_pairs, fp_indices, fn_indices, type_mismatches_keys,
                dpi, font_small, font_label, font_header, pdf_id, page_metrics):
    scale = dpi / 72.0
    page = pdf_doc[page_index]
    bitmap = page.render(scale=scale)
    img = bitmap.to_pil().convert("RGBA")
    page.close()

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def bbox_to_px(bbox):
        return [bbox[0] * scale, bbox[1] * scale,
                (bbox[0] + bbox[2]) * scale, (bbox[1] + bbox[3]) * scale]

    for fn_idx in fn_indices:
        gt_field = gt_for_page[fn_idx]
        x1, y1, x2, y2 = bbox_to_px(gt_field["bbox"])
        draw.rectangle([x1, y1, x2, y2], fill=COLOR_FN_FILL, outline=COLOR_FN_OUTLINE, width=2)
        draw.text((x1 + 2, y1 + 2), f"FN:{gt_field['id']}", fill=(20, 90, 30, 255), font=font_small)

    for fp_idx in fp_indices:
        det_field = det_for_page[fp_idx]
        x1, y1, x2, y2 = bbox_to_px(det_field["bbox"])
        draw.rectangle([x1, y1, x2, y2], fill=COLOR_FP_FILL, outline=COLOR_FP_OUTLINE, width=2)
        draw.text((x1 + 2, y1 + 2), f"FP:{det_field.get('id','?')}",
                  fill=(140, 20, 20, 255), font=font_small)

    for gt_idx, det_idx, type_match in tp_pairs:
        gt_field = gt_for_page[gt_idx]
        x1, y1, x2, y2 = bbox_to_px(gt_field["bbox"])
        outline = COLOR_TP_OUTLINE if type_match else COLOR_TP_TYPE_MISMATCH_OUTLINE
        draw.rectangle([x1, y1, x2, y2], fill=COLOR_TP_FILL, outline=outline, width=2)
        label = f"TP*:{gt_field['id']}" if not type_match else f"TP:{gt_field['id']}"
        draw.text((x1 + 2, y1 + 2), label, fill=(120, 80, 0, 255), font=font_small)

    composed = Image.alpha_composite(img, overlay).convert("RGBA")

    header_height = 56
    final = Image.new("RGBA", (composed.width, composed.height + header_height), (255, 255, 255, 255))
    final.paste(composed, (0, header_height), composed)

    header = Image.new("RGBA", (composed.width, header_height), HEADER_BG)
    hdraw = ImageDraw.Draw(header)
    hdraw.text((16, 8), f"{pdf_id}  ·  page {page_num}", fill=HEADER_TEXT, font=font_header)
    tp, fp, fn, tm = (page_metrics.get(k, 0) for k in ["tp", "fp", "fn", "type_mismatches"])
    p, r = page_metrics.get("precision", 0.0), page_metrics.get("recall", 0.0)
    hdraw.text((16, 30),
               f"TP {tp}  ·  FP {fp}  ·  FN {fn}  ·  type-mismatches {tm}  ·  P {p:.3f}  ·  R {r:.3f}",
               fill=HEADER_SUB, font=font_label)

    legend_x = composed.width - 360
    for offset, color, label in [
        (0, COLOR_TP_FILL[:3] + (255,), "TP"),
        (50, COLOR_FN_FILL[:3] + (255,), "FN"),
        (100, COLOR_FP_FILL[:3] + (255,), "FP"),
        (150, COLOR_TP_TYPE_MISMATCH_OUTLINE[:3] + (255,), "TP* (type mismatch)"),
    ]:
        hdraw.rectangle([legend_x + offset, 18, legend_x + offset + 14, 32], fill=color)
        hdraw.text((legend_x + offset + 18, 18), label, fill=HEADER_TEXT, font=font_small)

    final.paste(header, (0, 0), header)
    return final.convert("RGB")


def render_comparison_for_pdf(pdf_path, gt, per_pdf_detail, backend_fn, output_dir, dpi, dry_run):
    summary = {"pdf_id": gt["pdf_id"], "pdf": gt["pdf"], "page_count": gt["page_count"],
               "pages_rendered": 0, "error": None}

    assembled = assemble_comparison(per_pdf_detail, gt, backend_fn, pdf_path)
    if not assembled["ok"]:
        summary["error"] = assembled["error"]
        return summary

    gt_fields = assembled["gt_fields"]
    det_fields = assembled["det_fields"]
    match = assembled["match_detail"]

    tp_pairs_global = match.get("tp", [])
    fp_global = set(match.get("fp", []))
    fn_global = set(match.get("fn", []))
    type_mismatch_keys = {(t["gt_idx"], t["det_idx"]) for t in match.get("type_mismatches", [])}

    gt_by_page, gt_local_index = {}, {}
    for global_idx, f in enumerate(gt_fields):
        p = f["page"]
        local = gt_by_page.setdefault(p, [])
        gt_local_index[global_idx] = (p, len(local))
        local.append(f)

    det_by_page, det_local_index = {}, {}
    for global_idx, f in enumerate(det_fields):
        p = f["page"]
        local = det_by_page.setdefault(p, [])
        det_local_index[global_idx] = (p, len(local))
        local.append(f)

    tp_by_page, fp_by_page, fn_by_page, type_mismatch_by_page = {}, {}, {}, {}
    for tp_entry in tp_pairs_global:
        p, gt_local = gt_local_index.get(tp_entry["gt_idx"], (None, None))
        _, det_local = det_local_index.get(tp_entry["det_idx"], (None, None))
        if p is None or gt_local is None or det_local is None:
            continue
        tp_by_page.setdefault(p, []).append((gt_local, det_local, tp_entry["type_match"]))
        if (tp_entry["gt_idx"], tp_entry["det_idx"]) in type_mismatch_keys:
            type_mismatch_by_page.setdefault(p, set()).add((gt_local, det_local))

    for fp_idx in fp_global:
        p, det_local = det_local_index.get(fp_idx, (None, None))
        if p is None or det_local is None:
            continue
        fp_by_page.setdefault(p, set()).add(det_local)

    for fn_idx in fn_global:
        p, gt_local = gt_local_index.get(fn_idx, (None, None))
        if p is None or gt_local is None:
            continue
        fn_by_page.setdefault(p, set()).add(gt_local)

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
        sum_path = output_dir / "summary.json"
        assert_safe_output_path(sum_path)
        sum_path.write_text(json.dumps({
            "pdf_id": gt["pdf_id"],
            "pages_rendered": summary["pages_rendered"],
            "overall_metrics": per_pdf_detail.get("metrics", {}),
            "per_page_metrics": {str(p): page_metrics(p) for p in range(1, gt["page_count"] + 1)},
        }, indent=2))

    return summary


def write_index_html(summaries, run_id, backend, dpi, output_root):
    lines = ["<!DOCTYPE html>",
             "<html><head><meta charset='utf-8'>",
             f"<title>Detection Comparison · {run_id}</title>",
             "<style>",
             "  body { font-family: -apple-system, system-ui, sans-serif; margin: 24px; color: #1c1c1e; }",
             "  h1 { font-weight: 600; margin-bottom: 8px; }",
             "  .meta { color: #6e6e73; font-size: 13px; margin-bottom: 24px; }",
             "  table { border-collapse: collapse; width: 100%; }",
             "  th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #e5e5ea; }",
             "  th { background: #f2f2f7; font-weight: 600; }",
             "  tr:hover { background: #f9f9fb; }",
             "  .legend { margin-top: 16px; padding: 12px; background: #f2f2f7; border-radius: 8px; font-size: 13px; }",
             "  .swatch { display: inline-block; width: 14px; height: 14px; border-radius: 2px; vertical-align: middle; margin-right: 4px; }",
             "  .swatch-tp { background: rgba(255, 204, 0, 0.6); border: 1px solid rgba(255, 204, 0, 1); }",
             "  .swatch-fn { background: rgba(52, 199, 89, 0.5); border: 1px solid rgba(52, 199, 89, 1); }",
             "  .swatch-fp { background: rgba(255, 59, 48, 0.5); border: 1px solid rgba(255, 59, 48, 1); }",
             "  .swatch-tm { background: rgba(255, 204, 0, 0.4); border: 2px solid rgba(255, 140, 0, 1); }",
             "  .perfect { color: #34c759; font-weight: 600; }",
             "  .bad { color: #ff3b30; font-weight: 600; }",
             "  code { background: #f2f2f7; padding: 1px 6px; border-radius: 3px; font-size: 12px; }",
             "</style></head><body>",
             f"<h1>Detection Comparison · {run_id}</h1>",
             f"<div class='meta'>Backend: <code>{backend}</code> · DPI: {dpi}</div>",
             "<div class='legend'>",
             "  <strong>Legend:</strong> &nbsp;",
             "  <span class='swatch swatch-tp'></span> TP (matched) &nbsp;",
             "  <span class='swatch swatch-fn'></span> FN (ground truth missed) &nbsp;",
             "  <span class='swatch swatch-fp'></span> FP (detection wrong) &nbsp;",
             "  <span class='swatch swatch-tm'></span> TP* (geometry matched, type mismatch)",
             "</div><br>",
             "<table>",
             "<tr><th>PDF ID</th><th>Pages</th><th>P</th><th>R</th><th>F1</th><th>FP</th><th>FN</th><th>First page</th></tr>"]

    for s in sorted(summaries, key=lambda x: x["pdf_id"]):
        if s.get("error"):
            lines.append(f"<tr><td><code>{s['pdf_id']}</code></td>"
                         f"<td>{s['page_count']}</td>"
                         f"<td colspan='5'><span class='bad'>ERROR: {s['error']}</span></td>"
                         f"<td>—</td></tr>")
            continue
        m = s.get("overall_metrics", {})
        p, r, f1 = m.get("precision", 0), m.get("recall", 0), m.get("f1", 0)
        fp_count, fn_count = m.get("fp", 0), m.get("fn", 0)
        cls = "perfect" if (p == 1.0 and r == 1.0) else ("bad" if (p < 0.5 or r < 0.5) else "")
        link = f"<a href='{s['pdf_id']}/page_001.png'>page_001.png</a>" if s["pages_rendered"] > 0 else "—"
        lines.append(f"<tr><td><code>{s['pdf_id']}</code></td>"
                     f"<td>{s['page_count']}</td>"
                     f"<td class='{cls}'>{p}</td>"
                     f"<td class='{cls}'>{r}</td>"
                     f"<td class='{cls}'>{f1}</td>"
                     f"<td>{fp_count}</td>"
                     f"<td>{fn_count}</td>"
                     f"<td>{link}</td></tr>")
    lines.append("</table></body></html>")

    index_path = output_root / "_index.html"
    assert_safe_output_path(index_path)
    index_path.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=None, help="Benchmark run dir name (default: latest)")
    parser.add_argument("--pdf", default=None, help="Render only this pdf_id")
    parser.add_argument("--dpi", type=int, default=150, help="Rendering DPI (72-300)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (72 <= args.dpi <= 300):
        print(f"ERROR: --dpi must be 72-300, got {args.dpi}", file=sys.stderr)
        sys.exit(1)
    if not ACROFORM_MANIFEST.exists():
        print(f"ERROR: {ACROFORM_MANIFEST} not found", file=sys.stderr)
        sys.exit(1)

    if args.run:
        run_dir = BENCHMARK_REPORTS_DIR / args.run
        if not run_dir.exists():
            print(f"ERROR: benchmark run '{args.run}' not found", file=sys.stderr)
            sys.exit(1)
    else:
        run_dir = find_latest_benchmark_run()
        if run_dir is None:
            print(f"ERROR: no benchmark runs found", file=sys.stderr)
            sys.exit(1)

    scorecard_path = run_dir / "scorecard.json"
    per_pdf_dir = run_dir / "per_pdf"
    if not scorecard_path.exists() or not per_pdf_dir.exists():
        print(f"ERROR: incomplete benchmark run at {run_dir}", file=sys.stderr)
        sys.exit(1)

    scorecard = json.loads(scorecard_path.read_text())
    backend_name = scorecard.get("aggregate", {}).get("backend", "unknown")
    try:
        backend_fn = get_backend(backend_name)
    except KeyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    run_id = run_dir.name
    output_root = COMPARISON_DIR / run_id
    manifest = json.loads(ACROFORM_MANIFEST.read_text())

    per_pdf_files = sorted(per_pdf_dir.glob("*.json"))
    if args.pdf:
        per_pdf_files = [p for p in per_pdf_files if p.stem == args.pdf]
        if not per_pdf_files:
            print(f"ERROR: no per_pdf entry for '{args.pdf}'", file=sys.stderr)
            sys.exit(1)

    print(f"{'='*72}")
    print(f"render_detection_comparison.py v1.1")
    if args.dry_run:
        print("MODE: DRY RUN")
    print(f"Run: {run_id}")
    print(f"Backend: {backend_name}")
    print(f"Output: {output_root}")
    print(f"PDFs: {len(per_pdf_files)}")
    print(f"{'='*72}")

    if not args.dry_run:
        output_root.mkdir(parents=True, exist_ok=True)

    summaries = []
    total_pages = 0
    total_errors = 0

    for pp_file in per_pdf_files:
        pdf_id = pp_file.stem
        per_pdf_detail = json.loads(pp_file.read_text())

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
        write_index_html(summaries, run_id, backend_name, args.dpi, output_root)
        print(f"\nIndex: {(output_root / '_index.html').relative_to(ROOT)}")
        print(f"Output: {output_root.relative_to(ROOT)}")
    else:
        print(f"\n(dry-run: no files written)")


if __name__ == "__main__":
    main()
