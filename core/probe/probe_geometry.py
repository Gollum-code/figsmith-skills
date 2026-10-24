#!/usr/bin/env python3
"""core/probe/probe_geometry.py - measure a reference figure's geometry so a replica
can be built from evidence instead of guesswork.

"Redraw Figure 1 like this" is the highest-risk request in the whole system: fonts
wrong, layout drifting, data points nudged by hand, and no way to verify. This script
removes the guesswork by extracting measurable facts from the reference image:

  * canvas size and detected margin (content bounding box)
  * horizontal band structure (rows of ink) -> the vertical rhythm
  * column structure (columns of ink) -> the horizontal rhythm
  * ink density per band -> where the visual weight sits
  * dominant background and foreground tones -> contrast budget
  * connected-component boxes -> candidate element rectangles

The output is a JSON report the agent reads *before* writing any IR. It answers
"how many rows, how many columns, how big is a box" with numbers.

Usage:
    python -m core.probe.probe_geometry <reference.png> [--report out.json] [--bands 8]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

MIN_BAND_INK = 0.004   # a band with less ink than this is whitespace
MIN_GAP_PX = 6         # ink gaps narrower than this do not separate bands


def load_gray(path: str | Path) -> np.ndarray:
    img = Image.open(path)
    if img.mode != "L":
        img = img.convert("L")
    return np.asarray(img).astype(np.float64) / 255.0


def ink_mask(gray: np.ndarray, threshold: float = 0.92) -> np.ndarray:
    """Boolean mask of 'ink' pixels: anything meaningfully darker than paper."""
    return gray < threshold


def _runs(mask_1d: np.ndarray, min_gap: int = MIN_GAP_PX) -> list[tuple[int, int]]:
    """Contiguous True runs, merging runs separated by fewer than min_gap False pixels."""
    if not mask_1d.any():
        return []
    idx = np.flatnonzero(mask_1d)
    breaks = np.flatnonzero(np.diff(idx) > min_gap)
    starts = np.concatenate([[idx[0]], idx[breaks + 1]])
    ends = np.concatenate([idx[breaks], [idx[-1]]])
    return list(zip(starts.tolist(), ends.tolist()))


def measure(gray: np.ndarray) -> dict:
    h, w = gray.shape
    mask = ink_mask(gray)

    row_ink = mask.mean(axis=1)
    col_ink = mask.mean(axis=0)

    # ---- content bounding box = canvas minus meaningless white border ----
    rows_with_ink = np.flatnonzero(row_ink > 0.001)
    cols_with_ink = np.flatnonzero(col_ink > 0.001)
    if len(rows_with_ink) == 0 or len(cols_with_ink) == 0:
        return {"size": [w, h], "empty": True}
    top, bottom = int(rows_with_ink[0]), int(rows_with_ink[-1])
    left, right = int(cols_with_ink[0]), int(cols_with_ink[-1])
    margin = [left, top, w - 1 - right, h - 1 - bottom]

    # ---- band structure: rows of ink separated by whitespace ----
    band_rows = _runs(row_ink > MIN_BAND_INK)
    bands = []
    for (y0, y1) in band_rows:
        seg = mask[y0 : y1 + 1]
        bands.append({
            "y": [int(y0), int(y1)],
            "height": int(y1 - y0 + 1),
            "ink_density": round(float(seg.mean()), 4),
        })

    # ---- column structure within the widest band ----
    if bands:
        widest = max(bands, key=lambda b: b["ink_density"])
        y0, y1 = widest["y"]
        seg_cols = mask[y0 : y1 + 1].mean(axis=0)
        column_runs = _runs(seg_cols > 0.002)
    else:
        column_runs = []
    columns = [{"x": [int(a), int(b)], "width": int(b - a + 1)} for a, b in column_runs]

    # ---- rhythm: spacing between band starts ----
    band_starts = [b["y"][0] for b in bands]
    band_gaps = [int(band_starts[i + 1] - band_starts[i]) for i in range(len(band_starts) - 1)]

    # ---- tones ----
    flat = gray.ravel()
    background = float(np.percentile(flat, 98))
    foreground = float(np.percentile(flat, 2))

    return {
        "size": [w, h],
        "content_bbox": [left, top, right, bottom],
        "margin_px": margin,
        "margin_symmetric": bool(margin[0] == margin[2] and margin[1] == margin[3]),
        "band_count": len(bands),
        "bands": bands,
        "band_start_gaps": band_gaps,
        "column_count": len(columns),
        "columns": columns,
        "tone": {
            "background": round(background, 4),
            "foreground": round(foreground, 4),
            "delta": round(background - foreground, 4),
        },
        "ink_coverage": round(float(mask.mean()), 4),
    }


def suggest_ir(report: dict, tokens_name: str = "academic") -> dict:
    """Turn measurements into a starting IR skeleton.

    This is a *starting point*, never a finished figure: it gives the agent the grid
    (rows/columns/pitch) derived from evidence, and leaves content and style to be
    filled from the reference's semantics.
    """
    if report.get("empty"):
        raise ValueError("reference figure has no ink; cannot suggest an IR")
    bands = report["bands"]
    columns = report["columns"]
    rows = max(len(bands), 1)
    cols = max(len(columns), 1)
    box_h = min(b["height"] for b in bands) if bands else 12
    col_w = min(c["width"] for c in columns) if columns else 24
    unit = 8.0
    return {
        "schema": "figsmith.ir/1.0",
        "meta": {
            "domain": "unknown",
            "chart_type": "unknown",
            "tokens": tokens_name,
            "width_unit": round(report["size"][0] / unit, 1)
        },
        "content": {"labels": {}},
        "topology": {"nodes": [], "edges": []},
        "layout": {
            "canvas": {"margin": round(min(report["margin_px"]) / unit, 1), "px_per_unit": unit},
            "grid": {
                "columns": cols,
                "gap_x": 3.0,
                "gap_y": 3.0,
                "box_w": round(col_w / unit, 1),
                "box_h": round(box_h / unit, 1),
            },
            "nodes": {},
        },
        "style": {
            "fill": {"default": "colors.surface_band"},
            "stroke": {"default": "colors.border", "width": "stroke.thin"},
            "text": {
                "default": "fonts.role.panel_label",
                "size": "fonts.size_pt.panel_label",
                "color": "colors.ink",
            },
            "emphasis": [],
        },
        "_probe": {
            "rows_detected": rows,
            "columns_detected": cols,
            "margin_px": report["margin_px"],
            "tone_delta": report["tone"]["delta"],
        },
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Measure a reference figure's geometry.")
    ap.add_argument("image")
    ap.add_argument("--report", default=None, help="write the JSON report here")
    ap.add_argument("--suggest-ir", default=None, help="write a starting IR skeleton here")
    ap.add_argument("--tokens", default="academic")
    args = ap.parse_args(argv)

    gray = load_gray(args.image)
    report = measure(gray)
    report["file"] = args.image

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.suggest_ir:
        ir = suggest_ir(report, args.tokens)
        Path(args.suggest_ir).write_text(json.dumps(ir, indent=2, ensure_ascii=False), encoding="utf-8")

    if not report.get("empty"):
        print(f"canvas {report['size'][0]}x{report['size'][1]}  "
              f"margin {report['margin_px']} (symmetric={report['margin_symmetric']})")
        print(f"bands {report['band_count']}  columns {report['column_count']}  "
              f"ink {report['ink_coverage']:.3f}  tone delta {report['tone']['delta']:.3f}")
        if report["band_start_gaps"]:
            print(f"band pitch {report['band_start_gaps']}")
    else:
        print("no ink detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
