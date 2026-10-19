#!/usr/bin/env python3
"""figsmith tokens loader - the single entry point for semantic style tokens.

One rule: **no hex in code.** Colors, sizes and strokes always come from `t.<semantic path>`.
Switching style = switching the token name, not touching one line of render code.

Usage:
    from core.tokens import load
    t = load("academic")
    t.c("ink")            # -> "#1A1D21"
    t.s("stroke.thin")    # -> 1.2
    t.f("fonts.size_pt.tick_label")  # -> 8
    t.series(3)           # -> first three categorical colors
    t.text_width("CJK abc", 12)  # -> text width budget in px

Path resolution follows cross-file references, e.g. "palette.colors.sequential.blue".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

TOKENS_DIR = Path(__file__).resolve().parent
BUILTIN = ("academic", "web", "tech", "palette")

_CJK_RANGES = (
    (0x2E80, 0x9FFF),
    (0xAC00, 0xD7A3),
    (0xF900, 0xFAFF),
    (0xFE30, 0xFE4F),
    (0xFF00, 0xFFEF),
    (0x20000, 0x2FA1F),
)


def _dig(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


_FONT_CACHE: dict[str, Any] = {}
_FONT_DIRS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
    Path("C:/Windows/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/usr/share/fonts"),
]


def _find_font_file(family: str) -> Path | None:
    """Best-effort font file lookup for real metrics. Returns None when absent,
    in which case the width budget falls back to the CJK/latin estimate."""
    if family in _FONT_CACHE:
        return _FONT_CACHE[family]
    wanted = family.lower().replace(" ", "")
    candidates: list[Path] = []
    for base in _FONT_DIRS:
        if not base.exists():
            continue
        for pattern in (f"{family}.ttf", f"{family}.ttc", f"{family}.otf"):
            hit = base / pattern
            if hit.exists():
                candidates.append(hit)
        for hit in base.glob("*.tt*"):
            if wanted in hit.stem.lower().replace(" ", ""):
                candidates.append(hit)
    found = candidates[0] if candidates else None
    _FONT_CACHE[family] = found
    return found


def _font_metrics(path: Path) -> Any:
    key = str(path)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    try:
        from fontTools.ttLib import TTFont, TTCollection
        if path.suffix.lower() == ".ttc":
            fonts = TTCollection(str(path)).fonts
            font = fonts[0] if fonts else None
        else:
            font = TTFont(str(path), fontNumber=0)
        units_per_em = font["head"].unitsPerEm
        cmap = font.getBestCmap()
        hmtx = font["hmtx"]
        widths = {cp: hmtx[glyph][0] for cp, glyph in cmap.items()}
        _FONT_CACHE[key] = (units_per_em, widths)
        return _FONT_CACHE[key]
    except Exception:  # noqa: BLE001
        _FONT_CACHE[key] = None
        return None


def measure_text(text: str, size_px: float, family: str = "Arial") -> float | None:
    """Real advance width in px, or None when the font cannot be resolved.

    The width budget must match what the renderer produces; an estimate that is off by
    15% turns into either clipped labels or pointless wrapping.
    """
    path = _find_font_file(family)
    if path is None:
        return None
    metrics = _font_metrics(path)
    if metrics is None:
        return None
    units_per_em, widths = metrics
    total = 0.0
    for ch in text:
        if ch == " ":
            total += widths.get(0x20, units_per_em // 2)
            continue
        adv = widths.get(ord(ch))
        if adv is None:
            adv = units_per_em // 2
        total += adv
    return total * size_px / units_per_em


def _deepload(path: Path, cache: dict) -> dict:
    key = str(path.resolve())
    if key in cache:
        return cache[key]
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    cache[key] = data
    return data


class Tokens:
    """A resolved view of one token set. Cross-file references are resolved here."""

    def __init__(self, name: str, data: dict, cache: dict):
        self.name = name
        self._data = data
        self._cache = cache

    # ---------- lookups ----------

    def get(self, path: str, default: Any = None) -> Any:
        """Dot-path lookup. Supports cross-file references like "palette.colors.sequential.blue"."""
        return self._resolve(path, default, set())

    def _resolve(self, path: str, default: Any, seen: set) -> Any:
        head, _, rest = path.partition(".")
        if head in BUILTIN and head != self.name:
            other = _deepload(TOKENS_DIR / f"{head}.json", self._cache)
            return _dig(other, rest, default)
        val = _dig(self._data, path, None)
        if val is None:
            return default
        # A string value shaped like "<file>.<path>" pointing at another token file
        # is dereferenced automatically (one level only, cycle-safe).
        if isinstance(val, str) and "." in val:
            target_head = val.split(".")[0]
            if target_head in BUILTIN and target_head != self.name and val not in seen:
                seen.add(val)
                return self._resolve(val, default, seen)
        return val

    def c(self, path: str) -> str:
        """Fetch a color. Hard requirement: returns "#RRGGBB"."""
        val = self.get(path)
        if not isinstance(val, str) or not val.startswith("#"):
            raise KeyError(f"invalid color path or not a hex: {path}")
        return val

    def s(self, path: str, default: Any = None) -> Any:
        """Fetch a scalar (font size, stroke width, spacing)."""
        val = self.get(path, default)
        if val is None:
            raise KeyError(f"scalar path does not exist: {path}")
        return val

    def f(self, path: str) -> Any:
        return self.s(path)

    def font(self, role: str, kind: str = "latin") -> str:
        """Font name by role. kind = latin | cjk | mono."""
        stack = self.get(f"fonts.role.{role}")
        if not isinstance(stack, str):
            stack = "sans"
        return self.s(f"fonts.{stack}.{kind}", self.s(f"fonts.sans.{kind}"))

    def font_size(self, role: str) -> float:
        return self.s(f"fonts.size_pt.{role}")

    def series(self, n: int) -> list[str]:
        """First n categorical colors; cycles if n exceeds the palette."""
        pal = self.get("colors.categorical") or []
        if not pal:
            raise KeyError("token set lacks colors.categorical")
        out = []
        i = 0
        while len(out) < n:
            out.append(pal[i % len(pal)])
            i += 1
        return out

    def sequential(self, steps: int) -> list[str]:
        """Evenly pick n stops (including both ends) from the sequential ramp."""
        pal = self.get("colors.sequential")
        if isinstance(pal, list) and pal and isinstance(pal[0], str) and not pal[0].startswith("#"):
            pal = self.get(pal[0])
        if not isinstance(pal, list) or len(pal) < 2:
            raise KeyError("token set lacks a usable sequential ramp")
        if steps < 2:
            return [pal[0]]
        if steps >= len(pal):
            return list(pal)
        idx = [round(i * (len(pal) - 1) / (steps - 1)) for i in range(steps)]
        return [pal[i] for i in idx]

    # ---------- derived ----------

    def text_width(self, text: str, size_px: float, family: str | None = None) -> float:
        """Text width budget: CJK*1.0 + latin*0.55. Keep >=10px from the container edge;
        when it overflows, wrap the line instead of shrinking the font.

        Real font metrics are used when the font file is resolvable, because the
        estimate drifts enough to cause clipped labels or pointless wrapping. The
        estimate is the documented fallback.
        """
        if family is None:
            family = self.font("panel_label", "latin")
        measured = measure_text(text, size_px, family)
        if measured is not None:
            return measured
        cjk = sum(1 for ch in text if _is_cjk(ch))
        latin = len(text) - cjk
        return cjk * 1.0 * size_px + latin * 0.55 * size_px

    def pt_to_px(self, pt: float, dpi: int | None = None) -> float:
        dpi = dpi or int(self.get("export.target_dpi", 600))
        return pt * dpi / 72.0

    # ---------- export ----------

    def dump(self) -> dict:
        return json.loads(json.dumps(self._data))

    def __repr__(self) -> str:
        return f"<Tokens {self.name} v{self.get('version', '?')}>"


def load(name: str = "academic") -> Tokens:
    if name not in BUILTIN:
        raise ValueError(f"unknown token set: {name}. available: {', '.join(BUILTIN)}")
    cache: dict = {}
    return Tokens(name, _deepload(TOKENS_DIR / f"{name}.json", cache), cache)


def available() -> list[str]:
    return sorted(p.stem for p in TOKENS_DIR.glob("*.json") if not p.name.startswith("_"))


# ---------- consistency check ----------

REQUIRED_COLORS = (
    "colors.ink", "colors.ink_secondary", "colors.surface", "colors.surface_alt",
    "colors.surface_band", "colors.border", "colors.axis", "colors.grid",
)
REQUIRED_RAMPS = ("colors.categorical", "colors.accent")
REQUIRED_SCALARS = (
    "stroke.thin", "stroke.medium", "stroke.arrow", "grid.unit", "canvas.margin",
    "fonts.size_pt.figure_title", "fonts.size_pt.tick_label", "fonts.size_pt.min_readable",
)
# A renderable token set has fonts and ink; palette.json is a ramp dependency only.
def _is_renderable(data: dict) -> bool:
    return bool(_dig(data, "fonts.role")) or bool(_dig(data, "colors.ink"))


def _font_chain_ok(t: "Tokens", stack: str, kind: str) -> tuple[bool, str]:
    """True if any font in {primary, fallback} resolves on this host."""
    primary = t.get(f"fonts.{stack}.{kind}")
    fallback = t.get(f"fonts.{stack}.{kind}_fallback")
    names = [n for n in (primary, fallback) if n]
    if not names:
        return True, ""
    if any(_find_font_file(n) for n in names):
        return True, ""
    return False, f"font stack fonts.{stack}.{kind} resolves to no file (tried {names})"


def check(name: str) -> tuple[list[str], list[str]]:
    """Report what would break rendering for this token set.

    Returns (problems, warnings). Problems are structural and host-independent, so they
    fail CI: a color/scalar path that does not resolve, a missing ramp, a non-hex entry.
    Warnings are advisory and host-dependent, so they never fail CI: a categorical color
    that grays too close to the surface (a design judgment), or a font fallback chain
    with no file on *this* host (CI runners and designer boxes differ).
    """
    problems: list[str] = []
    warnings: list[str] = []
    try:
        t = load(name)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return [f"token set {name!r} failed to load: {exc}"], []

    if not _is_renderable(t.dump()):
        return problems, warnings  # palette.json and friends: dependency files

    for path in REQUIRED_COLORS:
        try:
            t.c(path)
        except KeyError:
            problems.append(f"{name}: color path {path} does not resolve")
    for path in REQUIRED_SCALARS:
        try:
            t.s(path)
        except KeyError:
            problems.append(f"{name}: scalar path {path} does not resolve")

    surface = t.get("colors.surface")
    for path in REQUIRED_RAMPS:
        ramp = t.get(path)
        if not isinstance(ramp, list) or not ramp:
            problems.append(f"{name}: ramp {path} is missing or empty")
            continue
        for col in ramp:
            if not isinstance(col, str) or not col.startswith("#"):
                problems.append(f"{name}: ramp {path} has a non-hex entry {col!r}")
            elif surface and gray_delta(col, surface) < 40:
                warnings.append(
                    f"{name}: {path} color {col} clears only "
                    f"{gray_delta(col, surface):.1f} against surface (min 40)"
                )

    for stack in ("sans", "serif", "mono"):
        for kind in ("latin", "cjk"):
            if not t.get(f"fonts.{stack}.{kind}"):
                continue
            ok, msg = _font_chain_ok(t, stack, kind)
            if not ok:
                warnings.append(f"{name}: {msg} (host-specific)")
    return problems, warnings


def check_all() -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    for name in available():
        p, w = check(name)
        problems.extend(p)
        warnings.extend(w)
    return problems, warnings


def hex_to_gray(hex_color: str) -> float:
    """Perceived luminance 0-255. The gray-difference >=40 rule uses this
    (see core/verify/check_contrast.py)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def gray_delta(hex_a: str, hex_b: str) -> float:
    """Perceived gray difference between two colors. Body vs grid must clear 40."""
    return abs(hex_to_gray(hex_a) - hex_to_gray(hex_b))


__all__ = ["Tokens", "load", "available", "check", "check_all",
           "hex_to_gray", "gray_delta"]


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Token-set consistency check.")
    ap.add_argument("--check", action="store_true", help="check every token set")
    ap.add_argument("--set", dest="token_set", default=None, help="check one set only")
    args = ap.parse_args(argv)

    targets = [args.token_set] if args.token_set else available()
    problems: list[str] = []
    warnings: list[str] = []
    for name in targets:
        p, w = check(name)
        problems.extend(p)
        warnings.extend(w)

    for w in warnings:
        print(f"[warn] {w}")
    for p in problems:
        print(f"[FAIL] {p}")
    if problems:
        print(f"\n{len(problems)} problem(s), {len(warnings)} warning(s) "
              f"across {len(targets)} token set(s)")
        return 1
    print(f"ok: {len(targets)} token set(s) consistent, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
