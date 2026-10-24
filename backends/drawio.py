#!/usr/bin/env python3
"""backends/drawio.py - FigSmith IR <-> draw.io mxfile, both directions.

Why round-trip and not just export: a stakeholder edits the .drawio and hands it back.
FigSmith must be able to read that edit back into an IR instead of losing it.

Usage:
    python -m backends.drawio ir2drawio <ir.json> -o out.drawio
    python -m backends.drawio drawio2ir <in.drawio> -o out.ir.json
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backends.svg import auto_layout, resolve_layout  # noqa: E402
from core.tokens import load as load_tokens  # noqa: E402

MXFILE_TEMPLATE = """<mxfile host="figsmith" version="24.0.0">
  <diagram id="figsmith-1" name="{name}">
    <mxGraphModel dx="1124" dy="794" grid="1" gridSize="10" guides="1" tooltips="1"
                  connect="1" arrows="1" fold="1" page="1" pageScale="1"
                  pageWidth="1169" pageHeight="826" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
{cells}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""


def _style(tokens, kind: str, emphasized: bool) -> str:
    fill = tokens.c("colors.surface_band").lstrip("#")
    stroke = tokens.c("colors.border").lstrip("#")
    if emphasized:
        accent = tokens.get("colors.accent")
        stroke = (accent[0] if isinstance(accent, list) and accent else tokens.c("colors.border")).lstrip("#")
    if kind == "band":
        return (f"rounded=0;whiteSpace=wrap;html=0;fillColor={fill};strokeColor=none;"
                f"opacity=100;fontSize=11;fontStyle=1;verticalAlign=top;align=left;")
    if kind == "label":
        return "text;html=0;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;"
    return (f"rounded=1;whiteSpace=wrap;html=0;fillColor={fill};strokeColor={stroke};"
            f"strokeWidth={'2' if emphasized else '1'};fontSize=11;verticalAlign=middle;align=center;")


def ir_to_mxfile(ir: dict, name: str = "figsmith") -> str:
    tokens = load_tokens(ir.get("meta", {}).get("tokens", "academic"))
    scale = float(ir.get("layout", {}).get("canvas", {}).get("px_per_unit", 12.0))
    nodes, info = resolve_layout(ir, scale)
    labels = ir.get("content", {}).get("labels", {})
    emphasis = set(ir.get("style", {}).get("emphasis", []))

    cells: list[str] = []
    # bands first so they render behind, matching the SVG painter's order
    ordered = [n for n in nodes if n.kind == "band"] + [n for n in nodes if n.kind != "band"]
    for node in ordered:
        style = _style(tokens, node.kind, node.id in emphasis)
        value = labels.get(node.id, "")
        cells.append(
            f'        <mxCell id="{node.id}" value="{_xml_escape(value)}" style="{style}" '
            f'vertex="1" parent="1">\n'
            f'          <mxGeometry x="{node.x:.0f}" y="{node.y:.0f}" '
            f'width="{node.w:.0f}" height="{node.h:.0f}" as="geometry"/>\n'
            f'        </mxCell>'
        )

    arrow_style = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=0;"
                   f"strokeColor={tokens.c('colors.border').lstrip('#')};"
                   f"strokeWidth=1.4;endArrow=block;endFill=1;")
    by_id = {n.id: n for n in nodes}
    for i, edge in enumerate(ir.get("topology", {}).get("edges", [])):
        src, dst = by_id.get(edge["from"]), by_id.get(edge["to"])
        if src is None or dst is None:
            continue
        src_x, src_y = (0, 0) if src.kind == "band" else (src.cx, src.cy)
        dst_x, dst_y = (0, 0) if dst.kind == "band" else (dst.cx, dst.cy)
        label = _xml_escape(labels.get(edge.get("label", ""), ""))
        cells.append(
            f'        <mxCell id="edge_{i}" value="{label}" style="{arrow_style}" '
            f'edge="1" parent="1" source="{edge["from"]}" target="{edge["to"]}">\n'
            f'          <mxGeometry relative="1" as="geometry">\n'
            f'            <mxPoint x="{src_x:.0f}" y="{src_y:.0f}" as="sourcePoint"/>\n'
            f'            <mxPoint x="{dst_x:.0f}" y="{dst_y:.0f}" as="targetPoint"/>\n'
            f'          </mxGeometry>\n'
            f'        </mxCell>'
        )

    return MXFILE_TEMPLATE.format(name=name, cells="\n".join(cells))


def _xml_escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _xml_unescape(text: str) -> str:
    return (str(text).replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&amp;", "&"))


# A draw.io file is untrusted input. This is the ceiling on the *decompressed* body:
# a graph model for a real diagram is a few hundred KB, so anything far beyond it is
# either a decompression bomb or not a diagram at all. The compressed form can express
# 50 MB in a few KB, which would otherwise land in memory before any parsing happens.
MAX_DECOMPRESSED_CHARS = 20_000_000


def _decode_compressed_diagram(diagram: ET.Element) -> str | None:
    """Decode a compressed draw.io diagram body.

    draw.io stores most saved diagrams as raw-DEFLATE + base64 + URL-encoding inside the
    <diagram> element instead of inline XML. Real exported .drawio files are almost always
    in this form, so refusing them would make the importer useless on anything but
    hand-written fixtures.

    Raises ValueError on malformed input rather than letting zlib/base64 errors escape
    as an unrelated exception type.
    """
    text = (diagram.text or "").strip()
    if not text:
        return None
    # Padding must be computed on the *decoded* base64 string: URL-decoding can change
    # the length (a '+' in the base64 arrives as '%2B'), so computing it on the raw text
    # pads the wrong amount and b64decode rejects a perfectly good body.
    b64 = urllib.parse.unquote(text)
    try:
        raw = base64.b64decode(b64 + "=" * (-len(b64) % 4), validate=False)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"compressed diagram body is not valid base64: {exc}") from exc
    try:
        # The size cap is enforced by refusing an absurd ratio *and* a bounded result.
        decoded = zlib.decompress(raw, -15).decode("utf-8")
    except (zlib.error, UnicodeDecodeError) as exc:
        raise ValueError(f"compressed diagram body failed to inflate: {exc}") from exc
    if len(decoded) > MAX_DECOMPRESSED_CHARS:
        raise ValueError(
            f"decompressed diagram is too large: {len(decoded)} > {MAX_DECOMPRESSED_CHARS}")
    return decoded


def mxfile_to_ir(xml_text: str, tokens: str = "academic") -> dict:
    """Read a draw.io file back into a FigSmith IR.

    Vertices keep their id, label and geometry; edges keep direction and label. Style
    is not imported: FigSmith re-applies its own token set, which is the whole point of
    the interoperability route (METHOD 4).
    """
    root = ET.fromstring(xml_text)
    diagram = root.find(".//diagram")
    name = diagram.get("name") if diagram is not None else "drawio"

    # the graph model may be plain XML or deflate+base64 encoded; try inline first, then
    # decompress the <diagram> body and re-parse it.
    model = root.find(".//mxGraphModel")
    if model is None and diagram is not None:
        decoded = _decode_compressed_diagram(diagram)
        if decoded:
            model = ET.fromstring(decoded)
    if model is None:
        raise ValueError("drawio file has no mxGraphModel (inline or compressed)")
    graph_root = model.find("root")
    if graph_root is None:
        raise ValueError("drawio mxGraphModel has no <root>")
    labels: dict[str, str] = {}
    topo_nodes: list[dict] = []
    topo_edges: list[dict] = []
    layout_nodes: dict[str, dict] = {}
    max_x = max_y = 0.0

    for cell in graph_root.findall("mxCell"):
        cid = cell.get("id")
        if cid in (None, "0", "1"):
            continue
        value = _xml_unescape(cell.get("value", ""))
        style = cell.get("style", "")
        if cell.get("edge") == "1":
            src, dst = cell.get("source"), cell.get("target")
            if src and dst:
                edge = {"from": src, "to": dst, "kind": "arrow"}
                if value:
                    lid = f"el_{len(topo_edges)}"
                    labels[lid] = value
                    edge["label"] = lid
                topo_edges.append(edge)
            continue

        kind = "band" if "container=1" in style or ("verticalAlign=top" in style and "strokeColor=none" in style) else "box"
        if "text;" in style and "fillColor=none" in style:
            kind = "label"
        topo_nodes.append({"id": cid, "kind": kind})
        labels[cid] = value
        geo = cell.find("mxGeometry")
        if geo is not None:
            x = float(geo.get("x", 0) or 0)
            y = float(geo.get("y", 0) or 0)
            w = float(geo.get("width", 120) or 120)
            h = float(geo.get("height", 44) or 44)
            layout_nodes[cid] = {"x": x, "y": y, "w": w, "h": h}
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + h)
        else:
            # A cell with no geometry is usually a group/pool frame: keep the node so the
            # IR stays faithful to the source, but give it a default box so the layout
            # engine has something real to place.
            layout_nodes[cid] = {"x": 0, "y": 0, "w": 200, "h": 60}
            max_x = max(max_x, 200)
            max_y = max(max_y, 60)

    scale = 12.0
    return {
        "schema": "figsmith.ir/1.0",
        "meta": {
            "domain": "imported-drawio",
            "chart_type": "graph",
            "tokens": tokens,
            "source_file": name,
            "width_unit": round((max_x + 24) / scale, 1)
        },
        "content": {"labels": labels, "legend": [], "footnote": ""},
        "topology": {"nodes": topo_nodes, "edges": topo_edges},
        "layout": {
            "canvas": {"margin": 2, "px_per_unit": scale},
            "nodes": layout_nodes,
        },
        "style": {
            "fill": {"default": "colors.surface_band"},
            "stroke": {"default": "colors.border", "width": "stroke.thin"},
            "text": {
                "default": "fonts.role.panel_label",
                "size": "fonts.size_pt.panel_label",
                "color": "colors.ink",
            },
            "emphasis": [],
        },
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Convert between FigSmith IR and draw.io mxfile.")
    ap.add_argument("mode", choices=["ir2drawio", "drawio2ir"])
    ap.add_argument("source")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--tokens", default="academic")
    args = ap.parse_args(argv)

    src = Path(args.source)
    if args.mode == "ir2drawio":
        ir = json.loads(src.read_text(encoding="utf-8-sig"))
        out = args.out or str(src.with_suffix(".drawio"))
        Path(out).write_text(ir_to_mxfile(ir, src.stem), encoding="utf-8")
    else:
        out = args.out or str(src.with_suffix(".ir.json"))
        ir = mxfile_to_ir(src.read_text(encoding="utf-8-sig"), args.tokens)
        Path(out).write_text(json.dumps(ir, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
