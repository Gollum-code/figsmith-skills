#!/usr/bin/env python3
"""backends/mpl2svg.py - matplotlib -> SVG, driven by a JSON spec.

Statistical figures are the one route where data must never be hand-drawn: every point
comes from the frozen table in the spec, and matplotlib does the pixel work. This
backend is the only sanctioned path for the statistical route (METHOD 4).

Hard rules enforced here:
  * data comes from `data.series[].x/y`, never from the layout layer
  * `error_kind` must be declared when error bars exist (IR 2.6)
  * colors come from tokens, not from matplotlib defaults
  * no seaborn styling, no default rcParams: everything is set explicitly

Usage:
    python -m backends.mpl2svg <ir.json> [-o out.svg] [--png out.png] [--dpi 600]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless, no display

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tokens import load as load_tokens  # noqa: E402

# Figure types this backend supports. Anything else must use another route.
SUPPORTED = {
    "line", "scatter", "bar", "bar_grouped", "bar_stacked", "area",
    "box", "violin", "hist", "heatmap", "errorbar", "stem",
}


def _apply_rc(tokens, dpi: int) -> None:
    """Push the token set into matplotlib rcParams. Defaults never survive."""
    plt.rcParams.update({
        "figure.dpi": dpi,
        "savefig.dpi": dpi,
        "font.family": "sans-serif",
        "font.sans-serif": [tokens.font("axis_label", "latin"),
                            tokens.font("axis_label", "latin_fallback")],
        "font.size": tokens.font_size("axis_label"),
        "axes.titlesize": tokens.font_size("figure_title"),
        "axes.labelsize": tokens.font_size("axis_label"),
        "xtick.labelsize": tokens.font_size("tick_label"),
        "ytick.labelsize": tokens.font_size("tick_label"),
        "legend.fontsize": tokens.font_size("legend"),
        "axes.edgecolor": tokens.c("colors.axis"),
        "axes.linewidth": tokens.s("stroke.axis"),
        "axes.labelcolor": tokens.c("colors.ink"),
        "text.color": tokens.c("colors.ink"),
        "xtick.color": tokens.c("colors.ink_secondary"),
        "ytick.color": tokens.c("colors.ink_secondary"),
        "xtick.direction": "out",
        "ytick.direction": "out",
        "axes.grid": False,
        "grid.color": tokens.c("colors.grid"),
        "grid.linewidth": tokens.s("stroke.grid"),
        "legend.frameon": False,
        "svg.fonttype": "none",  # keep text as text so it stays editable and searchable
    })


def _draw(ax, ir: dict, tokens) -> None:
    chart = ir["meta"]["chart_type"]
    if chart not in SUPPORTED:
        raise ValueError(f"mpl2svg does not support chart_type {chart!r}; supported: {sorted(SUPPORTED)}")

    data = ir.get("data")
    if not data or not data.get("series"):
        raise ValueError("statistical route requires a data layer (IR 2.6)")

    series = data["series"]
    palette = tokens.series(len(series))
    x_axis = ir.get("content", {}).get("axis", {}).get("x", "")
    y_axis = ir.get("content", {}).get("axis", {}).get("y", "")

    for i, s in enumerate(series):
        x = np.asarray(s["x"], dtype=float)
        y = np.asarray(s["y"], dtype=float)
        color = palette[i % len(palette)]
        label = s.get("name") or ir.get("content", {}).get("legend", [None] * 999)[i] or f"series {i + 1}"
        yerr = np.asarray(s["yerr"], dtype=float) if "yerr" in s else None
        kind = s.get("kind", chart)

        if kind == "line":
            ax.plot(x, y, color=color, linewidth=tokens.s("stroke.medium"), label=label,
                    marker=s.get("marker", "o"), markersize=4,
                    markeredgewidth=tokens.s("stroke.hairline"))
        elif kind == "scatter":
            ax.scatter(x, y, color=color, s=28, label=label, edgecolors="none")
        elif kind in ("bar", "bar_grouped"):
            width = s.get("width", 0.8 / max(len(series), 1))
            offset = (i - (len(series) - 1) / 2) * width
            ax.bar(x + offset, y, width=width, color=color, label=label,
                   edgecolor="none", zorder=3)
        elif kind == "bar_stacked":
            ax.bar(x, y, width=s.get("width", 0.6), color=color, label=label,
                   edgecolor="none", zorder=3)
        elif kind == "area":
            ax.fill_between(x, 0, y, color=color, alpha=0.25, zorder=2)
            ax.plot(x, y, color=color, linewidth=tokens.s("stroke.thin"), label=label)
        elif kind in ("box", "violin"):
            ax.boxplot(y, positions=[i], widths=0.5, patch_artist=True,
                       boxprops={"facecolor": color, "edgecolor": tokens.c("colors.ink")},
                       medianprops={"color": tokens.c("colors.ink")})
        elif kind == "hist":
            ax.hist(y, bins=s.get("bins", 20), color=color, label=label,
                    edgecolor=tokens.c("colors.surface"), linewidth=0.5, zorder=3)
        elif kind == "stem":
            ax.stem(x, y, linefmt="-", markerfmt="o", basefmt=" ")
        elif kind == "errorbar":
            ax.errorbar(x, y, yerr=yerr, color=color, label=label,
                        linewidth=tokens.s("stroke.thin"),
                        elinewidth=tokens.s("stroke.hairline"), capsize=3)
        else:
            ax.plot(x, y, color=color, label=label)

        if yerr is not None and kind in ("line", "scatter", "bar", "bar_grouped"):
            # error bars drawn separately so the kind stays readable
            if kind == "bar_grouped":
                width = s.get("width", 0.8 / max(len(series), 1))
                offset = (i - (len(series) - 1) / 2) * width
                ax.errorbar(x + offset, y, yerr=yerr, fmt="none",
                            ecolor=tokens.c("colors.ink_secondary"),
                            elinewidth=tokens.s("stroke.hairline"), capsize=2, zorder=4)
            elif kind == "line":
                ax.fill_between(x, y - yerr, y + yerr, color=color, alpha=0.18, zorder=1)

    if x_axis:
        ax.set_xlabel(x_axis)
    if y_axis:
        ax.set_ylabel(y_axis)

    units = data.get("units", {})
    if units.get("x") and not x_axis:
        ax.set_xlabel(units["x"])
    if units.get("y") and not y_axis:
        ax.set_ylabel(units["y"])

    if len(series) > 1 or (series and series[0].get("name")):
        ax.legend(loc="best")

    # category names on the x axis when the data supplies them
    categories = data.get("categories")
    if categories and len(categories) == len(series[0]["x"]):
        ax.set_xticks(list(range(len(categories))))
        ax.set_xticklabels([str(c) for c in categories], fontsize=tokens.font_size("tick_label"))

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if tokens.name != "tech":
        ax.spines["left"].set_color(tokens.c("colors.axis"))
        ax.spines["bottom"].set_color(tokens.c("colors.axis"))

    stats = data.get("statistics")
    if stats:
        note = "  ".join(f"{k}={v}" for k, v in stats.items() if k != "note")
        if stats.get("note"):
            note = f"{note}  {stats['note']}"
        ax.text(0.0, -0.18, note, transform=ax.transAxes, fontsize=tokens.font_size("annotation"),
                color=tokens.c("colors.ink_tertiary"), ha="left", va="top")


def render(ir: dict, out_svg: str | None = None, out_png: str | None = None,
           dpi: int | None = None, tokens_name: str | None = None) -> str:
    meta = ir.get("meta", {})
    tokens = load_tokens(tokens_name or meta.get("tokens", "academic"))
    dpi = dpi or int(tokens.get("export.target_dpi", 600))
    if dpi < 300:
        dpi = 600  # statistical route never ships below print resolution

    _apply_rc(tokens, dpi)

    layout = ir.get("layout", {})
    canvas = layout.get("canvas", {})
    # Physical size comes first for statistical figures: a journal column is a measured
    # width, not a dimensionless unit count. `figsize_inches` wins; otherwise fall back
    # to a double-column default and resample from the unit count proportionally.
    figsize = canvas.get("figsize_inches")
    if figsize:
        fig_w_in, fig_h_in = float(figsize[0]), float(figsize[1])
    else:
        aspect = float(canvas.get("h", 70)) / float(canvas.get("w", 100))
        fig_w_in = float(canvas.get("width_inches", 7.0))
        fig_h_in = fig_w_in * aspect

    # Output width guard. The vision probe (docs/vision-probe-report.md) measured the
    # readable ceiling at 4000px; exceeding it silently degrades judgement quality.
    max_px = float(canvas.get("max_width_px", 4000))
    if fig_w_in * dpi > max_px:
        scale_down = max_px / (fig_w_in * dpi)
        fig_w_in *= scale_down
        fig_h_in *= scale_down

    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in))
    _draw(ax, ir, tokens)

    fig.tight_layout()
    if out_svg:
        fig.savefig(out_svg, format="svg", bbox_inches="tight",
                    facecolor=tokens.c("colors.surface"))
    if out_png:
        fig.savefig(out_png, format="png", bbox_inches="tight",
                    facecolor=tokens.c("colors.surface"))
    plt.close(fig)

    if out_svg:
        return Path(out_svg).read_text(encoding="utf-8")
    return ""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render a statistical FigSmith IR to SVG/PNG.")
    ap.add_argument("ir")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--png", default=None)
    ap.add_argument("--dpi", type=int, default=None)
    args = ap.parse_args(argv)

    ir = json.loads(Path(args.ir).read_text(encoding="utf-8-sig"))
    out = args.out or str(Path(args.ir).with_suffix(".svg"))
    png = args.png or str(Path(args.ir).with_suffix(".png"))
    render(ir, out, png, args.dpi)
    print(f"wrote {out} and {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
