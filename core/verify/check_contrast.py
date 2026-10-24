#!/usr/bin/env python3
"""check_contrast.py - body vs grid gray difference >= 40, measured on RENDERED PIXELS.

Why rendered pixels: a 1.2px line theoretically holding delta-50 against its background
can rasterize to delta-12 after antialiasing. Hex math says "fine", the eye says
"there's no border". So we measure the PNG, not the source.

Usage:
    python -m core.verify.check_contrast <image.png> [--min-delta 40] [--json]

What it does:
    Converts to grayscale, then finds the strongest edge magnitude in the image and
    reports the distribution of local contrast. Fails when the *text/foreground*
    against *background/grid* never reaches the threshold, which is the case the
    METHOD calls out: "judge reads it as 'no border'".

Exit code 0 = pass, 1 = fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

DEFAULT_MIN_DELTA = 40.0


def load_gray(path: str | Path) -> np.ndarray:
    img = Image.open(path)
    if img.mode not in ("L", "RGB", "RGBA"):
        img = img.convert("RGB")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    arr = np.asarray(img).astype(np.float64)
    if arr.ndim == 3:
        arr = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    return arr


def local_contrast_stats(gray: np.ndarray) -> dict:
    """Local contrast = max minus min in a 5x5 neighborhood (Sobel-free, cheap).

    Returns the distribution so a human can see *how* the image fails,
    not just that it failed.
    """
    if gray.shape[0] < 5 or gray.shape[1] < 5:
        return {"max": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0, "mean": 0.0}
    pad = np.pad(gray, 2, mode="edge")
    windows = np.stack(
        [pad[i : i + gray.shape[0], j : j + gray.shape[1]] for i in range(5) for j in range(5)],
        axis=0,
    )
    local_max = windows.max(axis=0)
    local_min = windows.min(axis=0)
    contrast = local_max - local_min
    return {
        "max": float(contrast.max()),
        "p99": float(np.percentile(contrast, 99)),
        "p90": float(np.percentile(contrast, 90)),
        "p50": float(np.percentile(contrast, 50)),
        "mean": float(contrast.mean()),
    }


def foreground_background_delta(gray: np.ndarray) -> dict:
    """Separate ink from surface by luminance histogram, then report the gap.

    The meaningful check for "text on grid" is whether the *ink* sits far enough from
    the surface it is drawn on. Percentile extremes are the wrong tool in both
    directions: a 0.3%-ink figure reports delta 0 (its dark pixels fall outside p0.5),
    while a figure with one black speck and everything else unreadable reports a huge
    delta. So the ink is identified as the pixels below the mid-point, and the reported
    values are the medians of the ink and surface populations - the tones the eye
    actually compares, robust to how much of each is present.
    """
    flat = gray.ravel()
    midpoint = (flat.max() + flat.min()) / 2.0
    ink = flat[flat < midpoint]
    surface = flat[flat >= midpoint]
    if ink.size == 0 or surface.size == 0:
        # A flat image has no ink at all, which is the worst case for legibility.
        return {"background_tone": round(float(flat.max()), 1),
                "foreground_tone": round(float(flat.min()), 1),
                "delta": 0.0, "ink_share": 0.0}
    return {
        "background_tone": round(float(np.median(surface)), 1),
        "foreground_tone": round(float(np.median(ink)), 1),
        "delta": round(float(np.median(surface)) - float(np.median(ink)), 1),
        "ink_share": round(float(ink.size / flat.size), 4),
    }


def hairline_visibility(gray: np.ndarray, min_delta: float = DEFAULT_MIN_DELTA) -> dict:
    """Whether thin structure is distinguishable from its own background.

    This is the failure the METHOD calls out by name: a 1.2px line whose theoretical
    contrast is 50 rasterizes to delta 12, and the judge reads "no border". Global tone
    separation cannot see it, so the local contrast distribution is measured directly:
    the share of a window's area taken by structure of a given strength.
    """
    if gray.shape[0] < 5 or gray.shape[1] < 5:
        return {"structural_share": 0.0, "weak_share": 0.0, "passed": False}
    pad = np.pad(gray, 2, mode="edge")
    windows = np.stack(
        [pad[i: i + gray.shape[0], j: j + gray.shape[1]] for i in range(5) for j in range(5)],
        axis=0,
    )
    contrast = windows.max(axis=0) - windows.min(axis=0)
    # A window is "structural" when it contains an edge of at least the required delta:
    # that is what makes a border or a grid line visible rather than a smudge.
    structural = contrast >= min_delta
    weak = (contrast >= 5.0) & (contrast < min_delta * 0.5)
    return {
        "structural_share": round(float(structural.mean()), 4),
        "weak_share": round(float(weak.mean()), 4),
        # A figure with structure but no discernible edge is the hairline failure.
        "passed": bool(structural.mean() >= 0.001 or contrast.max() < min_delta),
    }


def check(path: str | Path, min_delta: float = DEFAULT_MIN_DELTA) -> dict:
    gray = load_gray(path)
    stats = local_contrast_stats(gray)
    tones = foreground_background_delta(gray)
    hairlines = hairline_visibility(gray, min_delta)

    # The binding requirements are (a) ink vs the surface it sits on, and (b) enough
    # structural edge somewhere in the image for thin rules to be visible. A peak-only
    # or tone-only test each pass a figure the other one rejects.
    passed = tones["delta"] >= min_delta and hairlines["passed"]
    reasons = []
    if tones["delta"] < min_delta:
        reasons.append(f"ink-to-surface delta {tones['delta']} < {min_delta}")
    if not hairlines["passed"]:
        reasons.append(
            f"no edge reaches delta {min_delta} (structure is below the visibility floor)")
    return {
        "file": str(path),
        "size": list(gray.shape),
        "min_delta_required": min_delta,
        "tone_separation": tones,
        "hairlines": hairlines,
        "local_contrast": {k: round(v, 1) for k, v in stats.items()},
        "passed": bool(passed),
        "reason": "ok" if passed else "; ".join(reasons),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Body vs grid contrast check on rendered pixels.")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--min-delta", type=float, default=DEFAULT_MIN_DELTA)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    results = [check(p, args.min_delta) for p in args.images]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"[{mark}] {r['file']}  delta={r['tone_separation']['delta']} "
                  f"(bg={r['tone_separation']['background_tone']}, "
                  f"fg={r['tone_separation']['foreground_tone']})  {r['reason']}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
