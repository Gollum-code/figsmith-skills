#!/usr/bin/env python3
"""check_tiling.py - detect the silent "fullPage screenshot stitched into copies" failure.

The trap: screenshotting a page taller than the viewport with fullPage=true can
silently produce a stitched image where content repeats. File size looks plausible.
Only pixel evidence catches it.

How this catches it: a stitched screenshot repeats *blocks* - a whole region appears
verbatim further down. Evenly spaced rules are NOT a failure (grids are legitimate),
so global autocorrelation is the wrong tool. Instead we compare block-to-block
similarity: split the image into horizontal bands, hash each band's downsampled
luminance, and look for near-identical non-adjacent bands.

Usage:
    python -m core.verify.check_tiling <image.png> [...] [--json] [--similarity 0.98]

Exit code 0 = pass, 1 = fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

DEFAULT_SIMILARITY = 0.98  # mean abs difference below this = duplicate block
BANDS = 8  # compare in 8 horizontal bands
MIN_INK = 0.02  # a band with less ink than this carries no structure to compare


def load_gray(path: str | Path) -> np.ndarray:
    img = Image.open(path)
    if img.mode != "L":
        img = img.convert("L")
    return np.asarray(img).astype(np.float64) / 255.0


def band_signatures(gray: np.ndarray, bands: int = BANDS) -> list[np.ndarray]:
    """Structural fingerprint of each horizontal band.

    Plain area-downsampling collapses to near-identical vectors on sparse figures
    (white space plus a few rules), which false-positives on every clean layout.
    The fingerprint therefore keeps the *structure*: horizontal and vertical gradient
    magnitudes downsampled to 16x16, plus the ink coverage ratio. Two bands match only
    when their edges and density match, which is what a verbatim copy looks like.
    """
    h, w = gray.shape
    step = max(1, h // bands)
    sigs = []
    for i in range(bands):
        block = gray[i * step : min((i + 1) * step, h)]
        if block.size == 0:
            sigs.append(np.zeros(16 * 16 + 1))
            continue
        gy = np.abs(np.diff(block, axis=0, prepend=block[:1])).mean(axis=1)
        gx = np.abs(np.diff(block, axis=1, prepend=block[:, :1])).mean(axis=0)
        gy_small = _resample_1d(gy, 16)
        gx_small = _resample_1d(gx, 16)
        ink = float((block < 0.85).mean())
        sigs.append(np.concatenate([gy_small, gx_small, [ink]]))
    return sigs


def _resample_1d(vec: np.ndarray, n: int) -> np.ndarray:
    """Area-average a 1-D signal down to n samples."""
    if len(vec) < n:
        vec = np.pad(vec, (0, n - len(vec)))
    edges = np.linspace(0, len(vec), n + 1).astype(int)
    out = np.zeros(n)
    for i in range(n):
        seg = vec[edges[i] : edges[i + 1]]
        out[i] = seg.mean() if seg.size else 0.0
    return out


def check(path: str | Path, similarity: float = DEFAULT_SIMILARITY) -> dict:
    gray = load_gray(path)
    h, w = gray.shape
    if h < 64:
        return {
            "file": str(path), "size": [h, w], "duplicate_bands": [],
            "passed": True, "reason": "image too short for tiling analysis",
        }

    sigs = band_signatures(gray)
    duplicates: list[dict] = []
    for i in range(len(sigs)):
        for j in range(i + 2, len(sigs)):  # skip adjacent bands (real content continues)
            a, b = sigs[i], sigs[j]
            # Two empty bands are not a duplicate; require both to carry real structure.
            ink_a, ink_b = a[-1], b[-1]
            if ink_a < MIN_INK or ink_b < MIN_INK:
                continue
            scale = max(a[:-1].max(), b[:-1].max(), 1e-6)
            mad = float(np.abs(a[:-1] - b[:-1]).mean() / scale)
            similarity_score = 1.0 - mad
            if similarity_score >= similarity:
                duplicates.append({
                    "bands": [i, j],
                    "similarity": round(similarity_score, 4),
                })

    return {
        "file": str(path),
        "size": [h, w],
        "bands": len(sigs),
        "threshold": similarity,
        "duplicate_bands": duplicates,
        "passed": not duplicates,
        "reason": ("ok" if not duplicates else
                   f"{len(duplicates)} duplicate band pair(s): " +
                   ", ".join(f"{d['bands']}@{d['similarity']:.3f}" for d in duplicates)),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Tiling / repeat detection for screenshots.")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--similarity", type=float, default=DEFAULT_SIMILARITY,
                    help="band similarity threshold (default 0.98)")
    args = ap.parse_args(argv)

    results = [check(p, args.similarity) for p in args.images]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"[{mark}] {r['file']} {r['size'][1]}x{r['size'][0]}  {r['reason']}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
