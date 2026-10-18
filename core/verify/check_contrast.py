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
    """Separate foreground from background by luminance histogram, then report the gap.

    The meaningful check for "text on grid" is whether the *ink* sits far enough from
    the surface it is drawn on. We take the extreme percentile tones rather than the
    histogram mode: thin text and hairlines occupy few pixels and get buried by the
    dominant background, so the mode would report a huge delta for an unreadable figure.
    p99.5 of the dark side vs p99.5 of the light side is what the eye actually compares.
    """
    flat = gray.ravel()
    light_center = float(np.percentile(flat, 99.5))
    dark_center = float(np.percentile(flat, 0.5))
    return {
        "background_tone": round(light_center, 1),
        "foreground_tone": round(dark_center, 1),
        "delta": round(light_center - dark_center, 1),
        "ink_share": round(float((flat < light_center - 20).mean()), 4),
    }


def check(path: str | Path, min_delta: float = DEFAULT_MIN_DELTA) -> dict:
    gray = load_gray(path)
    stats = local_contrast_stats(gray)
    tones = foreground_background_delta(gray)

    # The binding requirement is the tone separation: ink vs the surface it sits on.
    # Peak local contrast alone would pass any image containing one dark speck.
    passed = tones["delta"] >= min_delta
    return {
        "file": str(path),
        "size": list(gray.shape),
        "min_delta_required": min_delta,
        "tone_separation": tones,
        "local_contrast": {k: round(v, 1) for k, v in stats.items()},
        "passed": bool(passed),
        "reason": (
            "ok"
            if passed
            else f"ink-to-surface delta {tones['delta']} < {min_delta}"
        ),
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
