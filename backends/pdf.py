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


_FONT_FILES = {
    "Arial": ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
    "Arial Bold": ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
                   "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
    "Times New Roman": ["C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf",
                        "/System/Library/Fonts/Times.ttc",
                        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"],
    "SimHei": ["C:/Windows/Fonts/simhei.ttf",
               "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
    "SimSun": ["C:/Windows/Fonts/simsun.ttc",
               "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"],
    "Microsoft YaHei": ["C:/Windows/Fonts/msyh.ttc",
                        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
    "DejaVu Sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "C:/Windows/Fonts/DejaVuSans.ttf"],
    "DejaVu Serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
    "DejaVu Sans Mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
    "Noto Sans CJK SC": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                         "C:/Windows/Fonts/msyh.ttc"],
    "Noto Serif CJK SC": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
                          "C:/Windows/Fonts/simsun.ttc"],
}
# A CJK-capable file used when the requested family has no CJK coverage. Without it a
# Chinese label renders as blank space in the PDF while every other artifact shows it.
_CJK_FALLBACKS = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Supplemental/PingFang.ttc",
]

_CJK_FONT_NAME: str | None = None
_CJK_RESOLVED = False


def _has_cjk(path: str) -> bool:
    """True when the font carries CJK codepoints (or when that cannot be determined)."""
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(path, fontNumber=0, lazy=True)
        return any(0x4E00 <= cp <= 0x9FFF for cp in font.getBestCmap())
    except Exception:  # noqa: BLE001
        return False


def _register_cjk_font() -> str | None:
    """Register the first CJK-capable font on this host, once per process."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path in _CJK_FALLBACKS:
        if not Path(path).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("FigSmithCJK", path))
            return "FigSmithCJK"
        except Exception:  # noqa: BLE001
            continue
    return None


def _cjk_font() -> str | None:
    global _CJK_FONT_NAME, _CJK_RESOLVED  # noqa: PLW0603
    if not _CJK_RESOLVED:
        _CJK_FONT_NAME = _register_cjk_font()
        _CJK_RESOLVED = True
    return _CJK_FONT_NAME


def _find_font(family: str, bold: bool = False):
    """Resolve an SVG font-family list to a reportlab-registered TTF.

    The stack is walked in order (the SVG writer emits latin + CJK in one attribute).
    A latin font is returned even when it has no CJK coverage: `_draw_string` falls back
    to the CJK companion per glyph, so Chinese labels survive instead of vanishing.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    names = [n.strip().strip('"').strip("'") for n in (family or "").split(",") if n.strip()]
    if bold:
        names = [f"{n} Bold" for n in names] + names

    for name in names:
        for path in _FONT_FILES.get(name, []):
            if not Path(path).exists():
                continue
            stem = Path(path).stem.replace(" ", "")
            try:
                if stem not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(stem, path))
            except Exception:  # noqa: BLE001
                continue
            return stem
    return "Helvetica-Bold" if bold else "Helvetica"


def _draw_string(c, x: float, y: float, text: str, size: float, font: str) -> None:
    """Draw a string, switching to the CJK companion for CJK glyphs.

    The latin font in the SVG writer's stack has no CJK coverage, so drawing a Chinese
    label in one font drops every glyph. Splitting the runs costs nothing for pure latin
    text and keeps the mixed labels a paper figure is full of.
    """
    cjk = _cjk_font()
    if not cjk:
        c.setFont(font, size)
        c.drawString(x, y, text)
        return

    from reportlab.pdfbase import pdfmetrics

    runs: list[tuple[str, str]] = []
    for ch in text:
        is_cjk_ch = 0x4E00 <= ord(ch) <= 0x9FFF or 0x3000 <= ord(ch) <= 0x303F
        want = cjk if is_cjk_ch else font
        if runs and runs[-1][1] == want:
            runs[-1] = (runs[-1][0] + ch, want)
        else:
            runs.append((ch, want))

    cursor = x
    for chunk, chunk_font in runs:
        c.setFont(chunk_font, size)
        c.drawString(cursor, y, chunk)
        cursor += pdfmetrics.stringWidth(chunk, chunk_font, size)


def render_from_svg(svg_path: str | Path, out_pdf: str | Path) -> str:
    """Convert the FigSmith SVG subset to vector PDF.

    Handles rect / line / path(triangle) / text with the same semantics the SVG writer
    emits, so a rendered figure and its PDF are the same picture at the same size.
    """
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas as pdf_canvas

    svg_text = Path(svg_path).read_text(encoding="utf-8-sig")
    from backends.svg import parse_svg_size

    w_u, h_u, unit = parse_svg_size(svg_text)
    # Point-preserving rule: a unitless/"px" SVG declares no physical size, so one user
    # unit is treated as one PDF point exactly as before (existing deliverables do not
    # move). A declared physical unit (pt/mm/cm/in - what matplotlib emits) is honoured,
    # and the drawing is scaled into that page. Reading the first width/height pair in
    # the whole document used to grab a rectangle instead of the root, so the page size
    # depended on element order.
    to_pt = {"pt": 1.0, "px": 1.0, "mm": 72.0 / 25.4, "cm": 72.0 / 2.54, "in": 72.0}[unit]
    width_pt, height_pt = w_u * to_pt, h_u * to_pt

    c = pdf_canvas.Canvas(str(out_pdf), pagesize=(width_pt, height_pt))
    if to_pt != 1.0:
        c.scale(to_pt, to_pt)
    c.setLineJoin(1)
    # Flip using the user-space height: after c.scale the coordinate system is user units.
    height_pt = h_u

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
        c.setFillColor(rgb(a.get("fill", "#000000")))
        # The SVG writer now always emits a font-family stack; a missing one still has
        # to draw, so it falls through to the Arial entry.
        from reportlab.pdfbase import pdfmetrics
        text_w = pdfmetrics.stringWidth(body, font, size)
        if anchor == "middle":
            x -= text_w / 2
        elif anchor == "end":
            x -= text_w
        _draw_string(c, x, height_pt - y, body, size, font)

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
