#!/usr/bin/env python3
"""figsmith IR validator - schema check + cross-layer referential integrity.

Usage:
    python -m core.ir <file.json> [...]      # exit 1 on any error
    python -m core.ir --quiet <file.json>    # only print failures

Checks:
  1. schema/version present
  2. meta.tokens resolvable
  3. topology.nodes[].id unique, kind within the five primitives
  4. every id referenced by edges exists in nodes
  5. every node id has a label in content.labels (warn only)
  6. layout.nodes ids match topology.nodes ids
  7. style token paths resolve against the named token set
  8. data.series[].error_kind declared when yerr present
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tokens import load as load_tokens  # noqa: E402

SCHEMA = "figsmith.ir/1.0"
PRIMITIVES = {"box", "arrow", "polyline", "band", "label"}
REQUIRED_TOP = ("schema", "meta", "content", "topology", "layout", "style")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self, source: str) -> str:
        lines = [f"[{'PASS' if self.ok else 'FAIL'}] {source}"]
        for w in self.warnings:
            lines.append(f"  warn: {w}")
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        return "\n".join(lines)


def validate(ir: dict, rep: Report) -> None:
    if ir.get("schema") != SCHEMA:
        rep.error(f"schema must be '{SCHEMA}', got {ir.get('schema')!r}")
    for key in REQUIRED_TOP:
        if key not in ir:
            rep.error(f"missing required top-level key: {key}")
    if rep.errors:
        return

    meta = ir["meta"]
    if not isinstance(meta, dict):
        rep.error("meta must be an object")
        return
    for key in ("domain", "chart_type", "tokens"):
        if not meta.get(key):
            rep.error(f"meta.{key} is required")

    tokens = None
    try:
        tokens = load_tokens(meta.get("tokens"))
    except Exception as exc:  # noqa: BLE001
        rep.error(f"meta.tokens cannot be loaded: {exc}")

    # A statistical figure carries its content in the data layer, not in topology:
    # its "elements" are series, not nodes. Both shapes are valid IR.
    is_statistical = bool(ir.get("data", {}).get("series"))

    topo = ir["topology"]
    nodes = topo.get("nodes")
    if is_statistical:
        if nodes is None:
            rep.error("topology.nodes must be present (empty list is fine for statistical figures)")
            return
    else:
        if not isinstance(nodes, list) or not nodes:
            rep.error("topology.nodes must be a non-empty list for structural figures")
            return

    seen_ids: set[str] = set()
    for node in nodes:
        nid = node.get("id")
        if not nid:
            rep.error(f"topology node without id: {node!r}")
            continue
        if nid in seen_ids:
            rep.error(f"duplicate node id: {nid}")
        seen_ids.add(nid)
        kind = node.get("kind")
        if kind not in PRIMITIVES:
            rep.error(f"node {nid}: kind {kind!r} not in primitives {sorted(PRIMITIVES)}")

    for edge in topo.get("edges", []):
        for end in ("from", "to"):
            target = edge.get(end)
            if target not in seen_ids:
                rep.error(f"edge {edge.get('from')!r}->{edge.get('to')!r}: {end} {target!r} not in nodes")
        ekind = edge.get("kind", "arrow")
        if ekind not in PRIMITIVES:
            rep.error(f"edge {edge.get('from')}->{edge.get('to')}: kind {ekind!r} invalid")

    labels = ir["content"].get("labels", {})
    if not isinstance(labels, dict):
        rep.error("content.labels must be an object")
        labels = {}
    # Edge labels use their own key namespace: they are legitimately not node ids.
    edge_label_keys = {e.get("label") for e in topo.get("edges", []) if e.get("label")}
    for key in labels:
        if key not in seen_ids and key not in edge_label_keys:
            rep.warn(f"content.labels has orphan key {key!r} (neither a node id nor an edge label)")

    layout = ir["layout"]
    layout_nodes = layout.get("nodes", {})
    if not isinstance(layout_nodes, dict):
        rep.error("layout.nodes must be an object")
        layout_nodes = {}
    # An empty layout.nodes is valid: the renderer derives positions from the topology
    # by longest-path layering (backends.svg.auto_layout). The validator mirrors that
    # so it never reports a figure the renderer would happily place.
    if not layout_nodes and topo.get("nodes"):
        from backends.svg import auto_layout  # noqa: PLC0415
        try:
            layout_nodes = auto_layout(ir, layout.get("direction", "top-down"))
        except Exception as exc:  # noqa: BLE001
            rep.error(f"auto_layout failed: {exc}")
            layout_nodes = {}
    for nid in layout_nodes:
        if nid not in seen_ids:
            rep.error(f"layout.nodes references unknown node id: {nid}")
    for nid in seen_ids:
        if nid not in layout_nodes:
            rep.warn(f"node {nid} has no layout entry (grid auto-placement applies)")
    if "canvas" not in layout:
        rep.warn("layout.canvas missing; canvas derived from content + margin")
    if "grid" not in layout:
        rep.warn("layout.grid missing; nodes need explicit coordinates")

    if tokens is not None:
        style = ir["style"]
        _check_token_paths(style.get("fill", {}), tokens, "style.fill", rep)
        _check_token_paths(style.get("stroke", {}), tokens, "style.stroke", rep)
        _check_token_paths(style.get("text", {}), tokens, "style.text", rep)
        emphasis = style.get("emphasis", [])
        if isinstance(emphasis, list) and len(emphasis) > 3:
            rep.error(f"style.emphasis has {len(emphasis)} entries; max is 3 (METHOD 1.2)")
        if isinstance(emphasis, list):
            for nid in emphasis:
                if nid not in seen_ids:
                    rep.error(f"style.emphasis references unknown node: {nid}")

    data = ir.get("data")
    if data is not None:
        series = data.get("series", [])
        if not series:
            rep.error("data.series must be non-empty when data is present")
        for i, s in enumerate(series):
            if "yerr" in s and not s.get("error_kind"):
                rep.error(f"data.series[{i}] has yerr but no error_kind (must be CI/SD/SE)")
            for axis in ("x", "y"):
                if not isinstance(s.get(axis), list):
                    rep.error(f"data.series[{i}].{axis} must be a list")
            if len(s.get("x", [])) != len(s.get("y", [])):
                rep.error(f"data.series[{i}]: x and y length mismatch")
        if not data.get("units"):
            rep.warn("data.units missing; axes must declare units or write a.u.")


def _check_token_paths(mapping, tokens, where: str, rep: Report) -> None:
    if not isinstance(mapping, dict):
        rep.error(f"{where} must be an object")
        return
    for key, path in mapping.items():
        if not isinstance(path, str):
            rep.error(f"{where}.{key} must be a token path string, got {type(path).__name__}")
            continue
        if path.startswith("#"):
            rep.error(f"{where}.{key} is a raw hex ({path}); use a semantic token path")
            continue
        try:
            val = tokens.get(path)
        except Exception as exc:  # noqa: BLE001
            rep.error(f"{where}.{key}: token path {path!r} unresolvable ({exc})")
            continue
        if val is None:
            rep.error(f"{where}.{key}: token path {path!r} not found in token set {tokens.name!r}")


def validate_file(path: str | Path) -> Report:
    p = Path(path)
    rep = Report()
    try:
        ir = json.loads(p.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        rep.error(f"file not found: {p}")
        return rep
    except json.JSONDecodeError as exc:
        rep.error(f"invalid JSON: {exc}")
        return rep
    validate(ir, rep)
    return rep


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    failed = 0
    for f in files:
        rep = validate_file(f)
        if rep.errors or not quiet:
            print(rep.render(f))
        if not rep.ok:
            failed += 1
    print(f"{len(files) - failed}/{len(files)} valid")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
