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
# Keep this in sync with the `statistical` entries in domains/*/references/catalog.json;
# a catalog entry with no implementation here is a promise the tool cannot keep.
SUPPORTED = {
    "line", "scatter", "bar", "bar_grouped", "bar_stacked", "area",
    "box", "violin", "hist", "heatmap", "errorbar", "stem", "pie", "donut",
}


def _read_frozen_table(source: Path, columns: dict, name: str) -> dict:
    """Load one series' x/y/yerr from the frozen CSV named by `data.source`.

    IR 2.6 says the numbers live in the frozen table, not inlined in the IR. This is the
    reader that makes that rule true: without it `data.source` was documentation and the
    IR carried the numbers anyway, so the chart could drift from its data unnoticed.
    """
    import csv

    if not source.exists():
        raise FileNotFoundError(f"data.source not found: {source}")
    try:
        with source.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        raise OSError(f"data.source unreadable: {source}: {exc}") from exc
    if not rows:
        raise ValueError(f"data.source {source} has no data rows")

    missing = [col for col in columns.values() if col not in rows[0]]
    if missing:
        raise KeyError(
            f"series {name!r}: columns {missing} not in {source.name} "
            f"(available: {list(rows[0])})")

    def numeric(key: str) -> list[float]:
        raw = [r[columns[key]] for r in rows]
        try:
            return [float(v) for v in raw]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"series {name!r}: column {columns[key]!r} is not numeric "
                             f"({exc})") from exc

    # A categorical x column ("baseline", "low_dose", ...) is plotted by position and
    # its labels become the tick text. Treating it as numeric used to abort the render
    # with "could not convert string to float", which made the documented frozen-table
    # workflow unusable for exactly the bar charts it is meant for.
    raw_x = [r[columns["x"]] for r in rows]
    try:
        x = [float(v) for v in raw_x]
        categories = None
    except (TypeError, ValueError):
        x = list(range(len(raw_x)))
        categories = [str(v) for v in raw_x]

    out = {"x": x, "y": numeric("y")}
    if "yerr" in columns:
        out["yerr"] = numeric("yerr")
    if categories is not None:
        out["_categories"] = categories
    return out


def resolve_series(ir: dict, base: Path | None = None) -> list[dict]:
    """Return the series with their data resolved, reading the frozen table if declared.

    A series that declares `columns` is filled from `data.source`; a series without them
    keeps its inline arrays (handy for programmatic use and for a quick plot), but the
    IR validator rejects a declared source with inlined numbers.
    """
    data = ir.get("data") or {}
    series = data.get("series") or []
    source = data.get("source")
    out: list[dict] = []
    for i, s in enumerate(series):
        s = dict(s)
        columns = s.get("columns")
        if columns:
            if not source:
                raise ValueError(f"data.series[{i}] declares columns but data.source is unset")
            if not isinstance(columns, dict) or "x" not in columns or "y" not in columns:
                raise ValueError(f"data.series[{i}].columns must declare at least x and y")
            src = Path(source)
            if not src.is_absolute():
                src = (base or Path.cwd()) / src
            values = _read_frozen_table(src, columns, s.get("name") or f"series {i + 1}")
            s.update(values)
        out.append(s)
    return out


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


def _draw(ax, ir: dict, tokens, base_dir: Path | None = None) -> None:
    chart = ir["meta"]["chart_type"]
    if chart not in SUPPORTED:
        raise ValueError(f"mpl2svg does not support chart_type {chart!r}; supported: {sorted(SUPPORTED)}")

    data = ir.get("data")
    if not data or not data.get("series"):
        raise ValueError("statistical route requires a data layer (IR 2.6)")

    # `data.source` is resolved relative to the IR document, so a figure is reproducible
    # no matter which directory the command is run from.
    series = resolve_series(ir, base_dir)
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
            width = s.get("width", 0.6)
            bottom = np.zeros(len(y)) if s.get("stack") is None else np.asarray(s["stack"], dtype=float)
            ax.bar(x, y, width=width, bottom=bottom, color=color, label=label,
                   edgecolor="none", zorder=3)
        elif kind == "area":
            ax.fill_between(x, 0, y, color=color, alpha=0.25, zorder=2)
            ax.plot(x, y, color=color, linewidth=tokens.s("stroke.thin"), label=label)
        elif kind == "violin":
            # A violin is a KDE of the distribution, not a box plot with rounded ends.
            # `violin()` also draws a box plot by default; the box is opt-in.
            parts = ax.violinplot([list(y)], positions=[i], widths=0.5, showextrema=False)
            for body in parts["bodies"]:
                body.set_facecolor(color)
                body.set_edgecolor(tokens.c("colors.ink"))
                body.set_linewidth(tokens.s("stroke.hairline"))
                body.set_alpha(1.0)
            ax.scatter(np.full(len(y), i) + np.random.default_rng(0).uniform(-0.12, 0.12, len(y)),
                       y, s=8, color=tokens.c("colors.ink"), zorder=3)
        elif kind == "hist":
            ax.hist(y, bins=s.get("bins", 20), color=color, label=label,
                    edgecolor=tokens.c("colors.surface"), linewidth=0.5, zorder=3)
        elif kind == "stem":
            markerline, stemlines, _ = ax.stem(x, y, linefmt="-", markerfmt="o", basefmt=" ")
            markerline.set_color(color)
            markerline.set_markersize(4)
            stemlines.set_color(color)
            stemlines.set_linewidth(tokens.s("stroke.thin"))
            if label:
                stemlines.set_label(label)
        elif kind == "errorbar":
            ax.errorbar(x, y, yerr=yerr, color=color, label=label,
                        linewidth=tokens.s("stroke.thin"),
                        elinewidth=tokens.s("stroke.hairline"), capsize=3)
        elif kind in ("pie", "donut"):
            # A pie encodes a composition, so the wedge order is the category order and
            # the values are absolute, not positions on an axis.
            wedge_props = {"edgecolor": tokens.c("colors.surface"), "linewidth": 0.8}
            radius = 1.0 if kind == "pie" else 0.8
            if kind == "donut":
                wedge_props["width"] = 0.4
            colours = [palette[j % len(palette)] for j in range(len(y))]
            wedges, _ = ax.pie(y, radius=radius, colors=colours, wedgeprops=wedge_props,
                               startangle=90, counterclock=False)
            ax.set_aspect("equal")
            categories = data.get("categories") or series[0].get("_categories")
            if categories and len(categories) == len(y):
                ax.legend(wedges, [str(c) for c in categories],
                          loc="center left", bbox_to_anchor=(1.0, 0.5),
                          frameon=False, fontsize=tokens.font_size("legend"))
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

    if chart not in ("pie", "donut") and (len(series) > 1 or (series and series[0].get("name"))):
        ax.legend(loc="best")

    # category names on the x axis when the data supplies them. The labels line up with
    # the x values themselves, not with 0..n-1: a series with x = [10, 20, 30] has to be
    # labelled at those coordinates, or every tick lands on the wrong category. A
    # categorical source column supplies them automatically.
    categories = data.get("categories")
    if not categories and series and series[0].get("_categories"):
        categories = series[0]["_categories"]
    if categories and len(categories) == len(series[0]["x"]):
        ticks = [float(v) for v in series[0]["x"]]
        if len(categories) <= 12:
            ax.set_xticks(ticks)
            ax.set_xticklabels([str(c) for c in categories],
                               fontsize=tokens.font_size("tick_label"))
        else:
            step = max(1, len(categories) // 12)
            ax.set_xticks(ticks[::step])
            ax.set_xticklabels([str(c) for c in categories[::step]],
                               fontsize=tokens.font_size("tick_label"))

    if chart not in ("pie", "donut"):
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
           dpi: int | None = None, tokens_name: str | None = None,
           base_dir: Path | None = None) -> str:
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
    _draw(ax, ir, tokens, base_dir)

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
    render(ir, out, png, args.dpi, base_dir=Path(args.ir).resolve().parent)
    print(f"wrote {out} and {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
