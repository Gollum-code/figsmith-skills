#!/usr/bin/env python3
"""parse_mermaid.py - mermaid text -> FigSmith IR.

Supported diagram types:
  flowchart (graph TD / LR / TB / RL)
  sequenceDiagram (basic)
  stateDiagram-v2 (basic)

Everything else raises a clear error rather than silently producing a wrong IR.

The output IR is a *starting point*: it carries the exact topology and labels from the
source, and the caller fills in style from the domain's design language. This parser
never invents style, and never passes mermaid's own styling through.

Usage:
    python -m domains.docs-diagram.scripts.parse_mermaid input.mmd -o out.ir.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ---- mermaid grammar fragments ------------------------------------------------

NODE_SHAPES = [
    (r"\[\(\((?P<t>[^)]+)\)\)\]", "box"),     # (((text)))
    (r"\[\((?P<t>[^)]+)\)\]", "box"),         # [(text)] database
    (r"\(\((?P<t>[^)]+)\)\)", "box"),         # ((text)) circle
    (r"\[\[(?P<t>[^\]]+)\]\]", "box"),        # [[text]] subroutine
    (r"\[(?P<t>[^\]]+)\]", "box"),            # [text]
    (r"\((?P<t>[^)]+)\)", "box"),             # (text)
    (r"\{(?P<t>[^}]+)\}", "box"),             # {text} decision
]

EDGE_RE = re.compile(
    r"(?P<a>[A-Za-z0-9_]{1,120})\s*"
    r"(?P<arrow><?-{1,3}>|<--?>|-\.->|-\.-|={2,}>|--o|--x|--)\s*"
    r"(?:\|(?P<label>[^|\n]{0,200})\|\s*)?"
    r"(?P<b>[A-Za-z0-9_]{1,120})"
)

# Any inline node definition, used both standalone (`a[Text]`) and inside an edge
# (`a[Text] --> b[Text]`). Matching greedily over the whole line is what lets the edge
# survive: stripping the definition first would eat the source node.
#
# Every inner body is bounded: `[^)]*` on an unterminated `[` costs exponential
# backtracking, which measured 65s on a single 50 KB line. The cap is far above any real
# label while keeping the match linear.
INLINE_NODE_RE = re.compile(
    r"(?P<id>[A-Za-z0-9_]{1,120})\s*"
    r"(?P<shape>"
    r"\[\(\([^)]{0,400}\)\)\]"      # (((circle)))
    r"|\[\[[^\]]{0,400}\]\]"        # [[subroutine]]
    r"|\[\([^)]{0,400}\)\]"         # [(database)]
    r"|\(\([^)]{0,400}\)\)"         # ((circle))
    r"|\[[^\]]{0,400}\]"            # [rect]
    r"|\([^)]{0,400}\)"             # (round)
    r"|\{[^}]{0,400}\}"             # {decision}
    r")"
)

DIRECTION_MAP = {
    "TD": "top-down", "TB": "top-down", "BT": "bottom-up",
    "LR": "left-right", "RL": "right-left",
}


class MermaidError(ValueError):
    pass


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _node_text(shape: str) -> str:
    """Extract the label from a mermaid node shape.

    The shape list is ordered most-nested first: `[[Subroutine]]` must be tried before
    `[text]`, or the outer brackets get left behind in the label. This is why
    `db[(Primary DB)]` renders as `Primary DB` and not `(Primary DB)`.
    """
    for pattern, _kind in NODE_SHAPES:
        m = re.fullmatch(pattern, shape.strip())
        if m:
            return _strip_quotes(m.group("t"))
    # Unknown shape: strip any balanced wrapper pair rather than passing junk through.
    return _strip_quotes(shape.strip("[](){}"))


def parse_flowchart(lines: list[str]) -> dict:
    direction = "top-down"
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    order: list[str] = []
    # Open subgraphs, innermost last. A node defined while a subgraph is open belongs to
    # it; that membership becomes the band's span in the layout. Without it the band was
    # an orphan rectangle sitting on top of the first row.
    open_bands: list[str] = []

    header = lines[0].strip()
    m = re.match(r"(?:flowchart|graph)\s+([A-Za-z]{2})", header)
    if m:
        direction = DIRECTION_MAP.get(m.group(1).upper(), "top-down")

    def _add_node(nid: str, kind: str, label: str) -> None:
        if nid in nodes:
            return
        nodes[nid] = {"id": nid, "kind": kind, "label": label}
        order.append(nid)
        for bid in open_bands:
            nodes[bid]["members"].append(nid)

    for raw in lines[1:]:
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        # subgraph / end
        if line.startswith("subgraph"):
            title = line[len("subgraph"):].strip().strip("[]")
            sid = f"band_{len(nodes)}"
            nodes[sid] = {"id": sid, "kind": "band", "label": _strip_quotes(title),
                          "members": []}
            order.append(sid)
            open_bands.append(sid)
            continue
        if line == "end":
            if open_bands:
                open_bands.pop()
            continue
        # classDef / class / style / linkStyle are styling: dropped on purpose
        if re.match(r"^(classDef|class|style|linkStyle|click)\b", line):
            continue

        # Node definitions may be standalone or embedded in an edge line. Capture the
        # labels first, then rewrite the line down to bare ids so the edge matcher sees
        # `client -->|HTTPS| gateway` and not `client[Client] -->|HTTPS| gateway[API...]`.
        def _capture(m: re.Match) -> str:
            _add_node(m.group("id"), "box", _node_text(m.group("shape")))
            return m.group("id")

        bare_line = INLINE_NODE_RE.sub(_capture, line)

        # A shape that stayed behind did not fit the bounded label pattern. Dropping it
        # silently loses the node, so say so instead.
        if re.search(r"[\[\({]", bare_line):
            raise MermaidError(
                f"could not parse node definition (label too long or unsupported shape): "
                f"{line[:80]!r}")

        # edges (possibly several on one line)
        for em in EDGE_RE.finditer(bare_line):
            a, b = em.group("a"), em.group("b")
            _add_node(a, "box", a)
            _add_node(b, "box", b)
            edge = {"from": a, "to": b, "kind": "arrow"}
            if em.group("label"):
                edge["text"] = _strip_quotes(em.group("label"))
            edges.append(edge)

    if not nodes:
        raise MermaidError("no nodes found in flowchart")
    return {"direction": direction, "nodes": nodes, "edges": edges, "order": order}


def parse_sequence(lines: list[str]) -> dict:
    participants: list[str] = []
    aliases: dict[str, str] = {}
    messages: list[dict] = []

    for raw in lines[1:]:
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        pm = re.match(r"participant\s+([A-Za-z0-9_]+)(?:\s+as\s+(.+))?$", line)
        if pm:
            pid = pm.group(1)
            if pid not in participants:
                participants.append(pid)
            # `participant C as Web Client` names the lifeline "Web Client". Dropping the
            # alias made the rendered figure show the mermaid id instead of the text the
            # author wrote.
            if pm.group(2):
                aliases[pid] = _strip_quotes(pm.group(2).strip())
            continue
        mm = re.match(
            r"(?P<a>[A-Za-z0-9_]+)\s*(?P<arrow>>>|-->>|->>|-->|-x|x-)\s*(?P<b>[A-Za-z0-9_]+)"
            r"(?:\s*:\s*(?P<label>.+))?$",
            line,
        )
        if mm:
            for pid in (mm.group("a"), mm.group("b")):
                if pid not in participants:
                    participants.append(pid)
            messages.append({
                "from": mm.group("a"), "to": mm.group("b"),
                "label": (mm.group("label") or "").strip(),
                "dashed": "--" in mm.group("arrow"),
            })
            continue
        if re.match(r"^(autonumber|activate|deactivate|Note|loop|alt|else|end|opt|par)\b", line):
            continue  # structural directives: recorded as no-ops for now

    if not participants:
        raise MermaidError("no participants found in sequenceDiagram")
    return {"participants": participants, "aliases": aliases, "messages": messages}


def parse_state(lines: list[str]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    order: list[str] = []

    for raw in lines[1:]:
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if line.startswith("[*]"):
            continue
        tm = re.match(r"(?P<a>[A-Za-z0-9_]+)\s*-->\s*(?P<b>[A-Za-z0-9_]+|\*)\s*(?::\s*(?P<label>.+))?$", line)
        if tm:
            a, b = tm.group("a"), tm.group("b")
            for nid in (a, b):
                if nid != "*" and nid not in nodes:
                    nodes[nid] = {"id": nid, "kind": "box", "label": nid}
                    order.append(nid)
            if b != "*":
                edges.append({"from": a, "to": b, "kind": "arrow",
                              "label": (tm.group("label") or "").strip()})
            continue
        sm = re.match(r"state\s+(?P<id>[A-Za-z0-9_]+)\s*(?::\s*(?P<label>.+))?$", line)
        if sm:
            nid = sm.group("id")
            if nid not in nodes:
                nodes[nid] = {"id": nid, "kind": "box",
                              "label": (sm.group("label") or nid).strip()}
                order.append(nid)

    if not nodes:
        raise MermaidError("no states found in stateDiagram")
    return {"nodes": nodes, "edges": edges, "order": order}


MAX_SOURCE_CHARS = 2_000_000
MAX_LINE_CHARS = 4_000
MAX_LINES = 20_000


def parse(source: str) -> dict:
    # Reject pathological input before any regex runs. A single absurd line is the
    # shape that turns a linear parser quadratic (measured 65s at 50 KB); real diagrams
    # never approach these bounds, so rejecting is cheaper and safer than truncating.
    if len(source) > MAX_SOURCE_CHARS:
        raise MermaidError(f"source too large: {len(source)} > {MAX_SOURCE_CHARS} chars")
    raw_lines = source.splitlines()
    if len(raw_lines) > MAX_LINES:
        raise MermaidError(f"too many lines: {len(raw_lines)} > {MAX_LINES}")
    # Comments are legal before the diagram header (`%% generated by ...`), and taking
    # lines[0] verbatim reported "unsupported diagram type" for a perfectly good file.
    lines = [ln.rstrip() for ln in raw_lines
             if ln.strip() and not ln.lstrip().startswith("%%")]
    for ln in lines:
        if len(ln) > MAX_LINE_CHARS:
            raise MermaidError(f"line too long: {len(ln)} > {MAX_LINE_CHARS} chars")
    if not lines:
        raise MermaidError("empty source")
    header = lines[0].strip().lower()

    if header.startswith(("flowchart", "graph")):
        return {"type": "flowchart", **parse_flowchart(lines)}
    if header.startswith("sequencediagram"):
        return {"type": "sequenceDiagram", **parse_sequence(lines)}
    if header.startswith("statediagram"):
        return {"type": "stateDiagram", **parse_state(lines)}
    raise MermaidError(f"unsupported mermaid diagram type: {lines[0].strip()!r}")


def to_ir(parsed: dict, tokens: str = "academic") -> dict:
    """Turn a parsed mermaid doc into a FigSmith IR.

    Layout is intentionally left empty: `backends.svg.auto_layout` derives node
    positions from the topology by longest-path layering, so the rendered figure
    matches the source structure instead of a greedy left-to-right dump. Every node and
    edge from the source is carried over with the source's own labels, and mermaid's
    own styling never leaks through.
    """
    labels: dict[str, str] = {}
    topo_nodes: list[dict] = []
    topo_edges: list[dict] = []

    if parsed["type"] == "sequenceDiagram":
        for pid in parsed["participants"]:
            labels[pid] = parsed.get("aliases", {}).get(pid, pid)
            topo_nodes.append({"id": pid, "kind": "box"})
        for i, msg in enumerate(parsed["messages"]):
            topo_edges.append({"from": msg["from"], "to": msg["to"], "kind": "arrow"})
            if msg["label"]:
                lid = f"msg{i}"
                labels[lid] = msg["label"]
                topo_edges[-1]["label"] = lid
    else:
        for nid in parsed.get("order", list(parsed["nodes"])):
            node = parsed["nodes"][nid]
            labels[nid] = node["label"]
            entry = {"id": nid, "kind": node["kind"]}
            if node.get("members"):
                # Band membership drives the band's span in auto_layout. It is an optional
                # hint on the band node, documented in IR.md 2.3.
                entry["members"] = list(node["members"])
            topo_nodes.append(entry)
        for edge in parsed["edges"]:
            new_edge = {"from": edge["from"], "to": edge["to"], "kind": "arrow"}
            text = edge.get("text") or edge.get("label")
            if text:
                # Edge text stays on the edge: it is drawn next to the connector, and
                # must not become a node that the layout engine has to place.
                lid = f"el_{len(topo_edges)}"
                labels[lid] = text
                new_edge["label"] = lid
            topo_edges.append(new_edge)

    return {
        "schema": "figsmith.ir/1.0",
        "meta": {
            "domain": "docs-diagram",
            "chart_type": parsed["type"],
            "tokens": tokens,
            "width_unit": 100
        },
        "content": {"labels": labels, "legend": [], "footnote": ""},
        "topology": {"nodes": topo_nodes, "edges": topo_edges},
        "layout": {
            "direction": parsed.get("direction", "top-down"),
            "canvas": {"margin": 3, "px_per_unit": 12, "width_inches": 7.0},
            "grid": {"columns": 4, "gap_x": 2.0, "gap_y": 3.0, "box_w": 20, "box_h": 9},
            "nodes": {},
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
    ap = argparse.ArgumentParser(description="Parse mermaid into a FigSmith IR.")
    ap.add_argument("source")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--tokens", default="academic")
    args = ap.parse_args(argv)

    text = Path(args.source).read_text(encoding="utf-8-sig")
    try:
        parsed = parse(text)
    except MermaidError as exc:
        print(f"parse failed: {exc}", file=sys.stderr)
        return 1

    ir = to_ir(parsed, args.tokens)
    out = args.out or str(Path(args.source).with_suffix(".ir.json"))
    Path(out).write_text(json.dumps(ir, indent=2, ensure_ascii=False), encoding="utf-8")
    n_nodes = len(parsed.get("nodes", parsed.get("participants", [])))
    n_edges = len(parsed.get("edges", parsed.get("messages", [])))
    print(f"parsed {parsed['type']}: {n_nodes} nodes, {n_edges} edges -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
