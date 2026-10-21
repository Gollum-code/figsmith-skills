#!/usr/bin/env python3
"""backends/png.py - SVG -> PNG at explicit sizes, plus PNG -> PDF.

No cairosvg, no headless browser: uses the system Edge/Chrome if available for
rasterization (best fidelity for text), and falls back to a Pillow-based
rasterizer for the primitive subset FigSmith emits (rect / line / path / text).
The fallback keeps the toolchain offline and dependency-free; when a browser is
present it is preferred because it gets font shaping and text metrics right.

Usage:
    python -m backends.png <in.svg> [-o out.png] [--width 1600] [--dpi 600]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
CHROME_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_browser() -> str | None:
    for path in CHROME_CANDIDATES + CHROME_MAC:
        if os.path.exists(path):
            return path
    found = shutil.which("chrome") or shutil.which("msedge") or shutil.which("chromium")
    return found


def sandbox_flags() -> list[str]:
    """Chrome flags needed to start on this host.

    `--no-sandbox` is required when the Chromium sandbox cannot start: as root, and on
    CI runners where unprivileged user namespaces are disabled (GitHub Actions ships
    Chrome but not a usable sandbox). On a normal desktop session it is a needless
    hardening loss, so it is conditional. Set FIGSMITH_NO_SANDBOX=1 to force it on.
    """
    forced = os.environ.get("FIGSMITH_NO_SANDBOX", "").strip().lower() in {"1", "true", "yes"}
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    in_ci = os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}
    return ["--no-sandbox"] if (forced or is_root or in_ci) else []


def svg_to_png(svg_path: str | Path, out_path: str | Path, width_px: int | None = None,
               dpi: int | None = None) -> str:
    """Rasterize an SVG to PNG.

    Browser path: embed the SVG in a minimal HTML page sized exactly to the target
    pixel width, then screenshot the viewport. Never use fullPage - that is the trap
    that silently stitches repeated content (METHOD hard-trap #3). The page is sized
    so the viewport *is* the content.
    """
    svg_file = Path(svg_path).resolve()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    browser = find_browser()
    if browser:
        return _browser_raster(svg_file, out, width_px, dpi, browser)
    return _pillow_raster(svg_file, out, width_px)


def _browser_raster(svg_file: Path, out: Path, width_px: int | None, dpi: int | None,
                    browser: str) -> str:
    from PIL import Image

    svg_text = svg_file.read_text(encoding="utf-8-sig")
    # intrinsic size from the svg tag
    import re
    m = re.search(r'width="([\d.]+)"', svg_text)
    intrinsic_w = float(m.group(1)) if m else 1600.0
    target_w = int(width_px) if width_px else int(round(intrinsic_w * (dpi or 96) / 96.0))
    target_w = max(target_w, 64)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        page = tmp_path / "page.html"
        page.write_text(
            "<!doctype html><meta charset=utf-8><style>"
            "html,body{margin:0;padding:0;background:#fff;overflow:hidden}"
            f"svg{{display:block;width:{target_w}px;height:auto}}"
            "</style>" + svg_text,
            encoding="utf-8",
        )
        raw = tmp_path / "shot.png"
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={target_w},2400",
            *sandbox_flags(),
            f"--screenshot={raw}",
            f"file:///{page.as_posix()}",
        ]
        subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        if not raw.exists():
            raise RuntimeError(f"browser raster produced no output: {' '.join(cmd[:4])}...")
        img = Image.open(raw).convert("RGB")
        # crop to the actual ink extents so the PNG has no meaningless white border
        bbox = img.convert("L").point(lambda v: 0 if v > 250 else 255).getbbox()
        if bbox:
            pad = 0
            img = img.crop(bbox and (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                                     min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height)))
        img.save(out, "PNG")
    return str(out)


def _pillow_raster(svg_file: Path, out: Path, width_px: int | None) -> str:
    """Minimal fallback rasterizer for the FigSmith primitive subset.

    Handles rect / line / path(triangle) / text. Good enough for the geometry checks;
    the browser path is used whenever a browser exists because it shapes text properly.
    """
    import re

    from PIL import Image, ImageDraw, ImageFont

    text = svg_file.read_text(encoding="utf-8-sig")
    m = re.search(r'width="([\d.]+)"\s+height="([\d.]+)"', text)
    w0, h0 = (float(m.group(1)), float(m.group(2))) if m else (800.0, 600.0)
    scale = (width_px / w0) if width_px else 1.0
    W, H = int(w0 * scale), int(h0 * scale)

    img = Image.new("RGB", (W, H), "#FFFFFF")  # hex-ok: canvas base for the Pillow fallback
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", max(int(14 * scale), 8))
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()

    def num(s: str) -> float:
        return float(s) * scale

    for rect in re.finditer(r'<rect ([^/]*)/>', text):
        a = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', rect.group(1)))
        try:
            d.rectangle([num(a["x"]), num(a["y"]), num(a["x"]) + num(a["w"]), num(a["y"]) + num(a["h"])],
                        fill=a.get("fill", "#FFFFFF"), outline=a.get("stroke"))
        except KeyError:
            continue

    for line in re.finditer(r'<line ([^/]*)/>', text):
        a = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', line.group(1)))
        d.line([num(a["x1"]), num(a["y1"]), num(a["x2"]), num(a["y2"])],
               fill=a.get("stroke", "#000000"), width=max(int(num(a.get("stroke-width", "1"))), 1))

    for tri in re.finditer(r'<path d="M ([\d.-]+) ([\d.-]+) l ([-\d.]+) ([-\d.]+) l ([-\d.]+) ([-\d.]+) Z" fill="([^"]+)"', text):
        x, y, l1x, l1y, l2x, l2y, fill = tri.groups()
        pts = [(num(x), num(y)), (num(x) + num(l1x), num(y) + num(l1y)),
               (num(x) + num(l1x) + num(l2x), num(y) + num(l1y) + num(l2y))]
        d.polygon(pts, fill=fill)

    for t in re.finditer(r'<text ([^>]*)>([^<]*)</text>', text):
        a = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', t.group(1)))
        body = t.group(2)
        anchor = a.get("text-anchor", "start")
        x, y = num(a.get("x", "0")), num(a.get("y", "0"))
        size = max(int(num(a.get("font-size", "12"))), 8)
        try:
            f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)
        except Exception:  # noqa: BLE001
            f = font
        tw = d.textlength(body, font=f)
        if anchor == "middle":
            x -= tw / 2
        d.text((x, y - size), body, fill=a.get("fill", "#000000"), font=f)

    img.save(out, "PNG")
    return str(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Rasterize an SVG to PNG.")
    ap.add_argument("svg")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--width", type=int, default=None, help="target pixel width")
    ap.add_argument("--dpi", type=int, default=None, help="target dpi (implies width scaling)")
    args = ap.parse_args(argv)

    out = args.out or str(Path(args.svg).with_suffix(".png"))
    path = svg_to_png(args.svg, out, args.width, args.dpi)
    from PIL import Image
    print(f"wrote {path} {Image.open(path).size}  browser={'yes' if find_browser() else 'no (pillow fallback)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
