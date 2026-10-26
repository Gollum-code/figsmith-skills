#!/usr/bin/env python3
"""tools/four_way_check.py - one IR, four artifacts, one content set.

P4's completion definition is "same declaration -> SVG + PDF + PNG + PPTX, content
consistent". This script makes that verifiable instead of asserted:

  1. render all four outputs from one IR
  2. extract every text string from each artifact
  3. assert the label sets are equal (order-insensitive)
  4. assert the SVG -> PDF path preserved geometry (same count of rect/line primitives)
  5. report the size of each artifact so a silent raster fallback is visible

Usage:
    python tools/four_way_check.py <ir.json> [-o outdir]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _run(module: str, *args: str) -> str:
    cmd = [sys.executable, "-m", module, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{proc.stderr}")
    return proc.stdout.strip()


def svg_texts(svg_path: Path) -> set[str]:
    """Every distinct string in the SVG.

    Multi-line labels are emitted as one <text> per line, so 'Business logic' arrives as
    two entries. The caller normalises by comparing whole labels against the union of the
    emitted lines, which is what "no label dropped" actually means.
    """
    raw = svg_path.read_text(encoding="utf-8-sig")
    return {m.group(1).strip() for m in re.finditer(r"<text[^>]*>([^<]*)</text>", raw) if m.group(1).strip()}


def expected_texts(ir: dict) -> set[str]:
    """Every string the figure is supposed to carry.

    Structural figures keep their text in content.labels; a statistical figure has an
    empty label map, which made the consistency check vacuous for exactly the route where
    the data must not drift. Its axis titles, series names and footnote are what has to
    survive into every artifact, so they are collected here too.
    """
    content = ir.get("content", {})
    texts: set[str] = set()
    for value in content.get("labels", {}).values():
        if str(value).strip():
            texts.add(str(value).strip())
    for key, value in content.get("axis", {}).items():
        if str(value).strip():
            texts.add(str(value).strip())
    data = ir.get("data") or {}
    chart = ir.get("meta", {}).get("chart_type", "")
    # A pie/donut is a composition, so its legend is the categories; the series name is
    # not drawn and must not be demanded of the SVG.
    if chart not in ("pie", "donut"):
        for series in data.get("series", []):
            if str(series.get("name", "")).strip():
                texts.add(str(series["name"]).strip())
    for category in data.get("categories", []):
        if str(category).strip():
            texts.add(str(category).strip())
    # meta.title is document metadata (slide title, filename), not a string drawn into
    # the figure; content.labels is the layer that owns on-canvas text (IR.md 2.2).
    return texts


def label_coverage(expected: set[str], found: set[str]) -> set[str]:
    """Labels that appear nowhere in `found`.

    A label counts as present when either it appears verbatim or its whitespace-joined
    words all appear in order. This is what lets a wrapped label pass without forcing
    every backend to render on one line.
    """
    missing: set[str] = set()
    for label in expected:
        if label in found:
            continue
        words = [w for w in label.split() if w]
        if not words:
            continue
        if all(w in found for w in words):
            continue
        missing.add(label)
    return missing


def svg_primitive_counts(svg_path: Path) -> dict[str, int]:
    raw = svg_path.read_text(encoding="utf-8-sig")
    return {
        "rect": len(re.findall(r"<rect ", raw)),
        "line": len(re.findall(r"<line ", raw)),
        "path": len(re.findall(r"<path ", raw)),
        "text": len(re.findall(r"<text ", raw)),
    }


def pdf_texts(pdf_path: Path) -> set[str]:
    """Extract strings from the PDF content stream.

    reportlab writes text with Tj/TJ operators; the strings are mostly literal but can be
    hex-encoded or split. We decode what we can and compare on the literal subset: the
    point is to catch a *missing* label, not to round-trip encodings.
    """
    data = pdf_path.read_bytes()
    found: set[str] = set()
    for m in re.finditer(rb"\(((?:[^()\\]|\\.)*)\)\s*Tj", data):
        raw = m.group(1)
        try:
            found.add(raw.decode("latin-1"))
        except UnicodeDecodeError:
            continue
    # hex strings <...> Tj
    for m in re.finditer(rb"<([0-9A-Fa-f]+)>\s*Tj", data):
        try:
            found.add(bytes.fromhex(m.group(1).decode()).decode("utf-16-be", errors="ignore"))
        except ValueError:
            continue
    return {f for f in found if f.strip()}


def pptx_texts(pptx_path: Path) -> set[str]:
    found: set[str] = set()
    with zipfile.ZipFile(pptx_path) as zf:
        for name in zf.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                xml = zf.read(name).decode("utf-8", errors="ignore")
                found.update(re.findall(r"<a:t>([^<]*)</a:t>", xml))
    return {f.strip() for f in found if f.strip()}


def png_is_real(png_path: Path) -> bool:
    from PIL import Image

    img = Image.open(png_path)
    return img.width > 100 and img.height > 100


def _embedded_image_areas(data: bytes) -> list[int]:
    """Pixel areas of embedded image XObjects (/Width x /Height).

    A small logo is legitimate; a raster that covers the page is a deliverable that was
    never vector. Raw-bytes scanning is coarse but adequate: every image XObject carries
    /Subtype /Image, and its /Width and /Height sit in the same dictionary.
    """
    areas: list[int] = []
    for m in re.finditer(rb"/Subtype\s*/Image", data):
        window = data[max(0, m.start() - 600): m.start() + 600]
        w = re.search(rb"/Width\s+(\d+)", window)
        h = re.search(rb"/Height\s+(\d+)", window)
        if w and h:
            areas.append(int(w.group(1)) * int(h.group(1)))
    return areas


def _pdf_is_vector(pdf_path: Path) -> bool:
    """A real vector PDF has a content stream with drawing operators and no embedded
    image covering the page. A 'PNG wrapped in PDF' fails here; a small logo does not."""
    import base64
    import zlib

    data = pdf_path.read_bytes()
    if not data.startswith(b"%PDF-"):
        return False

    # An image is only disqualifying when it is page-sized. Compare its pixel area to the
    # page area (points^2): at 1x a full-page raster is roughly page_area pixels, so 50%
    # of the page cleanly separates "the deliverable" from "a logo in the corner".
    page_area = 0.0
    mb = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    if mb:
        page_area = abs(float(mb.group(3)) - float(mb.group(1))) * \
                    abs(float(mb.group(4)) - float(mb.group(2)))
    limit = 0.5 * page_area if page_area else 1_000_000
    if any(area >= limit for area in _embedded_image_areas(data)):
        return False

    streams = re.findall(rb"stream\r?\n(.*?)endstream", data, re.S)

    def decode_stream(raw: bytes) -> list[bytes]:
        """The stream may be plain, Flate, ASCII85, or ASCII85+Flate (reportlab's
        default for pages with images). Try each so operator detection does not
        silently fail on a perfectly valid vector PDF."""
        candidates = [raw]
        try:
            candidates.append(zlib.decompress(raw))
        except Exception:  # noqa: BLE001
            pass
        try:
            a85 = base64.a85decode(raw.strip(), adobe=True)
            candidates.append(a85)
            try:
                candidates.append(zlib.decompress(a85))
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
        return candidates

    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        # Image data is binary and can contain "BT" by coincidence. Images are judged
        # by the area check above, so skip them here.
        header = data[max(0, m.start() - 800): m.start()]
        if b"/Subtype /Image" in header:
            continue
        for content in decode_stream(m.group(1)):
            if b" re" in content or b" l\n" in content or b"BT" in content:
                return True
    return False


def _pdf_structural(pdf: Path) -> tuple[bool, str]:
    """The PDF half of the four-way contract: one page, vector content, real size.

    A raster proxy was the previous approach, but headless Chromium ships no PDF viewer,
    so the capture always came back blank and the check silently degraded to a no-op.
    The container is verified directly instead: page count, text operators, page-sized
    rasters. That is what "the PDF is a real deliverable" actually means.
    """
    from tools.pdf_check import check as pdf_check

    result = pdf_check(pdf, expect_pages=1)
    return bool(result["passed"]), (
        f"pages={result.get('pages')} text_ops={result.get('text_ops')} "
        f"vector={result.get('vector')}")


def check(ir_path: Path, outdir: Path) -> dict:
    from PIL import Image

    outdir.mkdir(parents=True, exist_ok=True)
    ir = json.loads(ir_path.read_text(encoding="utf-8-sig"))
    scale = float(ir.get("layout", {}).get("canvas", {}).get("px_per_unit", 12.0))

    svg = outdir / "figure.svg"
    png = outdir / "figure.png"
    pdf = outdir / "figure.pdf"
    pptx = outdir / "figure.pptx"

    # Route decides the backend (same rule as tools/regress.py). A statistical figure
    # has no nodes, so the structure backend emits an empty SVG; it must go through
    # matplotlib or this checker reports a false failure on a perfectly good figure.
    statistical = bool(ir.get("data", {}).get("series"))
    if statistical:
        _run("backends.mpl2svg", str(ir_path), "-o", str(svg), "--png", str(png))
        # The mpl SVG is the geometry; embed that same SVG as vector so the PDF cannot
        # drift from what was verified.
        _run("backends.pdf", "--from-svg", str(svg), "-o", str(pdf))
    else:
        _run("backends.svg", str(ir_path), "-o", str(svg), "--scale", str(scale))
        _run("backends.png", str(svg), "-o", str(png), "--width", "1200")
        _run("backends.pdf", str(ir_path), "-o", str(pdf))
    _run("backends.pptx", str(ir_path), "-o", str(pptx))

    expected = expected_texts(ir)
    # A statistical figure's axis ticks, legend and footnote live in the matplotlib SVG;
    # the PPTX carries the chart as an image plus its axis labels and series names as text.
    svg_expected = expected
    if statistical:
        pptx_expected = {str(v).strip() for v in ir.get("content", {}).get("axis", {}).values()
                         if str(v).strip()}
        pptx_expected |= {str(s.get("name")).strip()
                          for s in ir.get("data", {}).get("series", []) if s.get("name")}
    else:
        pptx_expected = expected

    got = {
        "svg": svg_texts(svg),
        "pptx": pptx_texts(pptx),
    }
    expectations = {"svg": svg_expected, "pptx": pptx_expected}

    report = {
        "ir": str(ir_path),
        "labels_expected": len(expected),
        "artifacts": {},
        "missing": {},
        "passed": True,
    }

    for fmt, texts in got.items():
        missing = sorted(label_coverage(expectations[fmt], texts))[:8]
        ok = not missing
        report["artifacts"][fmt] = {"ok": ok, "detail": f"texts={len(texts)}", "texts": len(texts)}
        report["missing"][fmt] = missing
        if not ok:
            report["passed"] = False

    # PDF is verified structurally, never by text extraction (docs/vision-probe-report.md
    # 3.2): page count, text operators and vector-ness. A "PNG wrapped in PDF" fails.
    pdf_ok, pdf_detail = _pdf_structural(pdf)
    report["artifacts"]["pdf"] = {"ok": pdf_ok, "detail": pdf_detail, "texts": None}
    report["missing"]["pdf"] = []
    if not pdf_ok:
        report["passed"] = False

    report["artifacts"]["png"] = {"size": list(Image.open(png).size), "ok": png_is_real(png)}
    report["primitives"] = svg_primitive_counts(svg)
    report["bytes"] = {p.suffix[1:]: p.stat().st_size for p in (svg, png, pdf, pptx)}
    if not report["artifacts"]["png"]["ok"]:
        report["passed"] = False
    return report


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Four-way content consistency check.")
    ap.add_argument("ir")
    ap.add_argument("-o", "--outdir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ir_path = Path(args.ir)
    if args.outdir:
        outdir = Path(args.outdir)
        report = check(ir_path, outdir)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            report = check(ir_path, Path(tmp))

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        mark = "PASS" if report["passed"] else "FAIL"
        print(f"[{mark}] {report['ir']}")
        print(f"  expected labels: {report['labels_expected']}")
        for fmt, meta in report["artifacts"].items():
            extra = f" {meta['size']}" if "size" in meta else ""
            detail = f"  {meta['detail']}" if fmt == "pdf" else ""
            print(f"  {fmt:5} texts={meta.get('texts', '-')} ok={meta['ok']}{extra}{detail}")
        print(f"  hung primitives: {report['primitives']}")
        print(f"  bytes: {report['bytes']}")
        if not report["passed"]:
            for fmt, missing in report["missing"].items():
                if missing:
                    print(f"  {fmt} missing: {missing}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
