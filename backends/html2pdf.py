#!/usr/bin/env python3
"""backends/html2pdf.py - HTML/CSS -> PDF -> PNG proxy, for the layout route.

This is the backend for deck-slides / poster-flyer / infographic. It encodes the P3-T0
spike's conclusions (docs/spike-html2vector.md):

  * Text, boxes and rules stay VECTOR: Chromium's print pipeline emits them as PDF text
    and path operators. This is the property that makes the route usable.
  * Gradients and shadows rasterize into image XObjects. So they are decoration only -
    never structural color. Structural fills use flat token colors.
  * The page size comes from @page, not from the viewport: CSS pixels are not PDF points
    and an unset page size silently spills onto a second page.

Usage:
    python -m backends.html2pdf page.html -o out.pdf [--png out.png] [--page-size 1200x900]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backends.png import find_browser, sandbox_flags  # noqa: E402


def _inject_page_css(html: str, width_px: int, height_px: int) -> str:
    """Give @page an exact pixel size.

    Without this the PDF takes its size from the print dialog defaults and a 1200px-wide
    page overflows A4 portrait onto a second sheet - which the spike measured.
    """
    from PIL import Image  # noqa: F401  (kept for symmetry; no use here)

    # 1 CSS px = 1/96 in, and PDF points are 1/72 in, so 1px = 0.75pt
    w_pt = width_px * 0.75
    h_pt = height_px * 0.75
    style = (
        f"<style>@page {{ size: {w_pt:.2f}pt {h_pt:.2f}pt; margin: 0; }}"
        f"html, body {{ margin: 0; padding: 0; width: {width_px}px; }}</style>"
    )
    if "</head>" in html:
        return html.replace("</head>", style + "</head>", 1)
    return style + html


def html_to_pdf(html: str, out_pdf: str | Path, width_px: int = 1200,
                height_px: int = 900, timeout: int = 120) -> str:
    browser = find_browser()
    if not browser:
        raise RuntimeError(
            "no Chromium-based browser found. The layout route needs Chrome or Edge; "
            "install one or use the SVG route instead."
        )
    out = Path(out_pdf).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(_inject_page_css(html, width_px, height_px), encoding="utf-8")
        proc = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", *sandbox_flags(),
             "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
             "--virtual-time-budget=3000",
             f"--print-to-pdf={out}", page.resolve().as_uri()],
            capture_output=True, timeout=timeout, check=False,
        )
        if not out.exists():
            raise RuntimeError(f"browser print-to-pdf produced nothing:\n{proc.stderr.decode(errors='ignore')[:400]}")
    return str(out)


def pdf_to_png_proxy(pdf_path: str | Path, out_png: str | Path, width_px: int = 1600,
                    height_px: int | None = None) -> str:
    """Rasterize the PDF for verification. PDFs cannot be handed to `read`
    (docs/vision-probe-report.md test 5), so every PDF deliverable ships a proxy.

    Chromium's PDF viewer plugin does not render under --headless=new (measured: the
    screenshot comes back as a flat gray page), so embedding the PDF in a page does not
    work. The proxy instead screenshots the *source HTML* at the same size: the PDF and
    the HTML were produced from the same bytes by the same engine, so what the HTML
    shows is what the PDF contains. The PDF's own structural integrity is checked
    separately (tools/four_way_check._pdf_is_vector).
    """
    browser = find_browser()
    if not browser:
        raise RuntimeError("no browser available for PDF proxy rasterization")
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)

    src_html = Path(str(pdf_path).replace(".pdf", ".html"))
    if not src_html.exists():
        raise FileNotFoundError(
            f"{src_html} not found: the proxy screenshots the source HTML next to the PDF; "
            "keep them side by side."
        )
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "shot.png"
        # Size the viewport to the declared page height so a tall poster is captured whole.
        view_h = int(height_px) if height_px else 3200
        cmd = [
            browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=1", f"--window-size={width_px},{view_h}",
            *sandbox_flags(), f"--screenshot={shot}", src_html.resolve().as_uri(),
        ]
        subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        if not shot.exists():
            raise RuntimeError("PDF proxy rasterization failed")
        from PIL import Image

        img = Image.open(shot).convert("RGB")
        bbox = img.convert("L").point(lambda v: 0 if v > 250 else 255).getbbox()
        if bbox:
            img = img.crop(bbox)
        img.save(out)
    return str(out)


def render(html: str, out_pdf: str | Path, width_px: int = 1200, height_px: int = 900,
           png_proxy: str | Path | None = None) -> dict:
    out = Path(out_pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Keep the source HTML next to the PDF: the proxy screenshots it, and it is the
    # editable source for the deliverable (METHOD 8: source and artifact stay separate).
    src_html = out.with_suffix(".html")
    src_html.write_text(_inject_page_css(html, width_px, height_px), encoding="utf-8")

    pdf = html_to_pdf(html, out, width_px, height_px)
    result = {"pdf": pdf, "html": str(src_html), "png": None}
    if png_proxy:
        result["png"] = pdf_to_png_proxy(pdf, png_proxy, width_px=width_px, height_px=height_px)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="HTML/CSS -> PDF (+ PNG proxy).")
    ap.add_argument("html")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--png", default=None)
    ap.add_argument("--size", default="1200x900", help="WIDTHxHEIGHT in CSS px")
    args = ap.parse_args(argv)

    w, _, h = args.size.partition("x")
    src = Path(args.html)
    out = args.out or str(src.with_suffix(".pdf"))
    png = args.png or str(src.with_suffix(".png"))

    html = src.read_text(encoding="utf-8-sig")
    result = render(html, out, int(w), int(h), png)
    print(f"wrote {result['pdf']}" + (f" and {result['png']}" if result["png"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
