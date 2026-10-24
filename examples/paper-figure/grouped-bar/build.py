#!/usr/bin/env python3
"""Figure 2. Dose-response comparison, grouped bars with SD error bars.

This is the canonical statistical route: the CSV is the frozen source, the IR points
at it, and the figure is regenerated from the two. Hand-moved data points are
structurally impossible here.

Regenerate:
    python examples/paper-figure/grouped-bar/build.py
Outputs:
    figure2.svg, figure2.png (600 dpi), figure2.pdf
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "dose_response.csv"
OUT_SVG = HERE / "figure2.svg"
OUT_PNG = HERE / "figure2.png"
OUT_PDF = HERE / "figure2.pdf"

# ---- 1. read the frozen table -------------------------------------------------

rows = list(csv.DictReader(DATA.open(encoding="utf-8")))
conditions = [r["condition"] for r in rows]
n = int(rows[0]["n"])
print(f"frozen table: {DATA.name}  rows={len(rows)}  n={n}  conditions={conditions}")

# ---- 2. build the IR (data stays external, IR only references it) -------------

ir = {
    "schema": "figsmith.ir/1.0",
    "meta": {
        "domain": "paper-figure",
        "chart_type": "bar_grouped",
        "tokens": "academic",
        "title": "Figure 2. Dose-response comparison",
        "width_unit": 100
    },
    "content": {
        "labels": {},
        "axis": {"x": "Condition", "y": "Response (a.u.)"},
        "legend": ["Experiment", "Control"],
        "footnote": f"Mean ± SD, n = {n} per group.",
    },
    "topology": {"nodes": [], "edges": []},
    "layout": {
        "canvas": {"margin": 4, "figsize_inches": [7.0, 4.4]},
        "grid": {"columns": 2, "gap_x": 4.0, "gap_y": 4.0, "box_w": 30, "box_h": 20},
        "nodes": {},
    },
    "style": {
        "fill": {},
        "stroke": {"default": "colors.border", "width": "stroke.thin"},
        "text": {
            "default": "fonts.role.axis_label",
            "size": "fonts.size_pt.axis_label",
            "color": "colors.ink",
        },
        "emphasis": [],
    },
    "data": {
        # Relative to this IR, so the figure regenerates from any working directory.
        "source": str((DATA).relative_to(HERE)),
        "categories": conditions,
        "series": [
            {"name": "Experiment",
             "columns": {"x": "condition", "y": "experiment_mean", "yerr": "experiment_sd"},
             "error_kind": "SD", "kind": "bar_grouped", "width": 0.36},
            {"name": "Control",
             "columns": {"x": "condition", "y": "control_mean", "yerr": "control_sd"},
             "error_kind": "SD", "kind": "bar_grouped", "width": 0.36},
        ],
        "units": {"x": "condition", "y": "a.u."},
        "statistics": {
            "test": "two-sided Welch t-test, experiment vs control within condition",
            "alpha": 0.05,
            "n": n,
            "correction": "Benjamini-Hochberg across 5 conditions",
        },
    },
}

# ---- 3. render ---------------------------------------------------------------

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backends.mpl2svg import _apply_rc, _draw, render  # noqa: E402
from core.tokens import load as load_tokens  # noqa: E402

ir_path = HERE / "figure2.ir.json"
ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False), encoding="utf-8")

render(ir, str(OUT_SVG), str(OUT_PNG), base_dir=HERE)
print(f"wrote {OUT_SVG}, {OUT_PNG}, {ir_path}")

# PDF companion from the same spec: one declaration, three artifacts.
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

tokens = load_tokens("academic")
_apply_rc(tokens, 600)
fig, ax = plt.subplots(figsize=ir["layout"]["canvas"]["figsize_inches"])
_draw(ax, ir, tokens, base_dir=HERE)
fig.tight_layout()
fig.savefig(OUT_PDF, format="pdf", bbox_inches="tight", facecolor=tokens.c("colors.surface"))
plt.close(fig)
print(f"wrote {OUT_PDF}")
