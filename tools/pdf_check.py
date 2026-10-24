#!/usr/bin/env python3
"""tools/pdf_check.py - structural acceptance for a PDF deliverable.

The layout routes (deck-slides / poster-flyer / infographic) ship PDFs, and the two
defects that matter are invisible in a raster proxy: a page that spilled onto a second
sheet, and text that silently became an image. This checks both, plus the vector verdict
that tools/four_way_check.py already uses.

Usage:
    python tools/pdf_check.py <file.pdf> [--expect-pages 1] [--json]

Exit code 0 = pass, 1 = fail.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _page_count(data: bytes) -> int:
    """Count page objects. `/Type /Pages` is the tree node, so it is excluded."""
    pages = len(re.findall(rb"/Type\s*/Page\b(?!s)", data))
    if pages:
        return pages
    # A compressed object stream hides the page dictionaries; the page tree still states
    # the count in that case.
    counts = [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)", data)]
    return max(counts) if counts else 0


def _page_size(data: bytes) -> tuple[float, float] | None:
    m = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    if not m:
        return None
    x0, y0, x1, y1 = (float(v) for v in m.groups())
    return (abs(x1 - x0), abs(y1 - y0))


def _text_ops(data: bytes) -> int:
    """Number of text-showing operators anywhere in the file.

    Both raw and Flate-compressed streams are scanned; reportlab compresses by default,
    so a raw-only scan reports zero text for a perfectly good vector PDF.
    """
    import zlib

    total = data.count(b"Tj") + data.count(b"TJ")
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            dec = zlib.decompress(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        total += dec.count(b"Tj") + dec.count(b"TJ")
    return total


def check(path: str | Path, expect_pages: int | None = None) -> dict:
    from tools.four_way_check import _pdf_is_vector

    p = Path(path)
    if not p.exists():
        return {"file": str(p), "passed": False, "reason": "file not found"}
    data = p.read_bytes()
    pages = _page_count(data)
    size = _page_size(data)
    text_ops = _text_ops(data)
    vector = _pdf_is_vector(p)

    problems = []
    if pages == 0:
        problems.append("no page objects found")
    if expect_pages is not None and pages != expect_pages:
        problems.append(f"{pages} page(s), expected {expect_pages}")
    if text_ops == 0:
        problems.append("no text operators; the text is an image, not vector")
    if not vector:
        problems.append("not a vector PDF (page-sized raster or no drawing operators)")

    return {
        "file": str(p),
        "pages": pages,
        "expected_pages": expect_pages,
        "page_size_pt": list(size) if size else None,
        "text_ops": text_ops,
        "vector": vector,
        "passed": not problems,
        "reason": "ok" if not problems else "; ".join(problems),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Structural acceptance for a PDF.")
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--expect-pages", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = [check(p, args.expect_pages) for p in args.pdfs]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"[{mark}] {r['file']}  pages={r.get('pages')} "
                  f"text_ops={r.get('text_ops')} vector={r.get('vector')}  {r['reason']}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
