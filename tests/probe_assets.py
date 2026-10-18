#!/usr/bin/env python3
"""Regenerate the vision probe assets under docs/probe/.

Run this after any model upgrade: the probe report (docs/vision-probe-report.md)
records the measured capability boundary, and that boundary can move.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "docs" / "probe"
BOLD = "C:/Windows/Fonts/arialbd.ttf"
REG = "C:/Windows/Fonts/arial.ttf"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _txt(draw: ImageDraw.ImageDraw, xy, text: str, size: int, fill=20, bold: bool = False) -> None:
    draw.text(xy, text, font=_font(BOLD if bold else REG, size), fill=fill)


def t1_basic() -> None:
    img = Image.new("RGB", (800, 300), "white")
    d = ImageDraw.Draw(img)
    _txt(d, (40, 30), "Figure 1. Baseline recognition test", 34, bold=True)
    for i, point in enumerate([
        "Point A: three boxes left to right",
        "Point B: one arrow between each pair",
        "Point C: footer note bottom left",
        "Point D: legend top right corner",
        "Point E: blue accent on second box",
    ]):
        _txt(d, (40, 100 + i * 36), point, 20)
    d.rectangle([620, 90, 750, 140], fill="#0072B2")
    img.save(OUT / "t1_basic.png")


def _dense(w: int) -> Image.Image:
    img = Image.new("RGB", (w, int(w * 0.5)), "white")
    d = ImageDraw.Draw(img)
    _txt(d, (w // 2 - 260, 20), "Density Test - 45 nodes", min(28, w // 40), bold=True)
    cols, rows = 9, 5
    bw = (w - 80 - (cols - 1) * 10) // cols
    bh = int(w * 0.5) // (rows + 2) - 10
    for r in range(rows):
        for c in range(cols):
            x = 40 + c * (bw + 10)
            y = 60 + r * (bh + 10)
            d.rectangle([x, y, x + bw, y + bh], outline=(90, 90, 90), width=1)
            _txt(d, (x + 6, y + 6), f"N{r * cols + c + 1}", max(10, bw // 8))
    _txt(d, (40, int(w * 0.5) - 30), f"canvas {w}px wide", 16)
    return img


def t2_dense() -> None:
    for w in (800, 1600, 2400, 4000):
        _dense(w).save(OUT / f"t2_dense_{w}.png")


def _tall(h: int) -> Image.Image:
    img = Image.new("RGB", (1400, h), "white")
    d = ImageDraw.Draw(img)
    _txt(d, (40, 20), f"Tall figure - {h}px", 30, bold=True)
    y, i = 80, 1
    while y < h - 60:
        d.rectangle([60, y, 1340, y + 50], outline=(70, 70, 70), width=1)
        _txt(d, (70, y + 12), f"row {i} - horizontal band content", 18)
        y += 70
        i += 1
    return img


def t3_tall() -> None:
    for h in (2000, 4000, 8000):
        _tall(h).save(OUT / f"t3_tall_{h}.png")


def t4_small_hairline() -> None:
    img = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(img)
    _txt(d, (40, 20), "Small text and hairline test", 26, bold=True)
    y = 80
    for size in (8, 10, 12, 14, 16):
        _txt(d, (60, y), f"{size}px: The quick brown fox jumps over the lazy dog 0123456789", size)
        y += 34
    y = 280
    for lw in (0.5, 0.8, 1.2, 1.7, 2.2):
        d.line([60, y, 840, y], fill=(60, 60, 60), width=int(lw * 4))
        _txt(d, (60, y - 4), f"{lw}px line", 10)
        y += 40
    img.save(OUT / "t4_small_hairline_2x.png")
    img.resize((450, 300), Image.LANCZOS).save(OUT / "t4_small_hairline.png")


def t5_multipage() -> None:
    pages = [_dense(1400).convert("RGB") for _ in range(3)]
    pages[0].save(
        OUT / "t5_multipage.pdf",
        save_all=True,
        append_images=pages[1:],
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t1_basic()
    t2_dense()
    t3_tall()
    t4_small_hairline()
    t5_multipage()
    print(f"probe assets written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
