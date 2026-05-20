#!/usr/bin/env python3
"""
render_ground_truth_overlays.py

Renders each AcroForm PDF in the corpus as PNG images with ground truth
bounding boxes overlaid. Color-coded by field type. Critical visual
verification step before benchmarking — proves that the extracted ground
truth bboxes actually land where the form fields visibly are.

Output structure:

    reports/overlays/ground_truth/<pdf_id>/
        page_001.png        Full page render with bbox overlays
        page_002.png
        ...
        summary.json        Per-PDF rendering summary

    reports/overlays/ground_truth/_index.html   Browseable index of all PDFs

Guardrails:
- READ-ONLY access to PDFs (pikepdf opens, pypdfium2 renders, never saves)
- READ-ONLY access to ground truth JSONs
- All writes confined to reports/overlays/ground_truth/
- assert_safe_output_path() refuses path traversal
- Idempotent: re-running overwrites cleanly without leaving stale files
- --dry-run mode reports what would be rendered without disk writes
- --pdf <id> mode renders one PDF only (useful for spot checks)
- Skips ground-truth files marked review_status="human_reviewed_failed"
  (placeholder for future workflow)

Field type colors:
    text       → blue       rgba(0, 122, 255, 0.35)
    checkbox   → green      rgba(52, 199, 89, 0.40)
    radio      → orange     rgba(255, 149, 0, 0.40)
    choice     → purple     rgba(175, 82, 222, 0.40)
    signature  → red        rgba(255, 59, 48, 0.45)
    pushbutton → gray       rgba(142, 142, 147, 0.30)

Usage:
    python scripts/render_ground_truth_overlays.py             # render all
    python scripts/render_ground_truth_overlays.py --dry-run   # report only
    python scripts/render_ground_truth_overlays.py --pdf irs_w9   # single PDF
    python scripts/render_ground_truth_overlays.py --dpi 100   # custom resolution
"""

import argparse
import io
import json
import sys
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:
    print("ERROR: pypdfium2 not installed. Run: pip install pypdfium2", file=sys.stderr)
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow not installed. Run: pip install pillow", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH_DIR = ROOT / "benchmarks" / "ground_truth"
ACROFORM_MANIFEST = ROOT / "samples" / "acroforms" / "manifest.json"
OVERLAY_DIR = ROOT / "reports" / "overlays" / "ground_truth"
INDEX_HTML = OVERLAY_DIR / "_index.html"


def assert_safe_output_path(path: Path) -> None:
    """Guardrail: refuse to write outside reports/overlays/ground_truth/."""
    resolved = path.resolve()
    expected = OVERLAY_DIR.resolve()
    try:
        resolved.relative_to(expected)
    except ValueError:
        raise RuntimeError(f"Refused to write outside {expected}: {resolved}")


# ---------------------------------------------------------------------------
# Type → color
# ---------------------------------------------------------------------------

TYPE_COLORS = {
    "text":       ((0, 122, 255), 90),       # blue,   ~35% alpha
    "checkbox":   ((52, 199, 89), 100),      # green,  ~40% alpha
    "radio":      ((255, 149, 0), 100),      # orange, ~40% alpha
    "choice":     ((175, 82, 222), 100),     # purple, ~40% alpha
    "signature":  ((255, 59, 48), 115),      # red,    ~45% alpha
    "pushbutton": ((142, 142, 147), 75),     # gray,   ~30% alpha
}

DEFAULT_COLOR = ((128, 128, 128), 100)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_font(size: int = 11):
    """Try a few common fonts; fall back to default if none found."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def find_pdf_path(pdf_id: str, manifest: list) -> Path | None:
    """Look up the source PDF path from the manifest."""
    for entry in manifest:
        if entry["id"] == pdf_id:
            return ROOT / entry["filename"]
    return None


def load_ground_truth(gt_path: Path) -> dict:
    """Load a ground truth JSON file."""
    return json.loads(gt_path.read_text())


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_page_with_overlays(pdf_doc, page_index: int, fields_for_page: list, dpi: int, font_small, font_label) -> Image.Image:
    """
    Render a single PDF page at the given DPI and overlay all field bboxes.

    Coordinate transform:
        Ground truth bbox is in PDF points, top-left origin.
        We render at `dpi` (default 150), so 1 PDF point = dpi/72 pixels.
        Both coordinate systems use top-left origin, so no flip needed for y.
    """
    scale = dpi / 72.0

    # Render page to PIL image
    page = pdf_doc[page_index]
    bitmap = page.render(scale=scale)
    img = bitmap.to_pil().convert("RGBA")
    page.close()

    # Overlay layer with transparency
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for f in fields_for_page:
        bbox = f["bbox"]  # [x, y, w, h] in PDF points, top-left origin
        x_px = bbox[0] * scale
        y_px = bbox[1] * scale
        w_px = bbox[2] * scale
        h_px = bbox[3] * scale

        color, alpha = TYPE_COLORS.get(f["type"], DEFAULT_COLOR)
        fill_color = color + (alpha,)
        outline_color = color + (220,)

        # Filled translucent rect
        draw.rectangle(
            [x_px, y_px, x_px + w_px, y_px + h_px],
            fill=fill_color,
            outline=outline_color,
            width=2,
        )

        # Field id label (small, top-left of bbox)
        try:
            label_text = f["id"]
            draw.rectangle(
                [x_px, y_px, x_px + len(label_text) * 7 + 4, y_px + 13],
                fill=color + (200,),
            )
            draw.text((x_px + 2, y_px + 1), label_text, fill=(255, 255, 255, 255), font=font_small)
        except Exception:
            pass

    # Composite overlay onto rendered page
    composed = Image.alpha_composite(img, overlay).convert("RGB")
    return composed


def render_pdf(pdf_path: Path, gt: dict, output_dir: Path, dpi: int, dry_run: bool) -> dict:
    """
    Render all pages of one PDF with overlays.
    Returns a summary dict.
    """
    summary = {
        "pdf_id": gt["pdf_id"],
        "pdf": gt["pdf"],
        "page_count": gt["page_count"],
        "field_count": len(gt["fields"]),
        "pages_rendered": 0,
        "output_dir": str(output_dir.relative_to(ROOT)) if not dry_run else "(dry-run)",
        "error": None,
    }

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Clean stale pages from previous runs
        for stale in output_dir.glob("page_*.png"):
            stale.unlink()

    # Group fields by page
    fields_by_page = {}
    for f in gt["fields"]:
        p = f["page"]
        fields_by_page.setdefault(p, []).append(f)

    font_small = get_font(10)
    font_label = get_font(12)

    try:
        pdf_doc = pdfium.PdfDocument(str(pdf_path))
        page_count = len(pdf_doc)

        for page_index in range(page_count):
            page_num = page_index + 1  # 1-indexed for ground truth match
            fields_for_page = fields_by_page.get(page_num, [])

            if dry_run:
                summary["pages_rendered"] += 1
                continue

            img = render_page_with_overlays(
                pdf_doc, page_index, fields_for_page, dpi, font_small, font_label
            )

            out_path = output_dir / f"page_{page_num:03d}.png"
            assert_safe_output_path(out_path)
            img.save(out_path, format="PNG", optimize=True)
            summary["pages_rendered"] += 1

        pdf_doc.close()

    except Exception as e:
        summary["error"] = f"{type(e).__name__}: {e}"

    # Per-PDF summary
    if not dry_run and summary["error"] is None:
        sum_path = output_dir / "summary.json"
        assert_safe_output_path(sum_path)
        sum_path.write_text(json.dumps(summary, indent=2))

    return summary


# ---------------------------------------------------------------------------
# HTML index
# ---------------------------------------------------------------------------

def write_index_html(summaries: list, dpi: int) -> None:
    """
    Generate a browseable HTML index that lists each PDF and links to its
    rendered overlays. Convenient for visual review.
    """
    lines = []
    lines.append("<!DOCTYPE html>")
    lines.append("<html><head><meta charset='utf-8'>")
    lines.append("<title>Ground Truth Overlay Index</title>")
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
    lines.append("  .swatch-text { background: rgba(0, 122, 255, 0.4); border: 1px solid rgba(0, 122, 255, 0.9); }")
    lines.append("  .swatch-checkbox { background: rgba(52, 199, 89, 0.4); border: 1px solid rgba(52, 199, 89, 0.9); }")
    lines.append("  .swatch-radio { background: rgba(255, 149, 0, 0.4); border: 1px solid rgba(255, 149, 0, 0.9); }")
    lines.append("  .swatch-choice { background: rgba(175, 82, 222, 0.4); border: 1px solid rgba(175, 82, 222, 0.9); }")
    lines.append("  .swatch-signature { background: rgba(255, 59, 48, 0.45); border: 1px solid rgba(255, 59, 48, 0.9); }")
    lines.append("  code { background: #f2f2f7; padding: 1px 6px; border-radius: 3px; font-size: 12px; }")
    lines.append("</style></head><body>")

    lines.append("<h1>Ground Truth Overlay Index</h1>")
    lines.append(f"<div class='meta'>Rendered at {dpi} DPI from <code>benchmarks/ground_truth/*.json</code></div>")

    lines.append("<div class='legend'>")
    lines.append("  <strong>Legend:</strong> &nbsp;")
    lines.append("  <span class='swatch swatch-text'></span> text &nbsp;")
    lines.append("  <span class='swatch swatch-checkbox'></span> checkbox &nbsp;")
    lines.append("  <span class='swatch swatch-radio'></span> radio &nbsp;")
    lines.append("  <span class='swatch swatch-choice'></span> choice &nbsp;")
    lines.append("  <span class='swatch swatch-signature'></span> signature")
    lines.append("</div>")

    lines.append("<br><table>")
    lines.append("<tr><th>PDF ID</th><th>Pages</th><th>Fields</th><th>Status</th><th>First page</th></tr>")

    for s in sorted(summaries, key=lambda x: x["pdf_id"]):
        if s["error"]:
            status = f"<span style='color: #ff3b30;'>ERROR: {s['error']}</span>"
            page_link = "—"
        else:
            status = f"{s['pages_rendered']}/{s['page_count']} rendered"
            page_link = f"<a href='{s['pdf_id']}/page_001.png'>page_001.png</a>"
        lines.append(
            f"<tr><td><code>{s['pdf_id']}</code></td>"
            f"<td>{s['page_count']}</td>"
            f"<td>{s['field_count']}</td>"
            f"<td>{status}</td>"
            f"<td>{page_link}</td></tr>"
        )

    lines.append("</table></body></html>")

    assert_safe_output_path(INDEX_HTML)
    INDEX_HTML.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be rendered without writing files")
    parser.add_argument("--pdf", type=str, default=None,
                        help="Render only the PDF with this pdf_id (e.g. irs_w9)")
    parser.add_argument("--dpi", type=int, default=150,
                        help="Rendering DPI (default 150, range 72-300)")
    args = parser.parse_args()

    if not (72 <= args.dpi <= 300):
        print(f"ERROR: --dpi must be 72-300, got {args.dpi}", file=sys.stderr)
        sys.exit(1)

    if not ACROFORM_MANIFEST.exists():
        print(f"ERROR: {ACROFORM_MANIFEST} not found", file=sys.stderr)
        sys.exit(1)
    if not GROUND_TRUTH_DIR.exists():
        print(f"ERROR: {GROUND_TRUTH_DIR} not found. Run extract_ground_truth.py first.", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(ACROFORM_MANIFEST.read_text())

    # Find all ground truth files (excluding the summary files)
    gt_files = sorted(p for p in GROUND_TRUTH_DIR.glob("*.json") if not p.name.startswith("_"))

    if args.pdf:
        gt_files = [p for p in gt_files if p.stem == args.pdf]
        if not gt_files:
            print(f"ERROR: no ground truth found for pdf_id '{args.pdf}'", file=sys.stderr)
            sys.exit(1)

    print(f"{'='*72}")
    print(f"render_ground_truth_overlays.py")
    if args.dry_run:
        print("MODE: DRY RUN -- no files will be written")
    print(f"Ground truth dir: {GROUND_TRUTH_DIR}")
    print(f"Output dir: {OVERLAY_DIR}")
    print(f"DPI: {args.dpi}")
    print(f"PDFs to render: {len(gt_files)}")
    print(f"{'='*72}")

    if not args.dry_run:
        OVERLAY_DIR.mkdir(parents=True, exist_ok=True)

    summaries = []
    total_pages = 0
    total_errors = 0

    for gt_path in gt_files:
        gt = load_ground_truth(gt_path)
        pdf_id = gt["pdf_id"]
        pdf_path = find_pdf_path(pdf_id, manifest)

        if pdf_path is None or not pdf_path.exists():
            print(f"SKIP {pdf_id}: source PDF not found")
            summaries.append({
                "pdf_id": pdf_id, "pdf": gt["pdf"], "page_count": gt["page_count"],
                "field_count": len(gt["fields"]), "pages_rendered": 0,
                "output_dir": "(skipped)", "error": "source PDF not found",
            })
            total_errors += 1
            continue

        output_dir = OVERLAY_DIR / pdf_id
        print(f"Rendering {pdf_id:30s} ({gt['page_count']} pages, {len(gt['fields'])} fields) ... ",
              end="", flush=True)

        summary = render_pdf(pdf_path, gt, output_dir, args.dpi, args.dry_run)
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
        write_index_html(summaries, args.dpi)
        print(f"\nWrote index: {INDEX_HTML.relative_to(ROOT)}")
        print(f"Output dir: {OVERLAY_DIR.relative_to(ROOT)}")
    else:
        print(f"\n(dry-run: no files written)")


if __name__ == "__main__":
    main()
