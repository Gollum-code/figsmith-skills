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

CHROME_WINDOWS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
# Linux packages the binary as `google-chrome` / `chromium-browser`, never `chrome`.
# Missing those names made every Linux host fall back to the Pillow rasterizer, which
# then dropped every rectangle (the w/h vs width/height bug). The candidates are
# probed before the PATH lookup so a stale PATH entry cannot shadow a real install.
CHROME_LINUX = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
]
CHROME_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
PATH_NAMES = ("google-chrome", "google-chrome-stable", "chromium",
              "chromium-browser", "chrome", "msedge", "microsoft-edge")

# Last-resort paint when an SVG primitive omits fill/stroke. The SVG writer always emits
# both, so these only cover a hand-written SVG fed straight to the rasterizer.
_FALLBACK_FILL = "#FFFFFF"  # hex-ok: rasterizer fallback fill
_FALLBACK_PAINT = "#000000"  # hex-ok: rasterizer fallback stroke/text


def find_browser() -> str | None:
    for path in CHROME_WINDOWS + CHROME_LINUX + CHROME_MAC:
        if os.path.exists(path):
            return path
    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


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
    # Root tag only, with unit conversion: a matplotlib SVG declares `width="491pt"`, and
    # a regex that stops at the digit either missed it or (worse) matched a rectangle
    # later in the document.
    from backends.svg import parse_svg_size

    raw_w, raw_h, unit = parse_svg_size(svg_text)
    to_px = {"px": 1.0, "pt": 96.0 / 72.0, "mm": 96.0 / 25.4,
             "cm": 96.0 / 2.54, "in": 96.0}[unit]
    svg_w, svg_h = raw_w * to_px, raw_h * to_px

    target_w = int(width_px) if width_px else int(round(svg_w * (dpi or 96) / 96.0))
    target_w = max(target_w, 64)
    scale = target_w / svg_w if svg_w > 0 else 1.0
    target_h = int(round(svg_h * scale))

    # Chromium refuses a viewport taller than ~16384px and silently clips at the window
    # size, which is how a tall figure used to lose its bottom half. When the figure is
    # taller than the cap the whole figure is scaled down instead of being cut.
    max_h = 16000
    if target_h > max_h:
        shrink = max_h / target_h
        target_w = max(int(target_w * shrink), 64)
        target_h = max_h
        scale = target_w / svg_w if svg_w > 0 else 1.0
        print(f"warning: figure is {target_h}px tall at the requested width; "
              f"scaled to {target_w}px wide so nothing is clipped", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        page = tmp_path / "page.html"
        page.write_text(
            "<!doctype html><meta charset=utf-8><style>"
            "html,body{margin:0;padding:0;background:#fff;overflow:hidden}"
            f"svg{{display:block;width:{target_w}px;height:{target_h}px}}"
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
            f"--window-size={target_w},{target_h}",
            *sandbox_flags(),
            f"--screenshot={raw}",
            f"file:///{page.as_posix()}",
        ]
        subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        if not raw.exists():
            raise RuntimeError(f"browser raster produced no output: {' '.join(cmd[:4])}...")
        img = Image.open(raw).convert("RGB")
        if img.width != target_w or img.height != target_h:
            # Some builds clamp the window height; a smaller capture means the figure is
            # incomplete, which must never be written out as if it were the deliverable.
            raise RuntimeError(
                f"browser captured {img.width}x{img.height}, expected "
                f"{target_w}x{target_h}; the figure would be clipped")
        # The PNG is exactly the SVG canvas. Cropping to the ink bounding box used to
        # strip the structural margin (METHOD 2.3) and, for an icon, the grid padding the
        # 24/48px rule depends on - a 256px icon came out 171x108.
        img.save(out, "PNG")
    return str(out)


def _pillow_raster(svg_file: Path, out: Path, width_px: int | None) -> str:
    """Minimal fallback rasterizer for the FigSmith primitive subset.

    Handles rect / line / path(triangle) / text. Good enough for the geometry checks;
    the browser path is used whenever a browser exists because it shapes text properly.

    It is a rasterizer, not a toy: a rect it silently drops is a figure whose boxes
    vanished while every check still passed. Every primitive the SVG writer emits is
    parsed by attribute name (width/height, not w/h), so nothing is dropped quietly.
    """
    import re

    from PIL import Image, ImageDraw, ImageFont

    text = svg_file.read_text(encoding="utf-8-sig")
    from backends.svg import parse_svg_size

    raw_w, raw_h, unit = parse_svg_size(text)
    to_px = {"px": 1.0, "pt": 96.0 / 72.0, "mm": 96.0 / 25.4,
             "cm": 96.0 / 2.54, "in": 96.0}[unit]
    w0, h0 = raw_w * to_px, raw_h * to_px
    scale = (width_px / w0) if width_px else 1.0
    W, H = int(w0 * scale), int(h0 * scale)

    img = Image.new("RGB", (max(W, 1), max(H, 1)), _FALLBACK_FILL)
    d = ImageDraw.Draw(img)

    def num(s: str) -> float:
        return float(s) * scale

    def color(value: str | None, default: str) -> str:
        """Accept only a colour the SVG writer could have produced.

        A malformed value is not clamped to the default silently - that is how a fill
        disappears without a trace - it is reported so the figure is visibly wrong.
        """
        v = (value or default).strip()
        is_hex = re.fullmatch(r"#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})", v)
        if is_hex or v.lower() in ("white", "black"):
            return v
        raise ValueError(f"not a supported colour literal: {value!r}")

    _fonts: dict[int, object] = {}

    def _font_for(size: int):
        if size not in _fonts:
            _fonts[size] = _load_font(size, size)
        return _fonts[size]

    # ---- rect (accept both width/height and the short w/h forms) ----
    for rect in re.finditer(r"<rect ([^/]*)/>", text):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', rect.group(1)))
        try:
            x = num(a.get("x", "0"))
            y = num(a.get("y", "0"))
            w = num(a.get("width", a.get("w", "0")))
            h = num(a.get("height", a.get("h", "0")))
        except (KeyError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        fill = a.get("fill")
        stroke = a.get("stroke")
        radius = num(a.get("rx", a.get("ry", "0")) or 0)
        try:
            if radius > 0:
                d.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                                    fill=color(fill, _FALLBACK_FILL) if fill and fill != "none" else None,
                                    outline=color(stroke, _FALLBACK_PAINT) if stroke and stroke != "none" else None,
                                    width=max(int(num(a.get("stroke-width", "1"))), 1))
            else:
                d.rectangle([x, y, x + w, y + h],
                            fill=color(fill, _FALLBACK_FILL) if fill and fill != "none" else None,
                            outline=color(stroke, _FALLBACK_PAINT) if stroke and stroke != "none" else None,
                            width=max(int(num(a.get("stroke-width", "1"))), 1))
        except ValueError as exc:
            raise RuntimeError(f"rect at {x:.0f},{y:.0f}: {exc}") from exc

    for line in re.finditer(r"<line ([^/]*)/>", text):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', line.group(1)))
        try:
            d.line([num(a["x1"]), num(a["y1"]), num(a["x2"]), num(a["y2"])],
                   fill=color(a.get("stroke"), _FALLBACK_PAINT),
                   width=max(int(num(a.get("stroke-width", "1"))), 1))
        except ValueError as exc:
            raise RuntimeError(f"line: {exc}") from exc

    # ---- path: absolute M + relative l/z runs, so any arrow head parses ----
    for path in re.finditer(r"<path ([^/]*)/>", text):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', path.group(1)))
        d_attr = a.get("d", "")
        fill = a.get("fill")
        try:
            pts = _parse_path_points(d_attr)
            stroke_col = a.get("stroke")
            if len(pts) >= 2 and stroke_col and stroke_col != "none":
                d.line(pts, fill=color(stroke_col, _FALLBACK_PAINT),
                       width=max(int(num(a.get("stroke-width", "1"))), 1))
            if len(pts) >= 3 and fill and fill != "none":
                d.polygon([(num(px), num(py)) for px, py in pts], fill=color(fill, _FALLBACK_PAINT))
        except ValueError as exc:
            raise RuntimeError(f"path {d_attr[:40]!r}: {exc}") from exc

    for t in re.finditer(r"<text ([^>]*)>([^<]*)</text>", text):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', t.group(1)))
        body = t.group(2)
        anchor = a.get("text-anchor", "start")
        x, y = num(a.get("x", "0")), num(a.get("y", "0"))
        size = max(int(num(a.get("font-size", "12"))), 8)
        f = _font_for(size)
        tw = d.textlength(body, font=f)
        if anchor == "middle":
            x -= tw / 2
        elif anchor == "end":
            x -= tw
        try:
            d.text((x, y - size), body, fill=color(a.get("fill"), _FALLBACK_PAINT), font=f)
        except ValueError as exc:
            raise RuntimeError(f"text {body[:20]!r}: {exc}") from exc

    img.save(out, "PNG")
    return str(out)


_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def _load_font(size: int | None, fallback_size: int = 14):
    """First real TTF on this host, or Pillow's bitmap default as a last resort.

    The candidate list is cross-platform: a hardcoded Windows path made every macOS
    and Linux host fall back to Pillow's 11px bitmap font, which no text budget in
    this project was ever measured against.
    """
    from PIL import ImageFont

    path = next((p for p in _FONT_CANDIDATES if Path(p).exists()), None)
    if path is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size or fallback_size)
    except OSError:
        return ImageFont.load_default()


def _parse_path_points(d_attr: str) -> list[tuple[float, float]]:
    """Parse the absolute-M plus relative-l/z subset the SVG writer emits.

    Returns absolute points. Anything outside that grammar raises, because silently
    returning fewer points is how a path stops being drawn.
    """
    import re

    tokens = re.findall(r"[MmLlHhVvZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d_attr)
    if not tokens or tokens[0] not in ("M", "m"):
        raise ValueError("path must start with an absolute or relative moveto")
    pts: list[tuple[float, float]] = []
    cur = [0.0, 0.0]
    i = 1
    cmd = tokens[0]
    start: tuple[float, float] | None = None
    while i < len(tokens):
        if tokens[i] in "MmLlHhVvZz":
            cmd = tokens[i]
            i += 1
            if cmd in "Zz" and start is not None:
                cur = [start[0], start[1]]
            continue
        try:
            if cmd in "Mm":
                x, y = float(tokens[i]), float(tokens[i + 1])
                cur = [cur[0] + x, cur[1] + y] if cmd == "m" else [x, y]
                start = (cur[0], cur[1])
                pts.append((cur[0], cur[1]))
                i += 2
                cmd = "l" if cmd == "m" else "L"
            elif cmd in "Ll":
                x, y = float(tokens[i]), float(tokens[i + 1])
                cur = [cur[0] + x, cur[1] + y] if cmd == "l" else [x, y]
                pts.append((cur[0], cur[1]))
                i += 2
            elif cmd in "Hh":
                cur[0] = cur[0] + float(tokens[i]) if cmd == "h" else float(tokens[i])
                pts.append((cur[0], cur[1]))
                i += 1
            elif cmd in "Vv":
                cur[1] = cur[1] + float(tokens[i]) if cmd == "v" else float(tokens[i])
                pts.append((cur[0], cur[1]))
                i += 1
            else:
                raise ValueError(f"unsupported path command {cmd!r}")
        except (IndexError, ValueError) as exc:
            raise ValueError(f"malformed path data at token {i}: {exc}") from exc
    return pts


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

    print(f"wrote {path} {Image.open(path).size}  "
          f"browser={'yes' if find_browser() else 'no (pillow fallback)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
