#!/usr/bin/env python3
"""
backend_registry.py

Single source of truth for all detection backends in the lab.

To add a new backend:
    1. Put backend module under scripts/backends/<name>.py
    2. Import its detect function in this file
    3. Add to BACKEND_METADATA
"""

from pathlib import Path
import sys

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))


def _backend_acroform_self(pdf_path: Path) -> list:
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


# Lab backends — imported optionally so registry doesn't fail if one breaks
try:
    from backends.heuristic_lab_v1 import detect as _backend_heuristic_lab_v1
    _v1_available = True
except ImportError:
    _backend_heuristic_lab_v1 = None
    _v1_available = False

try:
    from backends.heuristic_lab_v2 import detect as _backend_heuristic_lab_v2
    _v2_available = True
except ImportError:
    _backend_heuristic_lab_v2 = None
    _v2_available = False


BACKEND_METADATA: dict = {
    "acroform_self": {
        "fn": _backend_acroform_self,
        "lanes": ["A"],
        "description": "Re-extracts AcroForm widgets via pikepdf - sanity check",
        "schema_version": "1.0",
    },
}

if _v1_available:
    BACKEND_METADATA["heuristic_lab_v1"] = {
        "fn": _backend_heuristic_lab_v1,
        "lanes": ["A", "B"],
        "description": "Generic content-stream heuristic (v1 baseline)",
        "schema_version": "1.0",
    }
if _v2_available:
    BACKEND_METADATA["heuristic_lab_v2"] = {
        "fn": _backend_heuristic_lab_v2,
        "lanes": ["B"],
        "description": "v1 + char-box detection (flat-PDF candidate)",
        "schema_version": "1.0",
    }


BACKENDS: dict = {
    name: metadata["fn"]
    for name, metadata in BACKEND_METADATA.items()
}


def get_backend(name: str):
    if name not in BACKENDS:
        available = ", ".join(sorted(BACKENDS.keys()))
        raise KeyError(f"Unknown backend '{name}'. Available: {available}")
    return BACKENDS[name]


def list_backends() -> list[str]:
    return sorted(BACKENDS.keys())

def get_lanes_for_backend(name: str) -> list[str]:
    return BACKEND_METADATA[name]["lanes"]


def list_backends_for_lane(lane: str) -> list[str]:
    return sorted([
        name
        for name, metadata in BACKEND_METADATA.items()
        if lane in metadata["lanes"]
    ])


def get_backend_metadata(name: str) -> dict:
    return BACKEND_METADATA[name]
