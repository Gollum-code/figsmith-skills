#!/usr/bin/env python3
"""icon_gen.py - parameterized icon generator.

Icons are geometry on a 2px grid. This script turns a small JSON spec into a clean
24x24 SVG: paths are snapped to the grid, strokes are uniform, and the output carries
nothing but geometry (no editor metadata, no inline style block).

Spec format:
    {"name": "arrow-right", "grid": 24, "stroke": 2,
     "strokes": [{"d": "M4 12 H20 M14 6 l6 6 -6 6"}],
     "fills":   [{"d": "M..."}],
     "circles": [{"cx": 12, "cy": 12, "r": 4, "fill": true}]}

Usage:
    python -m domains.icon-logo.scripts.icon_gen spec.json -o icon.svg [--color INK]

Colors come from the academic token set by default; --color takes an explicit hex only
because icons are single-color geometry, not styled figures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.tokens import load as load_tokens  # noqa: E402

SNAP = 2.0  # key coordinates sit on the 2px grid; half-pixels are what makes icons fuzzy

# Icons are single-color geometry, so the color comes from the token set's ink rather
# than a hardcoded hex. Switching style = switching the token name.
DEFAULT_COLOR = load_tokens("academic").c("colors.ink")


# A path `d` is interpolated into an SVG attribute, so it must be validated, not just
# snapped: a spec is untrusted input. The grammar is the SVG path command set plus
# numbers, whitespace and comma - nothing that can close the attribute or open a tag.
_PATH_D_RE = re.compile(
    r"^[MmLlHhVvCcSsQqTtAaZz0-9eE.,+\-\s]*$"
)


def validate_path_d(path_d: str) -> str:
    """Reject anything that is not SVG path grammar.

    This is the security boundary: `d` lands inside `d="..."`, so a quote or `<` would
    break out of the attribute. Non-path characters are rejected outright instead of
    escaped, because a path containing them is malformed anyway.
    """
    if not isinstance(path_d, str) or not _PATH_D_RE.fullmatch(path_d):
        raise ValueError(f"invalid SVG path data (non-path characters): {path_d[:60]!r}")
    return path_d


def _snap_numbers(path_d: str) -> str:
    """Snap standalone numbers in a path `d` to the grid.

    Only snaps integers that are likely coordinates - fractional values in arc commands
    are left alone. This is a helper, not a validator: the spec should already be
    grid-clean, this catches typos.
    """
    validate_path_d(path_d)

    def repl(m: re.Match) -> str:
        val = float(m.group(0))
        if val == int(val) and int(val) % SNAP == 0:
            return m.group(0)
        return str(round(val / SNAP) * int(SNAP))
    return re.sub(r"-?\d+\.?\d*", repl, path_d)


def render(spec: dict, color: str | None = None) -> str:
    grid = int(spec.get("grid", 24))
    stroke_w = int(spec.get("stroke", 2))
    if stroke_w not in (2, 3):
        raise ValueError(f"stroke must be 2 (24-grid) or 3 (48-grid), got {stroke_w}")
    if grid == 24 and stroke_w != 2:
        raise ValueError("24-grid icons use a 2px stroke (SKILL 2)")
    if grid == 48 and stroke_w != 3:
        raise ValueError("48-grid icons use a 3px stroke (SKILL 2)")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{grid}" height="{grid}" '
        f'viewBox="0 0 {grid} {grid}">',
    ]
    requested = color or DEFAULT_COLOR
    safe_color = requested if re.fullmatch(r"#[0-9A-Fa-f]{3,6}", requested) else DEFAULT_COLOR

    for stroke in spec.get("strokes", []):
        d = _snap_numbers(stroke["d"])
        parts.append(
            f'  <path d="{d}" fill="none" stroke="{safe_color}" stroke-width="{stroke_w}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    for fill in spec.get("fills", []):
        d = _snap_numbers(fill["d"])
        parts.append(f'  <path d="{d}" fill="{safe_color}"/>')
    for circle in spec.get("circles", []):
        cx = round(float(circle["cx"]) / SNAP) * int(SNAP)
        cy = round(float(circle["cy"]) / SNAP) * int(SNAP)
        r = float(circle["r"])
        if circle.get("fill"):
            parts.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{safe_color}"/>')
        else:
            parts.append(
                f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{safe_color}" '
                f'stroke-width="{stroke_w}"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


def check(spec: dict) -> list[str]:
    """Domain acceptance self-checks (SKILL 4)."""
    issues: list[str] = []
    grid = int(spec.get("grid", 24))
    for item in spec.get("strokes", []) + spec.get("fills", []):
        try:
            validate_path_d(item["d"])
        except ValueError as exc:
            # Malformed geometry is an error, not a warning: it cannot render.
            raise ValueError(f"{item.get('name', 'stroke')}: {exc}") from exc
        for num in re.findall(r"-?\d+\.?\d*", item["d"]):
            v = float(num)
            if v != int(v):
                continue
            if int(v) > grid:
                issues.append(f"coordinate {int(v)} outside the {grid} grid in d={item['d'][:40]}...")
    return issues


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Generate a grid-clean SVG icon from a spec.")
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--color", default=None, help="override ink color (hex); default from tokens")
    args = ap.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8-sig"))
    try:
        issues = check(spec)
        svg = render(spec, args.color)
    except ValueError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 1
    for issue in issues:
        print(f"warn: {issue}")
    out = args.out or str(Path(args.spec).with_suffix(".svg"))
    Path(out).write_text(svg, encoding="utf-8")
    print(f"wrote {out}" + (f" ({len(issues)} warnings)" if issues else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
