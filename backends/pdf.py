#!/usr/bin/env python3
"""backends/pdf.py - vector PDF output from the FigSmith primitive set.

Two paths, both vector, neither needs a browser:

  1. **Direct PDF** (default): reportlab renders the primitives straight into PDF.
     Text stays selectable, lines stay crisp. This is the path that matters for
     journal submission.
  2. **SVG page embedding**: when the source is already an SVG and the simple parser
     can handle it, we re-emit primitives through the same reportlab surface so the
     fonts stay consistent with the PDF route.

Never rasterize: a "600 dpi PNG wrapped in a PDF" is not a vector deliverable, and
journals reject it.

Usage:
    python -m backends.pdf <ir.json> -o out.pdf
    python -m backends.pdf --from-svg in.svg -o out.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tokens import load as load_tokens  # noqa: E402

# PDF units are points; 1 unit = 1/72 inch
UNIT_PER_POINT = 1.0


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return r, g, b


def _find_font(family: str, bold: bool = False):
    """Resolve a font name to a reportlab-registered TTF, falling back to Helvetica."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = {
        "Arial": ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf",
                  "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
        "Times New Roman": ["C:/Windows/Fonts/times.ttf", "/System/Library/Fonts/Times.ttc",
                            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"],
        "SimHei": ["C:/Windows/Fonts/simhei.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
        "SimSun": ["C:/Windows/Fonts/simsun.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"],
        "Microsoft YaHei": ["C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
    }
    paths = candidates.get(family, candidates["Arial"])
    if bold and len(paths) > 1 and "bd" in paths[1]:
        paths = [paths[1]] + paths
    for path in paths:
        if Path(path).exists():
            name = Path(path).stem.replace(" ", "")
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                return name
            except Exception:  # noqa: BLE001
                continue
    return "Helvetica-Bold" if bold else "Helvetica"


def render_from_svg(svg_path: str | Path, out_pdf: str | Path) -> str:
    """Convert the FigSmith SVG subset to vector PDF.

    Handles rect / line / path(triangle) / text with the same semantics the SVG writer
    emits, so a rendered figure and its PDF are the same picture at the same size.
    """
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas as pdf_canvas

    svg_text = Path(svg_path).read_text(encoding="utf-8-sig")
    m = re.search(r'width="([\d.]+)"\s+height="([\d.]+)"', svg_text)
    if not m:
        raise ValueError("SVG has no explicit width/height; cannot size the PDF page")
    width_pt, height_pt = float(m.group(1)), float(m.group(2))

    c = pdf_canvas.Canvas(str(out_pdf), pagesize=(width_pt, height_pt))
    c.setLineJoin(1)

    def rgb(hex_color: str) -> Color:
        r, g, b = _hex_to_rgb(hex_color)
        return Color(r, g, b)

    # ---- rect ----
    for rect in re.finditer(r"<rect ([^/]*)/>", svg_text):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', rect.group(1)))
        try:
            x, y = float(a["x"]), float(a["y"])
            w, h = float(a["width"]), float(a["height"])
        except KeyError:
            continue
        fill = a.get("fill", "none")
        stroke = a.get("stroke", "none")
        if fill != "none":
            c.setFillColor(rgb(fill))
        if stroke != "none":
            c.setStrokeColor(rgb(stroke))
            c.setLineWidth(float(a.get("stroke-width", 1)))
        # PDF origin is bottom-left; SVG is top-left
        radius = float(a.get("rx", 0) or 0)
        c.roundRect(x, height_pt - y - h, w, h, radius,
                    stroke=1 if stroke != "none" else 0,
                    fill=1 if fill != "none" else 0)

    # ---- line ----
    for line in re.finditer(r"<line ([^/]*)/>", svg_text):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', line.group(1)))
        c.setStrokeColor(rgb(a.get("stroke", "#000000")))
        c.setLineWidth(float(a.get("stroke-width", 1)))
        c.line(float(a["x1"]), height_pt - float(a["y1"]),
               float(a["x2"]), height_pt - float(a["y2"]))

    # ---- path (triangular arrow heads) ----
    for path in re.finditer(
        r'<path d="M ([\d.-]+) ([\d.-]+) l ([-\d.]+) ([-\d.]+) l ([-\d.]+) ([-\d.]+) Z" fill="([^"]+)"',
        svg_text,
    ):
        x, y, l1x, l1y, l2x, l2y, fill = path.groups()
        p = c.beginPath()
        p.moveTo(float(x), height_pt - float(y))
        p.lineTo(float(x) + float(l1x), height_pt - (float(y) + float(l1y)))
        p.lineTo(float(x) + float(l1x) + float(l2x), height_pt - (float(y) + float(l1y) + float(l2y)))
        p.close()
        c.setFillColor(rgb(fill))
        c.drawPath(p, fill=1, stroke=0)

    # ---- text ----
    for t in re.finditer(r"<text ([^>]*)>([^<]*)</text>", svg_text):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', t.group(1)))
        body = t.group(2)
        if not body:
            continue
        size = float(a.get("font-size", "10"))
        x, y = float(a.get("x", "0")), float(a.get("y", "0"))
        anchor = a.get("text-anchor", "start")
        family = a.get("font-family", "Arial")
        bold = a.get("font-weight") == "600" or a.get("font-weight") == "bold"
        font = _find_font(family, bold)
        c.setFont(font, size)
        c.setFillColor(rgb(a.get("fill", "#000000")))
        text_w = c.stringWidth(body, font, size)
        if anchor == "middle":
            x -= text_w / 2
        elif anchor == "end":
            x -= text_w
        c.drawString(x, height_pt - y, body)

    c.showPage()
    c.save()
    return str(out_pdf)


def render_from_ir(ir: dict, out_pdf: str | Path, scale: float | None = None) -> str:
    """Render an IR to PDF by going through the SVG writer, then re-emitting vectors.

    Single source of truth: the SVG backend decides geometry, this backend decides the
    container format. Two independent layout implementations would drift.
    """
    import tempfile

    from backends.svg import render as render_svg

    if scale is None:
        scale = float(ir.get("layout", {}).get("canvas", {}).get("px_per_unit", 8.0))

    with tempfile.TemporaryDirectory() as tmp:
        svg_path = Path(tmp) / "figure.svg"
        render_svg(ir, str(svg_path), scale=scale)
        return render_from_svg(svg_path, out_pdf)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render a FigSmith IR or SVG to vector PDF.")
    ap.add_argument("source", nargs="?")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--from-svg", action="store_true", help="treat source as SVG")
    ap.add_argument("--scale", type=float, default=None)
    args = ap.parse_args(argv)

    if not args.source:
        print(__doc__)
        return 2

    src = Path(args.source)
    out = args.out or str(src.with_suffix(".pdf"))

    if args.from_svg or src.suffix.lower() == ".svg":
        path = render_from_svg(src, out)
    else:
        ir = json.loads(src.read_text(encoding="utf-8-sig"))
        path = render_from_ir(ir, out, args.scale)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
