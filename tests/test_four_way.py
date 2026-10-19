#!/usr/bin/env python3
"""tests/test_four_way.py - regression tests for the four-way acceptance checker.

These cover the checks that decide whether a deliverable is acceptable, so a bug here
means a broken figure would be shipped as "verified".

Run: python tests/test_four_way.py
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.gettempdir())
FAILURES: list[str] = []
TESTS: list = []

from tools.four_way_check import _pdf_is_vector  # noqa: E402


def case(name: str):
    def deco(fn):
        def wrapper():
            try:
                fn()
                print(f"[PASS] {name}")
            except AssertionError as exc:
                FAILURES.append(f"{name}: {exc}")
                print(f"[FAIL] {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                FAILURES.append(f"{name}: unexpected {type(exc).__name__}: {exc}")
                print(f"[FAIL] {name}: unexpected {type(exc).__name__}: {exc}")
        TESTS.append(wrapper)
        return wrapper
    return deco


def _logo_image(size: int = 120):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), "white")
    ImageDraw.Draw(img).rectangle([10, 10, size - 20, size - 20], fill="black")
    return img


@case("pdf: a page-sized raster is rejected")
def _raster_rejected():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1200, 1600), "white")
    ImageDraw.Draw(img).rectangle([100, 100, 1100, 400], fill="black")
    buf = io.BytesIO()
    img.save(buf, "PDF")
    p = TMP / "t4w_raster.pdf"
    p.write_bytes(buf.getvalue())
    assert _pdf_is_vector(p) is False, "a full-page raster was accepted as vector"


@case("pdf: a small logo alongside vector content is accepted")
def _logo_allowed():
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    _logo_image().save(buf, "PNG")
    buf.seek(0)
    p = TMP / "t4w_logo.pdf"
    c = canvas.Canvas(str(p), pagesize=(400, 300))
    c.setFont("Helvetica", 14)
    c.drawString(60, 260, "Figure with a logo")
    c.drawImage(ImageReader(buf), 20, 20, 60, 60)
    c.rect(150, 40, 200, 120, stroke=1, fill=0)
    c.save()
    assert _pdf_is_vector(p) is True, "a small logo made a vector PDF look like a raster"


@case("pdf: a file that is not a PDF is rejected")
def _not_a_pdf():
    p = TMP / "t4w_bad.pdf"
    p.write_bytes(b"not a pdf at all")
    assert _pdf_is_vector(p) is False, "a non-PDF was accepted"


@case("browser: --no-sandbox is only used when required")
def _sandbox_flags():
    import os

    from backends.png import sandbox_flags

    saved = os.environ.pop("FIGSMITH_NO_SANDBOX", None)
    try:
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        expected = ["--no-sandbox"] if is_root else []
        assert sandbox_flags() == expected, f"got {sandbox_flags()}, expected {expected}"

        os.environ["FIGSMITH_NO_SANDBOX"] = "1"
        assert sandbox_flags() == ["--no-sandbox"], "the env override did not force the flag"
    finally:
        os.environ.pop("FIGSMITH_NO_SANDBOX", None)
        if saved is not None:
            os.environ["FIGSMITH_NO_SANDBOX"] = saved


@case("browser: no code path hardcodes --no-sandbox")
def _no_hardcoded_sandbox():
    import re

    offenders = []
    for path in (ROOT / "backends").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'"--no-sandbox"', text):
            line = text[:m.start()].count("\n") + 1
            ctx = text.splitlines()[line - 1]
            if "sandbox_flags" not in ctx and "*sandbox_flags()" not in text:
                offenders.append(f"{path.name}:{line}")
    for path in (ROOT / "tools").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if '"--no-sandbox"' in text and "*sandbox_flags()" not in text:
            offenders.append(path.name)
    assert not offenders, f"hardcoded --no-sandbox in {offenders}"


if __name__ == "__main__":
    print()
    for test in TESTS:
        test()
    print(f"\n{len(TESTS) - len(FAILURES)}/{len(TESTS)} passed, {len(FAILURES)} failure(s)")
    raise SystemExit(1 if FAILURES else 0)
