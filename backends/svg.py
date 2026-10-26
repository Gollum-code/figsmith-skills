#!/usr/bin/env python3
"""backends/svg.py - IR -> SVG, plus the layout resolver that turns abstract
grid coordinates into absolute pixel rectangles.

Design notes:
  * `fill` never lands in CSS (METHOD hard-trap #1). Colors are set per element or
    inherited from a wrapping <g fill>.
  * Dimensionless units are resolved here; canvas/dpi stay in the renderer's hands.
  * Five primitives only: box / arrow / polyline / band / label.

Usage as a library:
    from backends.svg import render
    svg_text = render(ir_dict, out_path="out.svg")

Usage as a CLI:
    python -m backends.svg <ir.json> [-o out.svg] [--scale 8]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tokens import load as load_tokens  # noqa: E402

PRIMITIVES = {"box", "arrow", "polyline", "band", "label"}


def parse_svg_size(svg_text: str) -> tuple[float, float, str]:
    """Read the *root* `<svg>` width/height and their unit.

    Searching the whole document for `width="..." height="..."` picked up whichever
    rectangle happened to appear first, which made the PDF page size depend on element
    order (matplotlib emits its root size in points, with units). Only the root tag is
    authoritative; `viewBox` is the fallback when a tool omits width/height.
    """
    import re

    tag = re.search(r"<svg\b[^>]*>", svg_text, re.S)
    if not tag:
        raise ValueError("no <svg> root element")
    attrs = tag.group(0)

    def _len(name: str) -> tuple[float, str] | None:
        m = re.search(rf'\b{name}\s*=\s*"([\d.]+)\s*(px|pt|mm|cm|in)?"', attrs)
        if not m:
            return None
        return float(m.group(1)), (m.group(2) or "px")

    w = _len("width")
    h = _len("height")
    if w and h:
        # A mismatch in units is not something to guess about quietly.
        if w[1] != h[1]:
            raise ValueError(f"root width/height units differ ({w[1]} vs {h[1]})")
        return w[0], h[0], w[1]
    vb = re.search(r'\bviewBox\s*=\s*"([\d.\-\s]+)"', attrs)
    if vb:
        parts = vb.group(1).split()
        if len(parts) == 4:
            return float(parts[2]), float(parts[3]), "px"
    raise ValueError("SVG has no explicit width/height or viewBox; cannot size the canvas")


# --------------------------------------------------------------------------
# layout resolution
# --------------------------------------------------------------------------

class Node:
    """A resolved node: absolute pixel box plus everything needed to draw it."""

    def __init__(self, nid: str, kind: str, x: float, y: float, w: float, h: float):
        self.id = nid
        self.kind = kind
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


def layer_graph(ir: dict, direction: str = "top-down") -> tuple[dict[str, int], set[tuple[str, str]]]:
    """Assign a layer index to every node by longest-path layering.

    Greedy column packing puts a node wherever it happens to fall, which breaks a
    flowchart: `db` ends up beside `cache` even though it belongs under `service`.
    Longest-path layering derives depth from the edge structure, so the picture matches
    the topology.

    **Back edges do not add depth.** In a flow with a cycle (`reject -> client`), treating
    every edge as forward would push `client` four layers down and wreck the picture.
    Edges that close a cycle are detected here and returned separately: they still get
    drawn, but they do not influence layering.

    Returns ({node_id: layer}, {back edges}).
    """
    topo = ir.get("topology", {})
    nodes = [n["id"] for n in topo.get("nodes", []) if n.get("kind") != "band"]
    edges = [(e["from"], e["to"]) for e in topo.get("edges", [])]

    adjacency: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        if a in adjacency and b in adjacency:
            adjacency[a].append(b)

    # DFS to find back edges (edges into a node currently on the DFS stack). Iterative:
    # a recursive walk hit Python's recursion limit on a long chain (a 1500-node pipeline
    # is a legal drawio file).
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    back_edges: set[tuple[str, str]] = set()

    for root in nodes:
        if color[root] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        color[root] = GRAY
        while stack:
            u, idx = stack[-1]
            if idx < len(adjacency[u]):
                stack[-1] = (u, idx + 1)
                v = adjacency[u][idx]
                if color[v] == GRAY:
                    back_edges.add((u, v))
                elif color[v] == WHITE:
                    color[v] = GRAY
                    stack.append((v, 0))
            else:
                color[u] = BLACK
                stack.pop()

    forward = [(a, b) for a, b in edges if (a, b) not in back_edges]

    # longest-path layering over forward edges only
    indegree: dict[str, int] = {n: 0 for n in nodes}
    fwd_adj: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in forward:
        fwd_adj[a].append(b)
        indegree[b] += 1

    layer = {n: 0 for n in nodes}
    queue = [n for n in nodes if indegree[n] == 0]
    while queue:
        current = queue.pop(0)
        for nxt in fwd_adj[current]:
            layer[nxt] = max(layer[nxt], layer[current] + 1)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    return layer, back_edges


_SPEC_STRATEGY = {
    # One horizontal row of equal boxes.
    "row-1": "linear", "row-n-equal": "linear", "multi-row": "linear",
    "row-1-branch": "linear",
    # One box per row: layers, lanes, timelines, funnels.
    "stacked-bands": "stack", "stacked-offset": "stack", "stacked-axes": "stack",
    "nested": "stack", "lanes": "stack", "axis-alt": "stack", "bars-deps": "stack",
    "narrowing": "stack",
    # Square-ish grid in declaration order: matrices, tables, split layouts.
    "grid": "grid", "matrix": "grid", "table": "grid", "grid-contained": "grid",
    "grid-numbers": "grid", "sections": "grid", "two-column": "grid",
    "split-mid": "grid", "tri-matrix": "grid", "matrix-bars": "grid",
    "zones": "grid", "scatter-leaders": "grid",
    # Topology-derived layering.
    "graph": "graph", "hierarchy": "graph", "free": "graph",
    "mother-children": "graph", "subject-leaders": "graph", "two-col-links": "graph",
    "graph-symbols": "graph", "curve-peaks": "graph",
    # Statistical-type specs: matplotlib owns the layout, so the structure route is
    # never asked to place them. Mapping them to "graph" keeps the warning list honest.
    "axes": "graph", "axes-region": "graph", "axes-midline": "graph", "axes-grid": "graph",
    "polar": "graph", "flows": "graph", "area-tiles": "graph", "gradient-axis": "graph",
    "rows-bar": "graph",
}
# Specs the grid/row/column placement model cannot express. They are reported rather
# than silently rendered as a plain graph.
UNIMPLEMENTED_SPECS = {"radial", "ring", "circles-2", "circles-3", "ring-text", "ring-flows"}


def layout_strategy(spec: str | None, warn: bool = True) -> str:
    """Map a catalog `layout_spec` to one of the implemented placement strategies.

    Public so the scaffolder can size its grid to match: a `stack` diagram wants one
    column (full-width rows), a `linear` one wants exactly N columns. `warn=False` lets
    the scaffolder ask without duplicating the renderer's warning.
    """
    spec = (spec or "").strip()
    if not spec:
        return "graph"
    if spec in UNIMPLEMENTED_SPECS:
        if warn:
            print(f"warning: layout_spec {spec!r} is not implemented yet; "
                  f"falling back to topology layering", file=sys.stderr)
        return "graph"
    return _SPEC_STRATEGY.get(spec, "graph")


def _strategy_for(ir: dict) -> str:
    return layout_strategy((ir.get("meta") or {}).get("layout_spec"))


def auto_layout(ir: dict, direction: str = "top-down") -> dict[str, dict]:
    """Derive layout.nodes from the topology when the IR does not declare one.

    Used by the mermaid/drawio route: the source gives structure, this gives a layout
    that respects it. Explicit IR layout always wins.

    `meta.layout_spec` (from the chart catalog) selects a placement strategy: a pipeline
    wants one row, a layered diagram wants one box per row, a matrix wants a grid. Without
    it every chart type got the same topology layering, which is why "layered" and
    "pipeline" rendered identically.
    """
    existing = ir.get("layout", {}).get("nodes")
    if existing:
        return existing

    strategy = _strategy_for(ir)
    bands = {n["id"] for n in ir.get("topology", {}).get("nodes", []) if n.get("kind") == "band"}
    members = {n["id"]: list(n.get("members") or [])
               for n in ir.get("topology", {}).get("nodes", []) if n.get("kind") == "band"}

    if strategy in ("linear", "stack", "grid"):
        ids = [n["id"] for n in ir.get("topology", {}).get("nodes", [])
               if n.get("kind") != "band"]
        out: dict[str, dict] = {}
        if strategy == "linear":
            for i, nid in enumerate(ids):
                out[nid] = {"col": i, "row": 0}
        elif strategy == "stack":
            for i, nid in enumerate(ids):
                out[nid] = {"col": 0, "row": i}
        else:
            cols = max(int(len(ids) ** 0.5 + 0.999), 1) if ids else 1
            for i, nid in enumerate(ids):
                out[nid] = {"col": i % cols, "row": i // cols}
    else:
        layer, _back = layer_graph(ir, direction)
        layered = [n for n in layer if n not in bands]
        # One position map instead of `list(layer).index(k)` inside the sort key, which
        # was O(n^2) per comparison and made large imported graphs crawl.
        position = {nid: i for i, nid in enumerate(layer)}
        buckets: dict[int, list[str]] = {}
        for nid in sorted(layered, key=lambda k: (layer[k], position[k])):
            buckets.setdefault(layer[nid], []).append(nid)
        out = {}
        for depth, group in sorted(buckets.items()):
            for i, nid in enumerate(group):
                out[nid] = {"col": i, "row": depth}

    # A band covers the rectangle its members occupy, so a subgraph frames its nodes
    # instead of sitting as an orphan strip on top of the first row.
    for bid in bands:
        inside = [nid for nid in members.get(bid, []) if nid in out]
        if not inside:
            max_col = max((int(e.get("col", 0)) + int(e.get("col_span", 1))
                           for e in out.values()), default=1)
            out[bid] = {"col": 0, "row": 0, "col_span": max_col, "row_span": 1}
            continue
        cols = [int(out[nid].get("col", 0)) for nid in inside]
        rows = [int(out[nid].get("row", 0)) for nid in inside]
        out[bid] = {
            "col": min(cols), "row": min(rows),
            "col_span": max(cols) - min(cols) + 1,
            "row_span": max(rows) - min(rows) + 1,
        }
    return out


def resolve_layout(ir: dict, scale: float = 1.0) -> tuple[list[Node], dict]:
    """Turn layout.nodes abstract entries into absolute pixel boxes.

    Coordinate model: the *unit* is the design grid. `px_per_unit` converts it to pixels.
    Boxes derive from layout.grid so that adding a node means adding a row of data,
    never hand-editing coordinates (METHOD principles 5 and 6). Explicit {x, y, w, h}
    entries are honoured for one-off placement.

    The canvas is derived from content + symmetric margin (METHOD 2.3), so the IR never
    ships meaningless white borders.
    """
    layout = ir.get("layout", {})
    grid = layout.get("grid", {})
    nodes_layout = layout.get("nodes", {})
    # A missing layout is derived from topology, so the mermaid/drawio route produces a
    # figure that matches its structure instead of a greedy left-to-right dump. Both the
    # renderer and the checker go through here, so they can never disagree.
    if not nodes_layout:
        nodes_layout = auto_layout(ir, layout.get("direction", "top-down"))
    canvas = layout.get("canvas", {})
    meta = ir.get("meta", {})
    tokens = load_tokens(meta.get("tokens", "academic"))

    width_unit = float(meta.get("width_unit", 100))
    px_per_unit = float(scale) if scale else float(canvas.get("px_per_unit", 8.0))
    # Physical width is what gives "pt" meaning. A figure drawn 1200px wide but destined
    # for a 7in double column has an effective 171 dpi, so 8pt text is ~19px - not the
    # 96px that naively multiplying pt by px_per_unit would produce.
    width_inches = float(canvas.get("width_inches", tokens.get("canvas.width_inches", 7.0)))
    canvas_w_px = width_unit * px_per_unit
    effective_dpi = canvas_w_px / width_inches if width_inches > 0 else 96.0

    margin_u = float(canvas.get("margin", tokens.get("canvas.margin", 4)))
    margin = margin_u * px_per_unit

    columns = int(grid.get("columns", 1))
    gap_x_u = float(grid.get("gap_x", 3.0))
    gap_y_u = float(grid.get("gap_y", 4.0))

    # `width_unit` is the authoritative canvas width. Box width is derived from it so
    # that `columns` means columns of the canvas, and there is exactly one place the
    # total width is declared (no two contradictory numbers).
    content_w_u = width_unit - 2 * margin_u
    derived_box_w = (content_w_u - (columns - 1) * gap_x_u) / max(columns, 1)
    # An explicit box_w is a *cap*, not an override: the derived width wins when it is
    # smaller, so `width_unit` stays the single authority on canvas width.
    box_w_u = min(float(grid.get("box_w", derived_box_w)), derived_box_w)
    box_h_u = float(grid.get("box_h", 12.0))

    canvas_w_px = width_unit * px_per_unit
    origin_x = margin
    origin_y = margin
    pitch_x = box_w_u * px_per_unit + gap_x_u * px_per_unit
    pitch_y = box_h_u * px_per_unit + gap_y_u * px_per_unit

    nodes: list[Node] = []
    kinds = {n["id"]: n.get("kind", "box") for n in ir.get("topology", {}).get("nodes", [])}

    max_right, max_bottom = margin, margin
    for nid, entry in nodes_layout.items():
        kind = kinds.get(nid, "box")
        if all(k in entry for k in ("x", "y", "w", "h")):
            # Explicit coordinates are clamped to the canvas: a negative col/row or a
            # nonsensical size is a spec error, and emitting a negative pixel coordinate
            # pushes content off-canvas where nothing can verify it.
            x = max(float(entry["x"]), 0.0) * px_per_unit
            y = max(float(entry["y"]), 0.0) * px_per_unit
            w = max(float(entry["w"]), 0.0) * px_per_unit
            h = max(float(entry["h"]), 0.0) * px_per_unit
        else:
            col = max(int(entry.get("col", 0)), 0)
            row = max(int(entry.get("row", 0)), 0)
            span_c = max(int(entry.get("col_span", 1)), 1)
            span_r = max(int(entry.get("row_span", 1)), 1)
            x = origin_x + col * pitch_x
            y = origin_y + row * pitch_y
            w = span_c * box_w_u * px_per_unit + (span_c - 1) * gap_x_u * px_per_unit
            h = span_r * box_h_u * px_per_unit + (span_r - 1) * gap_y_u * px_per_unit
        nodes.append(Node(nid, kind, x, y, w, h))
        max_right = max(max_right, x + w)
        max_bottom = max(max_bottom, y + h)

    # Derived canvas, not declared: content + symmetric margin (METHOD 2.3).
    # Both the grid extent and explicit coordinates grow it, so a figure laid out by
    # hand is never cropped at the grid boundary.
    max_col = max((max(int(e.get("col", 0)), 0) + max(int(e.get("col_span", 1)), 1)
                   for e in nodes_layout.values()), default=1)
    max_row = max((max(int(e.get("row", 0)), 0) + max(int(e.get("row_span", 1)), 1)
                   for e in nodes_layout.values()), default=1)
    right_edge = origin_x + max_col * box_w_u * px_per_unit + (max_col - 1) * gap_x_u * px_per_unit
    bottom_edge = origin_y + max_row * box_h_u * px_per_unit + (max_row - 1) * gap_y_u * px_per_unit
    canvas_w = max(canvas_w_px, right_edge + margin, max_right + margin)
    canvas_h = max(bottom_edge + margin, max_bottom + margin)
    info = {
        "canvas_w": round(canvas_w, 2),
        "canvas_h": round(canvas_h, 2),
        "margin": round(margin, 2),
        "px_per_unit": round(px_per_unit, 3),
        "effective_dpi": round(effective_dpi, 2),
        "width_inches": round(width_inches, 3),
        "origin": [round(origin_x, 2), round(origin_y, 2)],
        "pitch": [round(pitch_x, 2), round(pitch_y, 2)],
        "box_px": [round(box_w_u * px_per_unit, 2), round(box_h_u * px_per_unit, 2)],
    }
    return nodes, info


# --------------------------------------------------------------------------
# svg emission
# --------------------------------------------------------------------------

def _font_attr(tokens, role: str) -> str:
    """A font stack covering latin and CJK, in one attribute.

    Without the CJK entry the PDF backend resolves only Arial and every Chinese glyph
    silently disappears from the deliverable (a paper-figure figure is mostly Chinese).
    The stack is quoted-family lists, which the SVG, PDF and Pillow readers all accept.
    """
    latin = tokens.font(role, "latin")
    latin_fb = tokens.get(f"fonts.{tokens.get(f'fonts.role.{role}', 'sans')}.latin_fallback")
    cjk = tokens.font(role, "cjk")
    cjk_fb = tokens.get(f"fonts.{tokens.get(f'fonts.role.{role}', 'sans')}.cjk_fallback")
    stack = [n for n in (latin, latin_fb, cjk, cjk_fb) if n]
    return f'font-family="{escape(", ".join(stack))}"'


def _label_lines(text: str, size_px: float, box_w: float, tokens) -> list[str]:
    """Split to fit the width budget (METHOD 2.1): overflow -> wrap, never shrink.

    An explicit newline in the IR label is honoured as a hard break. Otherwise the
    text is greedily wrapped at word boundaries; a single word longer than the box
    is broken mid-word rather than silently overflowing.
    """
    limit = max(box_w - 2 * 10.0, size_px)
    if "\n" in text:
        segments = [seg.strip() for seg in text.split("\n") if seg.strip()]
    else:
        segments = [text.strip()]

    lines: list[str] = []
    for segment in segments:
        if tokens.text_width(segment, size_px) <= limit:
            lines.append(segment)
            continue
        words = segment.split(" ")
        cur = ""
        for word in words:
            candidate = f"{cur} {word}".strip()
            if tokens.text_width(candidate, size_px) <= limit or not cur:
                cur = candidate
            else:
                lines.append(cur)
                cur = word
        if cur:
            # a single word wider than the box: break it rather than overflow
            while tokens.text_width(cur, size_px) > limit and len(cur) > 1:
                cut = len(cur)
                while cut > 1 and tokens.text_width(cur[:cut], size_px) > limit:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
            lines.append(cur)
    return lines or [text]


def _text_block(x: float, y: float, w: float, h: float, lines: list[str], size_px: float,
                tokens, role: str, color: str, anchor: str = "middle") -> list[str]:
    lh = size_px * tokens.get("fonts.line_height_ratio", 1.35)
    total = lh * len(lines)
    start_y = y + (h - total) / 2 + size_px * 0.82
    # The halo that separates text from a busy background is the surface color, so it
    # stays correct under a dark token set instead of always being white.
    halo = tokens.c("colors.surface")
    family = _font_attr(tokens, role)
    out = []
    for i, line in enumerate(lines):
        cy = start_y + i * lh
        if anchor == "middle":
            out.append(f'<text x="{x + w / 2:.2f}" y="{cy:.2f}" font-size="{size_px:.2f}" '
                       f'{family} fill="{color}" text-anchor="middle" '
                       f'paint-order="stroke" stroke="{halo}" stroke-width="{max(size_px * 0.12, 2.5):.2f}">'
                       f'{escape(line)}</text>')
        else:
            out.append(f'<text x="{x + 10:.2f}" y="{cy:.2f}" font-size="{size_px:.2f}" '
                       f'{family} fill="{color}" text-anchor="start" '
                       f'paint-order="stroke" stroke="{halo}" stroke-width="{max(size_px * 0.12, 2.5):.2f}">'
                       f'{escape(line)}</text>')
    return out


def render(ir: dict, out_path: str | None = None, scale: float = 1.0,
           tokens_name: str | None = None) -> str:
    meta = ir.get("meta", {})
    tokens = load_tokens(tokens_name or meta.get("tokens", "academic"))

    nodes, info = resolve_layout(ir, scale)
    box_h_px = info["box_px"][1]
    labels = ir.get("content", {}).get("labels", {})
    style = ir.get("style", {})
    fill_map = style.get("fill", {})
    stroke_default = tokens.c(style.get("stroke", {}).get("default", "colors.border"))
    stroke_w = tokens.s(style.get("stroke", {}).get("width", "stroke.thin"))
    text_color = tokens.c(style.get("text", {}).get("color", "colors.ink"))
    text_role = style.get("text", {}).get("default", "fonts.role.panel_label")
    text_size_pt = tokens.s(style.get("text", {}).get("size", "fonts.size_pt.panel_label"), 10.0)
    # pt -> px via the effective dpi (physical width is what makes "pt" meaningful).
    # The box-height cap keeps text/box proportion when the canvas resizes.
    text_size_px = min(text_size_pt * info["effective_dpi"] / 72.0, box_h_px * 0.42)
    # Annotation text follows the same pt -> px path as body text. Using the raw pt
    # number as px made edge labels 2-3x smaller than the panel labels beside them.
    annotation_pt = tokens.s("fonts.size_pt.annotation", 8.0)
    annotation_px = max(annotation_pt * info["effective_dpi"] / 72.0, 7.0)
    radius = tokens.get("radius.box", 3) * scale
    emphasis = set(style.get("emphasis", []))

    W, H = info["canvas_w"], info["canvas_h"]

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}" height="{H:.2f}" '
        f'viewBox="0 0 {W:.2f} {H:.2f}">',
        f'<rect x="0" y="0" width="{W:.2f}" height="{H:.2f}" fill="{tokens.c("colors.surface")}"/>',
    ]

    # ---- bands first (they sit under boxes) ----
    for node in nodes:
        if node.kind != "band":
            continue
        fill = tokens.c(fill_map.get(node.id, fill_map.get("default", "colors.surface_band")))
        parts.append(f'<rect x="{node.x:.2f}" y="{node.y:.2f}" width="{node.w:.2f}" '
                     f'height="{node.h:.2f}" fill="{fill}" stroke="none"/>')

    # ---- band titles: the domain's signature title plate ----
    # A band title sits at the band's top-left, inset by the text padding. Painted after
    # the band fill and before the boxes so it is never covered by a component, which is
    # arch-diagram collision class #1 (title plate under a box).
    band_title_px = min(
        tokens.s("fonts.size_pt.panel_label", 10.0) * info["effective_dpi"] / 72.0,
        box_h_px * 0.34,
    )
    for node in nodes:
        if node.kind != "band":
            continue
        text = labels.get(node.id, "")
        if not text:
            continue
        pad = tokens.get("grid.text_padding", 6) * scale * 0.5
        parts.append(
            f'<text x="{node.x + pad:.2f}" y="{node.y + pad + band_title_px * 0.85:.2f}" '
            f'font-size="{band_title_px:.2f}" font-weight="600" '
            f'{_font_attr(tokens, "panel_label")} '
            f'fill="{tokens.c("colors.ink_secondary")}" text-anchor="start">{escape(text)}</text>'
        )

    # ---- boxes ----
    for node in nodes:
        if node.kind != "box":
            continue
        fill = tokens.c(fill_map.get(node.id, fill_map.get("default", "colors.surface_band")))
        stroke = stroke_default
        sw = stroke_w
        if node.id in emphasis:
            accent = tokens.get("colors.accent")
            stroke = accent[0] if isinstance(accent, list) and accent else tokens.c("colors.border")
            sw = sw * 1.4
        parts.append(f'<rect x="{node.x:.2f}" y="{node.y:.2f}" width="{node.w:.2f}" '
                     f'height="{node.h:.2f}" rx="{radius:.2f}" ry="{radius:.2f}" '
                     f'fill="{fill}" stroke="{stroke}" stroke-width="{sw:.2f}"/>')
        text = labels.get(node.id, "")
        if text:
            lines = _label_lines(text, text_size_px, node.w, tokens)
            parts.extend(_text_block(node.x, node.y, node.w, node.h, lines,
                                     text_size_px, tokens, text_role, text_color))

    # ---- polyline / label ----
    for node in nodes:
        if node.kind not in ("polyline", "label"):
            continue
        text = labels.get(node.id, "")
        if not text:
            continue
        lines = _label_lines(text, text_size_px, node.w, tokens)
        parts.extend(_text_block(node.x, node.y, node.w, node.h, lines,
                                 text_size_px, tokens, text_role, text_color))

    # ---- edges (arrows) ----
    by_id = {n.id: n for n in nodes}
    for edge in ir.get("topology", {}).get("edges", []):
        src, dst = by_id.get(edge["from"]), by_id.get(edge["to"])
        if src is None or dst is None:
            continue
        parts.append(_arrow(src, dst, stroke_default, stroke_w, tokens, labels, edge,
                            annotation_px))

    parts.append("</svg>")
    svg = "\n".join(parts)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(svg, encoding="utf-8")
    return svg


def _arrow(src: Node, dst: Node, stroke: str, width: float, tokens, labels: dict, edge: dict,
           annotation_px: float, reverse: bool = False) -> str:
    """Straight connector, horizontal or vertical, with a small triangular head.

    Every edge gets a head. A link drawn without one reads as an undirected association,
    and a back edge in a flow diagram then looks like a second forward edge.
    """
    head = tokens.get("stroke.arrow_head", 5.0)
    # horizontal
    if abs(src.cy - dst.cy) < 1.0:
        y = src.cy
        if dst.x > src.right:
            x1, x2 = src.right, dst.x
        elif src.x > dst.right:
            x1, x2 = dst.right, src.x
        else:  # same column, fall through to vertical
            return _arrow_v(src, dst, stroke, width, head, labels, edge, tokens,
                            annotation_px, reverse)
        parts = [f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2 - head:.2f}" y2="{y:.2f}" '
                 f'stroke="{stroke}" stroke-width="{width:.2f}"/>',
                 f'<path d="M {x2:.2f} {y:.2f} l {-head:.2f} {-head * 0.6:.2f} '
                 f'l 0 {head * 1.2:.2f} Z" fill="{stroke}"/>']
        return "\n".join(parts) + _edge_label(edge, (x1 + x2) / 2, y - 8, tokens, labels,
                                              annotation_px)
    return _arrow_v(src, dst, stroke, width, head, labels, edge, tokens, annotation_px, reverse)


def _arrow_v(src: Node, dst: Node, stroke: str, width: float, head: float, labels: dict,
             edge: dict, tokens, annotation_px: float, reverse: bool = False) -> str:
    if dst.y > src.bottom:
        x, y1, y2 = src.cx, src.bottom, dst.y
    elif src.y > dst.bottom:
        x, y1, y2 = dst.cx, dst.bottom, src.y
    else:
        # Not vertically stacked and not horizontally separated: route the link on the
        # side that faces the destination, and keep the arrow head so a back edge is
        # still visibly a return path (arch-diagram collision #5).
        if dst.x >= src.right:
            x1, x2 = src.right, dst.x
        elif src.x >= dst.right:
            x1, x2 = dst.right, src.x
        else:
            x1, x2 = src.x, dst.x
        y = src.cy
        step = -head if x2 > x1 else head
        return (f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2 - step:.2f}" y2="{y:.2f}" '
                f'stroke="{stroke}" stroke-width="{width:.2f}"/>' +
                f'<path d="M {x2:.2f} {y:.2f} l {-step:.2f} {-head * 0.6:.2f} '
                f'l 0 {head * 1.2:.2f} Z" fill="{stroke}"/>' +
                _edge_label(edge, (x1 + x2) / 2, y - 8, tokens, labels, annotation_px))
    parts = [f'<line x1="{x:.2f}" y1="{y1:.2f}" x2="{x:.2f}" y2="{y2 - head:.2f}" '
             f'stroke="{stroke}" stroke-width="{width:.2f}"/>',
             f'<path d="M {x:.2f} {y2:.2f} l {-head * 0.6:.2f} {-head:.2f} '
             f'l {head * 1.2:.2f} 0 Z" fill="{stroke}"/>']
    return "\n".join(parts) + _edge_label(edge, x + 8, (y1 + y2) / 2, tokens, labels,
                                          annotation_px)


def _edge_label(edge: dict, x: float, y: float, tokens, labels: dict,
                size_px: float) -> str:
    text = labels.get(edge.get("label", ""))
    if not text:
        return ""
    # annotation size arrives already converted from pt to px, exactly like body text.
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size_px:.2f}" '
            f'{_font_attr(tokens, "annotation")} '
            f'fill="{tokens.c("colors.ink_secondary")}" '
            f'paint-order="stroke" stroke="{tokens.c("colors.surface")}" '
            f'stroke-width="3">{escape(text)}</text>')


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render a FigSmith IR to SVG.")
    ap.add_argument("ir")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--scale", type=float, default=8.0, help="px per dimensionless unit")
    args = ap.parse_args(argv)

    ir = json.loads(Path(args.ir).read_text(encoding="utf-8-sig"))
    out = args.out or str(Path(args.ir).with_suffix(".svg"))
    svg = render(ir, out, scale=args.scale)
    print(f"wrote {out} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
