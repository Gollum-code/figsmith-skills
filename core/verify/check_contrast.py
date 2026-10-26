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


def _window_max(a: np.ndarray, radius: int, axis: int) -> np.ndarray:
    """1-D sliding max along one axis. All shifts read the input of this pass."""
    out = a.copy()
    for k in range(1, radius + 1):
        if axis == 0:
            np.maximum(out[k:], a[:-k], out=out[k:])
            np.maximum(out[:-k], a[k:], out=out[:-k])
        else:
            np.maximum(out[:, k:], a[:, :-k], out=out[:, k:])
            np.maximum(out[:, :-k], a[:, k:], out=out[:, :-k])
    return out


def _window_min(a: np.ndarray, radius: int, axis: int) -> np.ndarray:
    out = a.copy()
    for k in range(1, radius + 1):
        if axis == 0:
            np.minimum(out[k:], a[:-k], out=out[k:])
            np.minimum(out[:-k], a[k:], out=out[:-k])
        else:
            np.minimum(out[:, k:], a[:, :-k], out=out[:, k:])
            np.minimum(out[:, :-k], a[:, k:], out=out[:, :-k])
    return out


def _local_contrast(gray: np.ndarray, radius: int = 2) -> np.ndarray:
    """Per-pixel max-minus-min over a (2r+1) neighborhood.

    Separable max/min filters instead of stacking 25 shifted copies: the stack version
    allocated 25 * H * W * 8 bytes, which is 3.2 GB for the 4000px figure the probe report
    calls the readable ceiling. Two passes per axis keep the peak at a few frames.

    The columns pass must run on the row pass's *result* - running both against the
    original array yields a 1-D max, not a square window.
    """
    if gray.shape[0] < 2 * radius + 1 or gray.shape[1] < 2 * radius + 1:
        return np.zeros_like(gray)
    hi = _window_max(_window_max(gray, radius, 0), radius, 1)
    lo = _window_min(_window_min(gray, radius, 0), radius, 1)
    return hi - lo


def local_contrast_stats(gray: np.ndarray) -> dict:
    """Distribution of local contrast, so a failure shows *how* the image fails."""
    contrast = _local_contrast(gray)
    if contrast.size == 0:
        return {"max": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0, "mean": 0.0}
    return {
        "max": float(contrast.max()),
        "p99": float(np.percentile(contrast, 99)),
        "p90": float(np.percentile(contrast, 90)),
        "p50": float(np.percentile(contrast, 50)),
        "mean": float(contrast.mean()),
    }


def foreground_background_delta(gray: np.ndarray) -> dict:
    """Contrast of drawn structure against the surface immediately around it.

    A single global background tone does not exist in a real figure: a band fill, a card
    and the page are three different surfaces, and picking the histogram mode measured
    the band against the page (delta 9 on a perfectly readable figure). Local contrast
    sidesteps that: every pixel is compared with its own neighbourhood, so text on a band
    and text on paper are measured the same way.

    `delta` is the median local contrast of edge-bearing pixels - the typical gap the eye
    sees between a stroke and what is behind it. A figure whose only structure rasterized
    below the floor has no such pixels and reports 0.
    """
    local = _local_contrast(gray)
    flat = local.ravel()
    edge = flat[flat >= 3.0]
    share = float(edge.size / flat.size) if flat.size else 0.0
    if edge.size == 0 or share < 0.0005:
        return {"surface_tone": round(float(np.median(gray.ravel())), 1),
                "delta": 0.0, "ink_share": round(share, 4)}
    return {
        # Median tone of the non-edge area, for the human reading the report.
        "surface_tone": round(float(np.median(gray.ravel()[local.ravel() < 3.0])), 1)
        if (local < 3.0).any() else 0.0,
        "delta": round(float(np.median(edge)), 1),
        "ink_share": round(share, 4),
    }


def hairline_visibility(gray: np.ndarray, min_delta: float = DEFAULT_MIN_DELTA) -> dict:
    """Whether thin structure is distinguishable from its own background.

    The local-contrast distribution is measured directly: a window is "structural" when
    it contains an edge at least `min_delta` strong, which is what makes a border or a
    grid line visible rather than a smudge. `weak_share` is the population that has an
    edge but one too faint to read, which is the hairline-rasterized-away signature.
    """
    contrast = _local_contrast(gray)
    if contrast.size == 0:
        return {"structural_share": 0.0, "weak_share": 0.0, "passed": False}
    structural = contrast >= min_delta
    weak = (contrast >= 5.0) & (contrast < min_delta * 0.5)
    return {
        "structural_share": round(float(structural.mean()), 4),
        "weak_share": round(float(weak.mean()), 4),
        # A flat image has no structure to be invisible in the first place; the tone check
        # is what rejects it.
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
            print(f"[{mark}] {r['file']}  structure delta={r['tone_separation']['delta']} "
                  f"(surface={r['tone_separation']['surface_tone']}, "
                  f"ink_share={r['tone_separation']['ink_share']})  {r['reason']}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
